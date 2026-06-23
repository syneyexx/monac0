from __future__ import annotations

import re
from typing import Iterable

from .db import MonacoDB
from .utils import truncate_middle


MEM_PATTERNS = [
    (re.compile(r"\bik heet\s+([A-Za-zÀ-ÿ0-9_ .'-]{2,60})", re.I), "user", "name"),
    (re.compile(r"\bmijn naam is\s+([A-Za-zÀ-ÿ0-9_ .'-]{2,60})", re.I), "user", "name"),
    (re.compile(r"\bmijn favoriete ([a-zA-ZÀ-ÿ ]{2,40}) is\s+(.{2,120})", re.I), "user", "favorite"),
    (re.compile(r"\bik werk bij\s+(.{2,120})", re.I), "user", "works_at"),
    (re.compile(r"\bik studeer\s+(.{2,120})", re.I), "user", "studies"),
    (re.compile(r"\bonthoud:?\s+(.{2,500})", re.I), "user", "note"),
]


def learn_from_message(db: MonacoDB, text: str, user_key: str | None = None) -> list[str]:
    learned: list[str] = []
    for rx, subject_default, predicate in MEM_PATTERNS:
        m = rx.search(text or "")
        if not m:
            continue
        if predicate == "favorite" and len(m.groups()) >= 2:
            pred = "favorite_" + re.sub(r"\W+", "_", m.group(1).strip().lower())
            obj = m.group(2).strip()
        else:
            pred = predicate
            obj = m.group(1).strip()
        subject = user_key or subject_default
        db.add_memory_fact(subject=subject, predicate=pred, obj=obj, user_key=user_key, source="conversation", confidence=0.85)
        learned.append(f"{subject} {pred} {obj}")
    return learned


def _same_message(a: str, b: str) -> bool:
    norm = lambda x: re.sub(r"\s+", " ", (x or "").strip().lower())
    return bool(a and b and norm(a) == norm(b))


def _compact_turn(role: str, content: str) -> str:
    """Keep recent chat context useful without feeding old answers back.

    User turns can help with context. Assistant turns are intentionally omitted
    from prompt context because local models often echo them before answering the
    newest question.
    """
    content = (content or "").strip()
    if role == "assistant":
        return ""
    content = truncate_middle(content, 420)
    return content.replace("\r\n", "\n").strip()



def build_memory_context(db: MonacoDB, query: str, chat_id: str, user_key: str | None, limit: int = 12) -> str:
    facts = db.search_memory(query, limit=limit)
    # Pull a few extra rows because we skip the current user message and any
    # internal duplicate assistant writes from older builds.
    recent = db.recent_conversation(chat_id, limit=max(limit + 8, 18))
    lines: list[str] = []
    if facts:
        lines.append("RELEVANTE MEMORY FACTS:")
        for f in facts:
            lines.append(f"- {f['subject']} | {f['predicate']} | {f['object']}")
    if recent:
        lines.append(
            "RECENTE GESPREKSCONTEXT (alleen referentie; herhaal oude assistant-antwoorden niet letterlijk):"
        )
        compact_turns: list[tuple[str, str]] = []
        for r in recent:
            role = str(r["role"])
            content = str(r["content"] or "")
            if role == "user" and _same_message(content, query):
                # The current question is already sent separately as VRAAG/OPDRACHT.
                continue
            compact = _compact_turn(role, content)
            if not compact:
                continue
            compact_turns.append((role, compact))
        # Keep only recent user-side context. Assistant replies are deliberately
        # excluded to prevent old answers leaking into new answers.
        compact_turns = compact_turns[-8:]
        for role, compact in compact_turns:
            lines.append(f"- {role}: {compact}")
    return "\n".join(lines)
