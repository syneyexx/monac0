from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .response_guard import finalize_answer

if TYPE_CHECKING:
    from .llm import LMStudioClient


DUTCH_SIGNAL_WORDS = {
    "ik", "jij", "je", "jou", "jouw", "wij", "we", "mijn", "zijn", "haar",
    "de", "het", "een", "en", "of", "maar", "want", "niet", "geen", "wel",
    "wat", "waar", "waarom", "hoe", "kan", "kun", "kunt", "moet", "mag",
    "als", "dan", "dus", "ook", "nog", "graag", "aub", "dankjewel", "bedankt",
    "maak", "fix", "zorg", "antwoord", "nederlands", "engels", "bericht",
    "vraag", "leren", "onderzoeken", "zoeken", "bestand", "source", "laatste",
}

ENGLISH_SIGNAL_WORDS = {
    "the", "and", "or", "but", "because", "with", "without", "what", "where",
    "why", "how", "can", "could", "should", "would", "this", "that", "these",
    "those", "your", "you", "i", "we", "they", "answer", "question", "please",
    "first", "then", "also", "from", "into", "about", "when", "while", "make",
    "create", "fix", "use", "using", "default", "local", "model", "response",
}

EXPLICIT_ENGLISH_PATTERNS = [
    r"\bin het engels\b",
    r"\bengels graag\b",
    r"\bantwoord in english\b",
    r"\banswer in english\b",
    r"\bin english\b",
    r"\btranslate to english\b",
    r"\bvertaal (dit|het)?\s*(naar|in) engels\b",
]

EXPLICIT_OTHER_LANGUAGE_PATTERNS = [
    r"\bin het duits\b",
    r"\bin het frans\b",
    r"\bin het spaans\b",
    r"\bin arabisch\b",
    r"\bin turks\b",
    r"\bin pools\b",
]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zA-ZÀ-ÿ']+", (text or "").lower())


def user_wants_non_dutch(text: str) -> bool:
    t = (text or "").lower()
    return any(re.search(p, t) for p in EXPLICIT_ENGLISH_PATTERNS + EXPLICIT_OTHER_LANGUAGE_PATTERNS)


def user_is_dutch_or_default(text: str) -> bool:
    """M0N4C0 is Romy's bot, so default language is Dutch.

    We still detect explicit English requests and leave those alone.
    """
    if user_wants_non_dutch(text):
        return False
    words = _words(text)
    if not words:
        return True
    dutch = sum(1 for w in words if w in DUTCH_SIGNAL_WORDS)
    english = sum(1 for w in words if w in ENGLISH_SIGNAL_WORDS)
    # If the user mixes Dutch and English tech terms, prefer Dutch.
    if dutch >= 1:
        return True
    if english >= 5 and dutch == 0:
        return False
    return True


def _strip_code_blocks(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    text = re.sub(r"`[^`]+`", " ", text)
    return text


def answer_looks_mostly_english(text: str) -> bool:
    """Heuristic detector for accidental English natural-language replies.

    Code blocks, commands and file paths are ignored so technical answers do not
    get translated just because they contain Python/CLI snippets.
    """
    plain = _strip_code_blocks(text)
    words = _words(plain)
    if len(words) < 8:
        return False

    dutch = sum(1 for w in words if w in DUTCH_SIGNAL_WORDS)
    english = sum(1 for w in words if w in ENGLISH_SIGNAL_WORDS)

    # Extra common English phrase signals.
    phrase_hits = len(re.findall(
        r"\b(the|this|that|with|without|because|should|would|could|answer|question|example|however|therefore|basically)\b",
        plain.lower(),
    ))

    # If there are enough Dutch words, let it pass. Straattaal/tech NL can be
    # mixed, so only rewrite when English is clearly dominant.
    return english + phrase_hits >= max(6, dutch * 3 + 4)


def ensure_dutch_answer(user_text: str, answer: str, llm: "LMStudioClient | None" = None) -> str:
    """Force Dutch output for Dutch/default conversations.

    If the model accidentally replies in English, ask the local LLM to rewrite
    only the prose into Dutch. Code blocks, commands, file paths and variable
    names must stay unchanged.
    """
    cleaned = finalize_answer(answer, [])
    if not cleaned:
        return cleaned
    if not user_is_dutch_or_default(user_text):
        return cleaned
    if not answer_looks_mostly_english(cleaned):
        return cleaned
    if llm is None:
        return cleaned

    system = (
        "Je bent een taal-corrector voor M0N4C0. "
        "Herschrijf het antwoord volledig naar natuurlijk Nederlands. "
        "Behoud codeblokken, commands, bestandsnamen, modelnamen, URLs en technische termen letterlijk waar nodig. "
        "Voeg geen nieuwe informatie toe. Verwijder niets belangrijks. "
        "Geef alleen het herschreven antwoord terug."
    )
    user = (
        "Zet dit antwoord om naar Nederlands. "
        "Laat code/commands letterlijk hetzelfde:\n\n"
        f"{cleaned}"
    )
    try:
        result = llm.safe_chat(system=system, user=user, context="", attempts=2)
        rewritten = finalize_answer(result.text, [])
        if rewritten and not answer_looks_mostly_english(rewritten):
            return rewritten
    except Exception:
        pass
    return cleaned
