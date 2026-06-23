from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .db import MonacoDB
from .llm import LMStudioClient, get_system_prompt
from .personality import build_personality_prompt, load_personality
from .memory import build_memory_context
from .retrieval import RetrievalEngine
from .response_guard import finalize_answer
from .utils import sha256_text
from .worldclass import ContextBudgetManager, ConversationQualityScanner, FreshnessDecision, FreshnessGuard, SkillMemory


@dataclass(slots=True)
class Answer:
    text: str
    used_local_chunks: int
    cached: bool = False
    technical: str = ""
    freshness_label: str = "stable"
    confidence: str = "medium"
    source_summary: str = "database/LLM"


class ReasoningEngine:
    def __init__(self, settings: Settings, db: MonacoDB, llm: LMStudioClient):
        self.settings = settings
        self.db = db
        self.llm = llm
        self.retrieval = RetrievalEngine(db)
        self.freshness = FreshnessGuard()
        self.budget = ContextBudgetManager(settings.llm_max_context_chars)
        self.quality = ConversationQualityScanner()
        self.skill_memory = SkillMemory(db)

    def answer(self, question: str, chat_id: str = "terminal", user_key: str | None = None, use_cache: bool = True, freshness_decision: FreshnessDecision | None = None) -> Answer:
        previous_answers = self._recent_assistant_answers(chat_id, limit=6)
        decision = freshness_decision or self.freshness.classify(question)
        cache_key = sha256_text(f"answer|{decision.label}|{question}".lower())
        if use_cache and decision.label == "stable":
            cached = self.db.cache_get(cache_key)
            if cached:
                cached = finalize_answer(cached, previous_answers)
                return Answer(cached, 0, cached=True, technical="cache-hit", freshness_label=decision.label, confidence="medium", source_summary="cache")

        profile = load_personality(self.settings)
        memory_context = ""
        if profile.toggles.get("long_term_memory", True) and profile.toggles.get("context_awareness", True):
            memory_context = build_memory_context(self.db, question, chat_id, user_key)
        skill_context = self.skill_memory.context(limit=10)
        budget = self.budget.budget_for(decision.label)
        retrieval = self.retrieval.retrieve(
            question,
            limit=budget["retrieval_limit"],
            max_chars=budget["context_chars"],
            allow_stale=decision.label != "fresh",
        )
        context_parts = []
        if memory_context.strip():
            context_parts.append("[Memory/context]\n" + memory_context)
        if skill_context.strip():
            context_parts.append("[Skill memory / werkvoorkeuren]\n" + skill_context)
        if retrieval.context.strip():
            context_parts.append("[Lokale kennis — let op freshness/confidence in headers]\n" + retrieval.context)
        context = self.budget.trim("\n\n".join(context_parts), budget["context_chars"])
        system = (
            get_system_prompt(self.settings)
            + "\n"
            + build_personality_prompt(self.settings)
            + "\n"
            + "Je redeneert zorgvuldig, maar toont geen verborgen chain-of-thought. "
            + "Geef wel een korte bron-/zekerheidssamenvatting als info onzeker of actueel is. "
            + "Antwoord standaard in het Nederlands; alleen Engels als de gebruiker expliciet om Engels vraagt. "
            + "Gebruik lokale bronnen alleen als context en let op freshness/confidence metadata. "
            + "Als de vraag actueel is maar er geen live web-check is gedaan, zeg duidelijk dat dit niet actueel geverifieerd is. "
            + "Verzin niets. Zeg eerlijk wanneer je iets niet weet. "
            + "Antwoord alleen op de laatste vraag/opdracht van de gebruiker. "
            + "Chatgeschiedenis is alleen referentie: herhaal geen oude assistant-antwoorden letterlijk. "
            + "Lever precies één schoon eindantwoord."
        )
        user = (
            f"Vraagclassificatie: {decision.label} (confidence {decision.confidence:.2f}; reason: {decision.reason}).\n"
            f"Gebruikersvraag: {question}"
        )
        result = self.llm.safe_chat(system=system, user=user, context=context, attempts=3)
        answer = finalize_answer(result.text, previous_answers)
        source_titles = [str(ch.get("title") or ch.get("url") or "bron") for ch in retrieval.chunks[:4]]
        scanned, report = self.quality.scan(question, answer, freshness=decision, sources=source_titles, web_checked=False)
        answer = scanned
        try:
            self.db.add_quality_report("reasoning", question, answer[:900], report.get("confidence", "medium"), report.get("warnings", []), {"freshness": decision.label, "chunks": len(retrieval.chunks)})
        except Exception:
            pass
        self.db.cache_set(cache_key, question, answer, retrieval.context_hash, {"chunks": len(retrieval.chunks), "freshness": decision.label, "confidence": report.get("confidence")})
        tech = f"chunks={len(retrieval.chunks)} model={self.settings.lmstudio_model} freshness={decision.label}"
        return Answer(
            answer,
            len(retrieval.chunks),
            cached=False,
            technical=tech,
            freshness_label=decision.label,
            confidence=str(report.get("confidence", "medium")),
            source_summary="lokale database/LLM",
        )

    def _recent_assistant_answers(self, chat_id: str, limit: int = 6) -> list[str]:
        try:
            with self.db.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT content FROM conversations
                    WHERE chat_id=? AND role='assistant'
                    ORDER BY id DESC LIMIT ?
                    """,
                    (chat_id, limit),
                ).fetchall()
            return [str(r["content"] or "") for r in rows]
        except Exception:
            return []

    def _looks_time_sensitive(self, text: str) -> bool:
        return self.freshness.classify(text).needs_web
