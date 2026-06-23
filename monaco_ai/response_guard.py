from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable

BAD_FALLBACK_PATTERNS = [
    "het spijt me dat ik je teleurstel",
    "technische fout",
    "communicatie met de ai-assistentie",
    "i'm sorry to disappoint",
    "technical issue communicating",
]

# Text markers that are allowed inside prompts/context, but must never leak
# into the final user-visible answer.
INTERNAL_LEAK_PATTERNS = [
    r"\[\s*tech\s*:[^\]]*\]",
    r"\.\.\.\s*\[\s*ingekort\s*\]\s*\.\.\.",
    r"\[\s*ingekort\s*\]",
    r"\.\.\.\s*\[\s*context\s+ingekort\s*\]",
    r"\[\s*context\s+ingekort\s*\]",
    r"\.\.\.\s*\[\s*truncated\s*\]\s*\.\.\.",
    r"\[\s*truncated\s*\]",
    r"-{2,}\s*omitted\s+internal\s+context\s*-{2,}",
]


def looks_like_bad_fallback(text: str) -> bool:
    t = (text or "").lower()
    return any(p in t for p in BAD_FALLBACK_PATTERNS)


def clean_model_output(text: str) -> str:
    text = text or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
    text = text.replace("```\n```", "")
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    return text


def scrub_internal_leaks(text: str) -> str:
    """Remove internal context/truncation artifacts from user-visible output.

    Older builds used markers like ``...[ingekort]...`` while shortening chat
    history. Local models sometimes copied that marker into their answer. This
    function is intentionally narrow: it removes only internal markers and prompt
    headers that should never be displayed to the user.
    """
    out = clean_model_output(text)
    if not out:
        return ""

    for pattern in INTERNAL_LEAK_PATTERNS:
        out = re.sub(pattern, " ", out, flags=re.IGNORECASE)

    # Remove full prompt-wrapper lines if a local model copied them.
    out = re.sub(
        r"(?im)^\s*ACHTERGRONDCONTEXT\s+VOOR\s+JOU\s+ALLEEN\..*$\n?",
        "",
        out,
    )
    out = re.sub(
        r"(?im)^\s*Gebruik\s+dit\s+alleen\s+als\s+referentie\..*$\n?",
        "",
        out,
    )
    out = re.sub(
        r"(?im)^\s*LAATSTE\s+GEBRUIKERSVRAAG\s*[-–—:]?.*$\n?",
        "",
        out,
    )
    out = re.sub(r"(?im)^\s*beantwoord\s+alleen\s+dit\s*:\s*$\n?", "", out)

    # If the model accidentally starts by quoting our prompt wrapper, remove the
    # wrapper line, not legitimate content later in the answer.
    out = re.sub(
        r"^\s*(CONTEXT|ACHTERGRONDCONTEXT|ACHTERGRONDCONTEXT VOOR JOU ALLEEN|LAATSTE GEBRUIKERSVRAAG|VRAAG/OPDRACHT|QUESTION|USER|ASSISTANT|RECENTE GESPREKSCONTEXT|RELEVANTE MEMORY FACTS)\s*[:\-–—]?\s*",
        "",
        out,
        flags=re.IGNORECASE,
    )

    # Remove common "old answer" labels if they appear at the beginning.
    out = re.sub(
        r"^\s*(oud antwoord|vorig antwoord|vorige reactie|assistant_samenvatting|assistant summary)\s*:\s*",
        "",
        out,
        flags=re.IGNORECASE,
    )

    # Drop standalone lines that are only internal headers/markers.
    cleaned_lines: list[str] = []
    for line in out.splitlines():
        compact = re.sub(r"\s+", " ", line.strip())
        low = compact.lower().strip(":")
        if not compact:
            cleaned_lines.append(line)
            continue
        if low in {
            "context",
            "vraag/opdracht",
            "recente gesprekscontext",
            "relevante memory facts",
            "achtergrondcontext",
            "achtergrondcontext voor jou alleen",
            "laatste gebruikersvraag",
            "laatste gebruikersvraag - beantwoord alleen dit",
            "assistant_samenvatting",
            "old answer",
            "oud antwoord",
        }:
            continue
        if low.startswith("achtergrondcontext voor jou alleen") or low.startswith("gebruik dit alleen als referentie"):
            continue
        if low.startswith("laatste gebruikersvraag"):
            continue
        if any(re.fullmatch(pattern, compact, flags=re.IGNORECASE) for pattern in INTERNAL_LEAK_PATTERNS):
            continue
        cleaned_lines.append(line)

    out = "\n".join(cleaned_lines)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{4,}", "\n\n\n", out)
    return out.strip()


def _norm(text: str) -> str:
    """Compact text for safe similarity checks."""
    text = scrub_internal_leaks(text or "").lower()
    text = re.sub(r"\[[0-9]+/[0-9]+\]", " ", text)
    text = re.sub(r"`{1,3}", " ", text)
    text = re.sub(r"[^a-z0-9à-ÿ]+", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def _similar(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na[:2500], nb[:2500]).ratio()


def dedupe_repeated_blocks(text: str, *, line_similarity: float = 0.97, paragraph_similarity: float = 0.985) -> str:
    """Remove accidental duplicate paragraphs/lines from a final answer."""
    text = scrub_internal_leaks(text)
    if not text:
        return ""

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    kept: list[str] = []
    seen_norms: set[str] = set()
    for paragraph in paragraphs:
        n = _norm(paragraph)
        if not n:
            continue
        if len(n) >= 45 and n in seen_norms:
            continue
        if len(n) >= 80 and any(_similar(paragraph, old) >= paragraph_similarity for old in kept[-12:]):
            continue
        seen_norms.add(n)
        kept.append(paragraph)

    text = "\n\n".join(kept).strip()

    final_lines: list[str] = []
    recent_lines: list[str] = []
    for line in text.splitlines():
        raw = line.rstrip()
        n = _norm(raw)
        if len(n) >= 35 and any(_similar(raw, old) >= line_similarity for old in recent_lines[-20:]):
            continue
        final_lines.append(raw)
        if n:
            recent_lines.append(raw)
    text = "\n".join(final_lines).strip()
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text


def strip_previous_answer_echo(text: str, previous_answers: Iterable[str] | None = None) -> str:
    """Strip an old assistant answer if the model pasted it before the new answer."""
    out = scrub_internal_leaks(text)
    if not out or not previous_answers:
        return out

    stripped_once = False
    for previous in previous_answers:
        prev = scrub_internal_leaks(previous or "")
        if len(_norm(prev)) < 80:
            continue

        candidates = [prev]
        if len(prev) > 1800:
            candidates.extend([prev[:1800], prev[:1200], prev[:800], prev[:500]])
        elif len(prev) > 900:
            candidates.extend([prev[:900], prev[:600], prev[:400]])
        elif len(prev) > 450:
            candidates.extend([prev[:450], prev[:300]])

        for candidate in candidates:
            cand = candidate.strip()
            if len(_norm(cand)) < 80:
                continue
            prefix = out[: max(len(cand) + 100, 350)]
            if _similar(prefix[:len(cand)], cand) >= 0.955:
                remainder = out[len(cand):].lstrip(" \n\r\t-—–:|.,")
                if len(_norm(remainder)) >= 35:
                    out = remainder.strip()
                    stripped_once = True
                    break
        if stripped_once:
            break
    return out.strip()


def strip_cache_tech_from_plain_answer(text: str) -> str:
    """Remove internal [tech: chunks=...] metadata from user-facing answers."""
    out = text or ""
    out = re.sub(r"\s*\[\s*tech\s*:[^\]]*\]\s*", " ", out, flags=re.IGNORECASE)
    out = re.sub(r"\n{4,}", "\n\n\n", out)
    return out.strip()


def finalize_answer(text: str, previous_answers: Iterable[str] | None = None) -> str:
    """Last-mile output guard for GUI, Telegram and terminal replies."""
    text = strip_cache_tech_from_plain_answer(text)
    text = strip_previous_answer_echo(text, previous_answers)
    text = dedupe_repeated_blocks(text)
    text = scrub_internal_leaks(text)
    return text.strip()
