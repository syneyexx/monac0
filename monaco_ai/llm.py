from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re

import requests

from .config import Settings
from .response_guard import looks_like_bad_fallback
from .utils import clean_answer, truncate_middle


@dataclass(slots=True)
class LLMResult:
    text: str
    raw: dict[str, Any] | None = None
    used_model: str | None = None
    error: str | None = None


class LMStudioClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.lmstudio_base_url.rstrip("/")
        self.model = settings.lmstudio_model
        self.timeout = settings.lmstudio_timeout

    def health(self) -> str:
        try:
            r = requests.get(f"{self.base_url}/models", timeout=5)
            if r.ok:
                names = []
                try:
                    data = r.json()
                    for item in data.get("data", []):
                        if isinstance(item, dict) and item.get("id"):
                            names.append(str(item["id"]))
                except Exception:
                    pass
                suffix = f" | models: {', '.join(names[:4])}" if names else ""
                coding = getattr(self.settings, "lmstudio_coding_model", "") or self.model
                if coding and coding != self.model:
                    suffix += f" | code model: {coding}"
                return f"ok: {self.base_url}{suffix}"
            return f"waarschuwing: LM Studio gaf HTTP {r.status_code}"
        except Exception as e:
            return f"niet bereikbaar: {e}"

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        model_override: str | None = None,
        base_url_override: str | None = None,
    ) -> LLMResult:
        model = (model_override or self.model or "").strip()
        base_url = (base_url_override or self.base_url).rstrip("/")
        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.settings.llm_temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.settings.llm_max_output_tokens,
            "stream": False,
        }
        # LM Studio accepts OpenAI-compatible payloads plus several llama.cpp
        # generation parameters. Keep these configurable from the GUI but do not
        # fail if an older model/server ignores them.
        for key, attr in {
            "top_p": "llm_top_p",
            "repeat_penalty": "llm_repeat_penalty",
            "top_k": "llm_top_k",
            "min_p": "llm_min_p",
        }.items():
            value = getattr(self.settings, attr, None)
            if value is not None:
                payload[key] = value
        try:
            r = requests.post(f"{base_url}/chat/completions", json=payload, timeout=self.timeout)
            if not r.ok:
                return LLMResult(text="", error=f"LLM HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            cleaned = clean_answer(text)
            if not cleaned or looks_like_bad_fallback(cleaned):
                return LLMResult(text="", raw=data, used_model=model, error="leeg/slecht modelantwoord")
            return LLMResult(text=cleaned, raw=data, used_model=model)
        except requests.Timeout:
            return LLMResult(text="", error=f"timeout na {self.timeout}s naar {base_url}")
        except Exception as e:
            return LLMResult(text="", error=str(e))

    def should_use_coding_model(self, text: str) -> bool:
        """Detect programming/codebase prompts for automatic model routing."""
        if not bool(getattr(self.settings, "llm_programming_router_enabled", True)):
            return False
        coding_model = str(getattr(self.settings, "lmstudio_coding_model", "") or "").strip()
        if not coding_model or coding_model == self.model:
            return False
        lower = (text or "").lower()
        code_tokens = [
            "python", "javascript", "typescript", "html", "css", "sql", "sqlite", "tkinter",
            "script", "code", "codebase", "main.py", ".py", ".js", ".json", "api",
            "functie", "class", "def ", "import ", "traceback", "stacktrace", "error",
            "bug", "fix", "debug", "database manager", "gui", "telegram bot", "programme",
            "programmeren", "programmeer", "refactor", "optimaliseer", "repository", "zip",
        ]
        if any(token in lower for token in code_tokens):
            return True
        return bool(re.search(r"```|\b(select|insert|update|create table|alter table)\b|\b[A-Za-z_][A-Za-z0-9_]+\(.*\)", text or "", re.I | re.S))

    def safe_chat(self, system: str, user: str, context: str = "", attempts: int = 3) -> LLMResult:
        budget = self.settings.llm_max_context_chars
        last_error = None
        forced_role = str(getattr(self.settings, "llm_forced_model_role", "auto") or "auto").strip().lower()
        role_map = {
            "chat": (getattr(self.settings, "lmstudio_model", self.model), getattr(self.settings, "lmstudio_base_url", self.base_url)),
            "code": (getattr(self.settings, "lmstudio_coding_model", self.model), getattr(self.settings, "lmstudio_coding_base_url", self.base_url)),
            "coding": (getattr(self.settings, "lmstudio_coding_model", self.model), getattr(self.settings, "lmstudio_coding_base_url", self.base_url)),
            "research": (getattr(self.settings, "lmstudio_research_model", self.model), getattr(self.settings, "lmstudio_research_base_url", self.base_url)),
            "telegram": (getattr(self.settings, "lmstudio_telegram_model", self.model), getattr(self.settings, "lmstudio_telegram_base_url", self.base_url)),
            "image": (getattr(self.settings, "lmstudio_image_model", self.model), getattr(self.settings, "lmstudio_image_base_url", self.base_url)),
            "trading": (getattr(self.settings, "lmstudio_trading_model", self.model), getattr(self.settings, "lmstudio_trading_base_url", self.base_url)),
        }
        use_coding = self.should_use_coding_model(user + "\n" + context[:2000])
        if forced_role in role_map:
            model_override, base_override = role_map[forced_role]
            model_override = str(model_override or self.model).strip()
            base_override = str(base_override or self.base_url).rstrip("/")
        else:
            model_override = str(getattr(self.settings, "lmstudio_coding_model", "") or "").strip() if use_coding else None
            base_override = str(getattr(self.settings, "lmstudio_coding_base_url", "") or self.base_url).rstrip("/") if use_coding else None
        for attempt in range(max(1, attempts)):
            cut_context = truncate_middle(context, max(1500, budget)) if context else ""
            user_text = user if not cut_context else (
                "ACHTERGRONDCONTEXT VOOR JOU ALLEEN. "
                "Gebruik dit alleen als referentie. Citeer deze headers niet en begin nooit met oude context.\n"
                f"{cut_context}\n\n"
                "LAATSTE GEBRUIKERSVRAAG - beantwoord alleen dit:\n"
                f"{user}"
            )
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ]
            result = self.chat(messages, model_override=model_override, base_url_override=base_override)
            if result.text and not result.error:
                return result
            # If the dedicated programming model is not served right now, fall
            # back to the normal chat model instead of giving a blank answer.
            if model_override:
                fallback = self.chat(messages)
                if fallback.text and not fallback.error:
                    return fallback
                last_error = f"coding model {model_override}: {result.error}; fallback: {fallback.error}"
            else:
                last_error = result.error or "leeg antwoord"
            budget = int(budget * 0.55)
        return LLMResult(
            text=(
                "Ik kan de lokale LLM nu niet goed bereiken of hij gaf geen bruikbaar antwoord.\n\n"
                f"Technische melding: {last_error}\n\n"
                "Check even of LM Studio draait, of het juiste chatmodel/codingmodel geladen is, "
                "en of de Base URL in de LLM Models pagina klopt."
            ),
            error=last_error,
        )


SYSTEM_PROMPT = """Je bent M0N4C0AI, een lokale AI-assistent
BELANGRIJKE TAALREGEL:
- Antwoord standaard in het Nederlands.
- Als de gebruiker Nederlands typt, antwoord altijd Nederlands.
- Als de taal onduidelijk is, kies Nederlands.
- Gebruik alleen Engels wanneer de gebruiker expliciet vraagt om Engels of wanneer het om code, commands, modelnamen, URLs of vaste technische termen gaat.
- Vertaal niet onnodig codeblokken, bestandsnamen, terminal commands of API-namen.

M0N4C0AI:
- Je bent een krachtige lokale assistent voor chat, code, research, databasebeheer en automatisering.
- Je werkt nauwkeurig, controleert aannames, en weigert geen normale hulpvragen zonder reden.

Je communiceert helder, menselijk en direct.
Je gebruikt beschikbare, lokale context wanneer die relevant is.
Je helpt niet met schadelijke, illegale of misbruikgerichte handelingen; bied dan een veilige alternatiefroute.
Toon geen interne chain-of-thought. Geef wel korte technische status als dit nuttig is.
Als je iets niet zeker weet, research je het of geef je het eerlijk toe en stel je een nuttige vervolgstap voor.
Gedraag je als een normale chat-assistent: de gebruiker hoeft geen /ask of /vraag te typen voor gewone vragen.
Niet steeds dat is een leuke vraag! Dat is intressant! zeggen.
"""


def get_system_prompt(settings: Settings) -> str:
    """Return the currently active system prompt.

    The GUI can update `settings.llm_system_prompt` live, so the next model call
    uses the new behavior immediately without restarting the app. Empty/blank
    means: fall back to the built-in default prompt.
    """

    custom = str(getattr(settings, "llm_system_prompt", "") or "").strip()
    return custom if custom else SYSTEM_PROMPT
