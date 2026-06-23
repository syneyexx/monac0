from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import webbrowser
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import requests

from .utils import utc_now


@dataclass(slots=True)
class ModelCandidate:
    """A local model discovered from LM Studio API and/or disk scan."""

    id: str
    name: str
    source: str
    path: str = ""
    family: str = "Unknown"
    model_type: str = "Local"
    size_bytes: int = 0
    quantization: str = ""
    architecture: str = ""
    format: str = ""
    loaded: bool = False
    metadata: dict[str, Any] | None = None

    @property
    def size_label(self) -> str:
        if not self.size_bytes:
            return "Unknown"
        value = float(self.size_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if value < 1024 or unit == "TB":
                return f"{value:.2f} {unit}" if unit in {"GB", "TB"} else f"{value:.0f} {unit}"
            value /= 1024
        return "Unknown"

    @property
    def short_id(self) -> str:
        return self.id if len(self.id) <= 58 else self.id[:55] + "..."


@dataclass(slots=True)
class LLMRuntimeConfig:
    """Runtime model settings saved outside .env so the GUI can persist changes.

    `model_id` is the normal chat/research model. `coding_model_id` is used by
    LMStudioClient when a prompt looks like programming, debugging, scripts or
    codebase work. This lets M0N4C0 switch models live without restarting.
    """

    base_url: str
    model_id: str
    coding_base_url: str = ""
    coding_model_id: str = ""
    research_base_url: str = ""
    research_model_id: str = ""
    telegram_base_url: str = ""
    telegram_model_id: str = ""
    image_base_url: str = ""
    image_model_id: str = ""
    trading_base_url: str = ""
    trading_model_id: str = ""
    model_mode: str = "split"  # split or single
    programming_router_enabled: bool = True
    temperature: float = 0.45
    max_tokens: int = 900
    context_chars: int = 18000
    top_p: float = 0.90
    repeat_penalty: float = 1.10
    top_k: int = 40
    min_p: float = 0.05
    system_prompt: str = ""
    updated_at: str = ""

    @classmethod
    def from_settings(cls, settings: Any) -> "LLMRuntimeConfig":
        base = str(getattr(settings, "lmstudio_base_url", "http://localhost:1234/v1")).rstrip("/")
        model = str(getattr(settings, "lmstudio_model", ""))
        coding_base = str(getattr(settings, "lmstudio_coding_base_url", base) or base).rstrip("/")
        coding_model = str(getattr(settings, "lmstudio_coding_model", model) or model)
        return cls(
            base_url=base,
            model_id=model,
            coding_base_url=coding_base,
            coding_model_id=coding_model,
            research_base_url=str(getattr(settings, "lmstudio_research_base_url", base) or base).rstrip("/"),
            research_model_id=str(getattr(settings, "lmstudio_research_model", model) or model),
            telegram_base_url=str(getattr(settings, "lmstudio_telegram_base_url", base) or base).rstrip("/"),
            telegram_model_id=str(getattr(settings, "lmstudio_telegram_model", model) or model),
            image_base_url=str(getattr(settings, "lmstudio_image_base_url", base) or base).rstrip("/"),
            image_model_id=str(getattr(settings, "lmstudio_image_model", model) or model),
            trading_base_url=str(getattr(settings, "lmstudio_trading_base_url", base) or base).rstrip("/"),
            trading_model_id=str(getattr(settings, "lmstudio_trading_model", model) or model),
            model_mode=str(getattr(settings, "llm_model_mode", "split") or "split"),
            programming_router_enabled=bool(getattr(settings, "llm_programming_router_enabled", True)),
            temperature=float(getattr(settings, "llm_temperature", 0.45)),
            max_tokens=int(getattr(settings, "llm_max_output_tokens", 900)),
            context_chars=int(getattr(settings, "llm_max_context_chars", 18000)),
            top_p=float(getattr(settings, "llm_top_p", 0.90)),
            repeat_penalty=float(getattr(settings, "llm_repeat_penalty", 1.10)),
            top_k=int(getattr(settings, "llm_top_k", 40)),
            min_p=float(getattr(settings, "llm_min_p", 0.05)),
            system_prompt=str(getattr(settings, "llm_system_prompt", "") or ""),
            updated_at=utc_now(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any], fallback: "LLMRuntimeConfig") -> "LLMRuntimeConfig":
        def f_float(key: str, default: float) -> float:
            try:
                return float(data.get(key, default))
            except Exception:
                return default

        def f_int(key: str, default: int) -> int:
            try:
                return int(float(data.get(key, default)))
            except Exception:
                return default

        def f_bool(key: str, default: bool) -> bool:
            value = data.get(key, default)
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "aan"}

        base = str(data.get("base_url") or fallback.base_url).rstrip("/")
        model = str(data.get("model_id") or data.get("model") or fallback.model_id)
        coding_base = str(data.get("coding_base_url") or data.get("code_base_url") or fallback.coding_base_url or base).rstrip("/")
        coding_model = str(data.get("coding_model_id") or data.get("code_model_id") or data.get("programming_model_id") or fallback.coding_model_id or model)
        def role_base(role: str) -> str:
            return str(data.get(f"{role}_base_url") or getattr(fallback, f"{role}_base_url", base) or base).rstrip("/")
        def role_model(role: str) -> str:
            return str(data.get(f"{role}_model_id") or getattr(fallback, f"{role}_model_id", model) or model)
        mode = str(data.get("model_mode") or fallback.model_mode or "split")
        if mode not in {"split", "single"}:
            mode = "split"
        if mode == "single":
            coding_base = base
            coding_model = model
        return cls(
            base_url=base,
            model_id=model,
            coding_base_url=coding_base,
            coding_model_id=coding_model,
            research_base_url=role_base("research"),
            research_model_id=role_model("research"),
            telegram_base_url=role_base("telegram"),
            telegram_model_id=role_model("telegram"),
            image_base_url=role_base("image"),
            image_model_id=role_model("image"),
            trading_base_url=role_base("trading"),
            trading_model_id=role_model("trading"),
            model_mode=mode,
            programming_router_enabled=f_bool("programming_router_enabled", fallback.programming_router_enabled),
            temperature=max(0.0, min(2.0, f_float("temperature", fallback.temperature))),
            max_tokens=max(64, min(32768, f_int("max_tokens", fallback.max_tokens))),
            context_chars=max(1500, min(1000000, f_int("context_chars", fallback.context_chars))),
            top_p=max(0.01, min(1.0, f_float("top_p", fallback.top_p))),
            repeat_penalty=max(0.8, min(2.0, f_float("repeat_penalty", fallback.repeat_penalty))),
            top_k=max(0, min(1000, f_int("top_k", fallback.top_k))),
            min_p=max(0.0, min(1.0, f_float("min_p", fallback.min_p))),
            system_prompt=str(data.get("system_prompt") if data.get("system_prompt") is not None else fallback.system_prompt),
            updated_at=str(data.get("updated_at") or utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["updated_at"] = utc_now()
        return payload


def config_path(root_or_settings: Any) -> Path:
    root = getattr(root_or_settings, "root", root_or_settings)
    return Path(root) / "data" / "llm_model_settings.json"


def load_saved_config(settings: Any) -> LLMRuntimeConfig:
    fallback = LLMRuntimeConfig.from_settings(settings)
    path = config_path(settings)
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return LLMRuntimeConfig.from_dict(data, fallback)
    except Exception:
        return fallback
    return fallback


def save_config(settings: Any, cfg: LLMRuntimeConfig) -> None:
    path = config_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def apply_config(settings: Any, router: Any | None, cfg: LLMRuntimeConfig) -> None:
    """Apply runtime config without restarting the app."""

    settings.lmstudio_base_url = cfg.base_url.rstrip("/")
    settings.lmstudio_model = cfg.model_id
    settings.llm_model_mode = cfg.model_mode if cfg.model_mode in {"split", "single"} else "split"
    if settings.llm_model_mode == "single":
        settings.lmstudio_coding_base_url = cfg.base_url.rstrip("/")
        settings.lmstudio_coding_model = cfg.model_id
    else:
        settings.lmstudio_coding_base_url = (cfg.coding_base_url or cfg.base_url).rstrip("/")
        settings.lmstudio_coding_model = cfg.coding_model_id or cfg.model_id
    settings.lmstudio_research_base_url = (cfg.research_base_url or cfg.base_url).rstrip("/")
    settings.lmstudio_research_model = cfg.research_model_id or cfg.model_id
    settings.lmstudio_telegram_base_url = (cfg.telegram_base_url or cfg.base_url).rstrip("/")
    settings.lmstudio_telegram_model = cfg.telegram_model_id or cfg.model_id
    settings.lmstudio_image_base_url = (cfg.image_base_url or cfg.base_url).rstrip("/")
    settings.lmstudio_image_model = cfg.image_model_id or cfg.model_id
    settings.lmstudio_trading_base_url = (cfg.trading_base_url or cfg.base_url).rstrip("/")
    settings.lmstudio_trading_model = cfg.trading_model_id or cfg.model_id
    settings.llm_programming_router_enabled = bool(cfg.programming_router_enabled)
    settings.llm_temperature = float(cfg.temperature)
    settings.llm_max_output_tokens = int(cfg.max_tokens)
    settings.llm_max_context_chars = int(cfg.context_chars)
    if hasattr(settings, "llm_top_p"):
        settings.llm_top_p = float(cfg.top_p)
    if hasattr(settings, "llm_repeat_penalty"):
        settings.llm_repeat_penalty = float(cfg.repeat_penalty)
    if hasattr(settings, "llm_top_k"):
        settings.llm_top_k = int(cfg.top_k)
    if hasattr(settings, "llm_min_p"):
        settings.llm_min_p = float(cfg.min_p)
    if hasattr(settings, "llm_system_prompt"):
        settings.llm_system_prompt = str(cfg.system_prompt or "")

    if router is not None and getattr(router, "llm", None) is not None:
        router.llm.base_url = cfg.base_url.rstrip("/")
        router.llm.model = cfg.model_id
        router.llm.timeout = getattr(settings, "lmstudio_timeout", router.llm.timeout)


class LMStudioModelManager:
    """Discovers and controls local LM Studio models.

    LM Studio versions expose different APIs. This manager is intentionally
    defensive: it uses the OpenAI-compatible /v1/models endpoint, tries LM
    Studio's local /api/v0 endpoints where available, and also scans the usual
    LM Studio model folders for downloaded GGUF files. If model loading is not
    available in the installed LM Studio build, selecting still saves the model
    id and the UI tells the user to load it manually in LM Studio.
    """

    def __init__(self, settings: Any):
        self.settings = settings
        self._disk_models_cache: tuple[float, list[ModelCandidate]] | None = None

    @property
    def base_url(self) -> str:
        return str(getattr(self.settings, "lmstudio_base_url", "http://localhost:1234/v1")).rstrip("/")

    @property
    def server_url(self) -> str:
        url = self.base_url.rstrip("/")
        return url[:-3] if url.endswith("/v1") else url

    def discover_models(self, base_url: str | None = None) -> list[ModelCandidate]:
        if base_url:
            old = self.settings.lmstudio_base_url
            self.settings.lmstudio_base_url = base_url.rstrip("/")
            try:
                return self.discover_models()
            finally:
                self.settings.lmstudio_base_url = old

        found: dict[str, ModelCandidate] = {}
        for candidate in self._api_models_v1() + self._api_models_v0() + self._scan_disk_models():
            if not candidate.id:
                continue
            existing = found.get(candidate.id)
            if existing is None:
                found[candidate.id] = candidate
            else:
                # Merge richer metadata. Loaded/API state wins over disk scan.
                existing.loaded = existing.loaded or candidate.loaded
                if existing.source != candidate.source:
                    existing.source = f"{existing.source} + {candidate.source}"
                for field in ["path", "family", "model_type", "quantization", "architecture", "format"]:
                    if not getattr(existing, field) and getattr(candidate, field):
                        setattr(existing, field, getattr(candidate, field))
                if not existing.size_bytes and candidate.size_bytes:
                    existing.size_bytes = candidate.size_bytes
                meta = dict(existing.metadata or {})
                meta.update(candidate.metadata or {})
                existing.metadata = meta

        active = str(getattr(self.settings, "lmstudio_model", ""))
        for model in found.values():
            if model.id == active or model.name == active:
                model.loaded = True

        return sorted(found.values(), key=lambda m: (not m.loaded, m.name.lower(), m.id.lower()))

    def _api_models_v1(self) -> list[ModelCandidate]:
        models: list[ModelCandidate] = []
        try:
            r = requests.get(f"{self.base_url}/models", timeout=3)
            if not r.ok:
                return models
            data = r.json()
            for item in data.get("data", []) if isinstance(data, dict) else []:
                if not isinstance(item, dict):
                    continue
                mid = str(item.get("id") or item.get("name") or "").strip()
                if not mid:
                    continue
                models.append(ModelCandidate(
                    id=mid,
                    name=self._clean_name(mid),
                    source="LM Studio API",
                    model_type=str(item.get("type") or "Loaded/Served"),
                    loaded=True,
                    metadata=item,
                ))
        except Exception:
            pass
        return models

    def _api_models_v0(self) -> list[ModelCandidate]:
        models: list[ModelCandidate] = []
        endpoints = [f"{self.server_url}/api/v0/models", f"{self.server_url}/api/v0/models/search"]
        for endpoint in endpoints:
            try:
                r = requests.get(endpoint, timeout=3)
                if not r.ok:
                    continue
                payload = r.json()
                raw_items = payload.get("data") if isinstance(payload, dict) else payload
                if isinstance(raw_items, dict):
                    raw_items = raw_items.get("models") or raw_items.get("data") or []
                if not isinstance(raw_items, list):
                    continue
                for item in raw_items:
                    if not isinstance(item, dict):
                        continue
                    mid = str(item.get("id") or item.get("modelKey") or item.get("path") or item.get("name") or "").strip()
                    if not mid:
                        continue
                    size = item.get("sizeBytes") or item.get("size_bytes") or item.get("size") or 0
                    try:
                        size = int(size)
                    except Exception:
                        size = 0
                    loaded = bool(item.get("loaded") or item.get("isLoaded") or item.get("state") == "loaded")
                    models.append(ModelCandidate(
                        id=mid,
                        name=str(item.get("displayName") or item.get("name") or self._clean_name(mid)),
                        source="LM Studio API v0",
                        path=str(item.get("path") or item.get("file") or ""),
                        family=str(item.get("family") or item.get("publisher") or item.get("architecture") or "Unknown"),
                        model_type=str(item.get("type") or item.get("model_type") or "Local"),
                        size_bytes=size,
                        quantization=str(item.get("quantization") or item.get("quant") or ""),
                        architecture=str(item.get("architecture") or item.get("arch") or ""),
                        format=str(item.get("format") or ""),
                        loaded=loaded,
                        metadata=item,
                    ))
            except Exception:
                continue
        return models

    def _scan_disk_models(self) -> list[ModelCandidate]:
        if self._disk_models_cache is not None:
            cached_at, cached_models = self._disk_models_cache
            if time.time() - cached_at < 30:
                return list(cached_models)
        roots = self._model_roots()
        candidates: list[ModelCandidate] = []
        seen_paths: set[Path] = set()
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            try:
                for path in root.rglob("*.gguf"):
                    if path in seen_paths:
                        continue
                    seen_paths.add(path)
                    try:
                        stat = path.stat()
                    except OSError:
                        stat = None
                    model_id = path.stem
                    parent = path.parent.name
                    if parent and parent.lower() not in {"models", ".lmstudio"}:
                        # LM Studio often nests by publisher/model; keep the GGUF
                        # stem as id, but show a nicer human name.
                        name = self._clean_name(parent if parent.lower() not in model_id.lower() else model_id)
                    else:
                        name = self._clean_name(model_id)
                    candidates.append(ModelCandidate(
                        id=model_id,
                        name=name,
                        source="Disk scan",
                        path=str(path),
                        family=self._guess_family(model_id),
                        model_type=self._guess_model_type(model_id),
                        size_bytes=stat.st_size if stat else 0,
                        quantization=self._guess_quant(model_id),
                        architecture=self._guess_arch(model_id),
                        format="GGUF",
                        loaded=False,
                        metadata={"root": str(root)},
                    ))
            except Exception:
                continue
        self._disk_models_cache = (time.time(), list(candidates))
        return candidates

    def _model_roots(self) -> list[Path]:
        env_root = os.getenv("LMSTUDIO_MODELS_DIR")
        home = Path.home()
        roots = []
        if env_root:
            roots.append(Path(env_root).expanduser())
        roots.extend([
            home / ".lmstudio" / "models",
            home / ".cache" / "lm-studio" / "models",
            home / "AppData" / "Local" / "LM Studio" / "models",
            home / "AppData" / "Roaming" / "LM Studio" / "models",
            home / "Documents" / "LM Studio" / "models",
            Path(getattr(self.settings, "root", Path.cwd())) / "models",
        ])
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root).lower()
            if key not in seen:
                seen.add(key)
                unique.append(root)
        return unique

    def test_connection(self, cfg: LLMRuntimeConfig, run_chat_test: bool = False) -> tuple[bool, str]:
        base = cfg.base_url.rstrip("/")
        try:
            start = time.perf_counter()
            r = requests.get(f"{base}/models", timeout=5)
            ms = int((time.perf_counter() - start) * 1000)
            if not r.ok:
                return False, f"LM Studio bereikbaar maar /models gaf HTTP {r.status_code}: {r.text[:180]}"
            data = r.json()
            count = len(data.get("data", [])) if isinstance(data, dict) else 0
            if not run_chat_test:
                return True, f"Connected in {ms} ms. /models returned {count} model(s)."
            payload = {
                "model": cfg.model_id,
                "messages": [
                    {"role": "system", "content": "Reply with exactly: OK"},
                    {"role": "user", "content": "Connection test"},
                ],
                "temperature": 0.1,
                "max_tokens": 8,
                "stream": False,
            }
            start = time.perf_counter()
            rr = requests.post(f"{base}/chat/completions", json=payload, timeout=15)
            ms2 = int((time.perf_counter() - start) * 1000)
            if not rr.ok:
                return False, f"/models OK, maar chat test HTTP {rr.status_code}: {rr.text[:220]}"
            return True, f"Connected. Chat test OK in {ms2} ms. Models visible: {count}."
        except Exception as exc:
            return False, f"Niet bereikbaar: {type(exc).__name__}: {exc}"

    def try_load_model(self, cfg: LLMRuntimeConfig) -> tuple[bool, str]:
        """Best-effort model loading for LM Studio builds that expose v0 control.

        If unsupported, this returns a clear message; the saved model still works
        once the user loads that model in LM Studio.
        """
        server = cfg.base_url.rstrip("/")
        if server.endswith("/v1"):
            server = server[:-3]
        payloads = [
            (f"{server}/api/v0/model/load", {"model": cfg.model_id}),
            (f"{server}/api/v0/models/load", {"model": cfg.model_id}),
            (f"{server}/api/v0/models/{cfg.model_id}/load", {}),
        ]
        errors: list[str] = []
        for url, payload in payloads:
            try:
                r = requests.post(url, json=payload, timeout=10)
                if r.ok:
                    return True, f"Load request accepted by LM Studio: {url}"
                errors.append(f"{r.status_code} at {url}")
            except Exception as exc:
                errors.append(f"{type(exc).__name__} at {url}")
        return False, "Model saved, but LM Studio did not expose a supported load endpoint. Load the model in LM Studio if chat fails. Tried: " + "; ".join(errors[:3])

    def open_lm_studio(self) -> str:
        try:
            # The scheme works on many LM Studio installs; if not, opening the
            # local server URL is still useful for the user.
            if platform.system().lower().startswith("win"):
                subprocess.Popen(["cmd", "/c", "start", "", "lmstudio://"], shell=False)
            else:
                webbrowser.open("lmstudio://")
            return "Opening LM Studio app."
        except Exception:
            try:
                webbrowser.open(self.server_url)
                return f"Opening {self.server_url}."
            except Exception as exc:
                return f"Could not open LM Studio: {type(exc).__name__}: {exc}"

    @staticmethod
    def _clean_name(value: str) -> str:
        text = str(value or "").replace("_", " ").replace("-", " ").strip()
        return " ".join(part.capitalize() if part.islower() else part for part in text.split()) or "Unknown Model"

    @staticmethod
    def _guess_quant(name: str) -> str:
        upper = name.upper()
        for token in ["Q2_K", "Q3_K", "Q4_K_M", "Q4_K_S", "Q4_0", "Q5_K_M", "Q5_K_S", "Q6_K", "Q8_0", "IQ4", "IQ3", "FP16", "BF16"]:
            if token in upper:
                return token
        return ""

    @staticmethod
    def _guess_arch(name: str) -> str:
        lower = name.lower()
        for token in ["llama", "qwen", "mistral", "gemma", "phi", "deepseek", "dolphin", "hermes", "mixtral", "tinyllama", "nous"]:
            if token in lower:
                return token
        return ""

    @staticmethod
    def _guess_family(name: str) -> str:
        arch = LMStudioModelManager._guess_arch(name)
        return arch.title() if arch else "Unknown"

    @staticmethod
    def _guess_model_type(name: str) -> str:
        lower = name.lower()
        if "vision" in lower or "vl" in lower:
            return "Vision"
        if "embed" in lower:
            return "Embedding"
        if "instruct" in lower or "chat" in lower or "dolphin" in lower or "hermes" in lower:
            return "Instruct"
        return "Base/Local"
