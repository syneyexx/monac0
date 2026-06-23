from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class LearningIntent:
    topic: str
    rounds: int
    broad: bool = False
    start_year: int | None = None
    end_year: int | None = None
    raw: str = ""


def _explicit_rounds(text: str) -> bool:
    t = (text or "").lower()
    return bool(re.search(r"\b(?:rounds|rondes)\s*=\s*\d+\b|\b\d+\s*(?:rounds?|rondes?)\b", t))


def parse_rounds(text: str, default: int = 3, max_rounds: int = 10) -> int:
    """Return the requested research depth.

    M0N4C0 treats learning as expert-level by default. Explicit rounds still work
    for power users, but normal language like "leer pokemon" or "leer elke
    pokemon" escalates to max depth automatically.
    """
    t = text.lower()
    patterns = [
        r"rounds\s*=\s*(\d+)",
        r"rondes\s*=\s*(\d+)",
        r"(\d+)\s*rondes?",
        r"(\d+)\s*rounds?",
    ]
    for pattern in patterns:
        m = re.search(pattern, t)
        if m:
            try:
                return max(1, min(int(m.group(1)), max_rounds))
            except Exception:
                pass
    if any(k in t for k in ["expert", "alles", "elke", "ieder", "alle", "complete", "volledig", "diep", "deep", "research"]):
        return max_rounds
    return max(1, min(default, max_rounds))


def parse_year_range(text: str) -> tuple[int | None, int | None]:
    t = text.lower()
    # 1995 - 2025 / 1995 tot 2025 / 1995 tot en met het jaar 2026 / tussen 1995 en 2025
    m = re.search(
        r"(19\d{2}|20\d{2})\s*(?:-|tot(?:\s+en\s+met)?|t/m|tm|en|–|—)\s*(?:het\s+jaar\s*)?(19\d{2}|20\d{2})",
        t,
    )
    if not m:
        return None, None
    a, b = int(m.group(1)), int(m.group(2))
    if a > b:
        a, b = b, a
    # keep sane but broad enough
    if b - a > 100:
        b = a + 100
    return a, b


def _clean_learning_topic(topic: str) -> str:
    topic = (topic or "").strip(" .!?:;\n\t")
    topic = re.sub(r"\b(rounds|rondes)\s*=\s*\d+\b", "", topic, flags=re.I).strip()
    topic = re.sub(r"\b\d+\s*(rounds|rondes?)\b", "", topic, flags=re.I).strip()
    topic = re.sub(
        r"[, ]*\b(?:vanaf|tussen|van)\s+(?:het\s+jaar\s*)?\d{4}.*$",
        "",
        topic,
        flags=re.I,
    ).strip()
    topic = re.sub(
        r"\b(19\d{2}|20\d{2})\s*(?:-|tot(?:\s+en\s+met)?|t/m|tm|en|–|—)\s*(?:het\s+jaar\s*)?(19\d{2}|20\d{2})\b",
        "",
        topic,
        flags=re.I,
    ).strip()
    # Strip stacked Dutch modifiers: "alles over elke voetbalwedstrijd" -> "voetbalwedstrijd".
    previous = None
    while previous != topic:
        previous = topic
        topic = re.sub(r"^(?:alles\s+over|alles\s+van|elke|ieder|alle|over|van)\s+", "", topic, flags=re.I).strip()
    topic = re.sub(r"\s+", " ", topic)
    return topic.strip(" ,.-")


def parse_natural_learning_intent(text: str, default_rounds: int = 3, max_rounds: int = 10) -> LearningIntent | None:
    raw = (text or "").strip()
    if not raw:
        return None
    t = raw.lower().strip()

    # Specific natural-language learning triggers. Commands are still allowed,
    # but the user can just ask normally. Keep generic "zoek ..." out of this
    # parser so quick web-search remains a normal chat feature.
    patterns = [
        r"^(?:leer|bestudeer)\s+(?:mij\s+)?(?P<topic>.+)$",
        r"^(?:onderzoek|research)\s+(?:alles\s+over\s+|diep\s+over\s+|expert\s+over\s+)?(?P<topic>.+)$",
        r"^(?:zoek\s+alles\s+uit\s+over|zoek\s+diep\s+uit\s+over)\s+(?P<topic>.+)$",
        r"^(?:word|wordt|become)\s+expert\s+(?:in|over)\s+(?P<topic>.+)$",
        r"^(?:maak\s+(?:jezelf|mij|de\s+bot)\s+expert\s+(?:in|over))\s+(?P<topic>.+)$",
        r"^(?:learn\s+(?:everything\s+about|all\s+about)|deep\s+research)\s+(?P<topic>.+)$",
    ]
    topic = ""
    for pattern in patterns:
        m = re.search(pattern, t, flags=re.I)
        if m:
            # Preserve original casing where possible by slicing after the first verb.
            topic = m.group("topic")
            # If the regex ran against lowercase text, recover the same span from raw.
            span = m.span("topic")
            topic = raw[span[0]:span[1]]
            break
    if not topic:
        return None

    topic = _clean_learning_topic(topic)
    if not topic:
        return None

    sy, ey = parse_year_range(raw)
    broad_words = ["alles", "elke", "ieder", "alle", "complete", "volledig", "expert", "tussen", "vanaf", "199", "20"]
    broad = any(w in t for w in broad_words) or (sy is not None and ey is not None)

    # Expert-level is the floor for natural learning. No casual/low-depth mode.
    # Natural learning requests always use max research depth.
    rounds = max_rounds
    return LearningIntent(topic=topic, rounds=rounds, broad=broad, start_year=sy, end_year=ey, raw=raw)

def build_broad_queries(topic: str, start_year: int | None = None, end_year: int | None = None, rounds: int = 10) -> list[str]:
    topic_clean = topic.strip()
    queries: list[str] = []
    if start_year is not None and end_year is not None:
        years = list(range(start_year, end_year + 1))
        # For big year ranges: every year, but cap initial plan to a reasonable number; subsequent rounds explore more.
        for y in years:
            queries.append(f"{topic_clean} {y} complete records results overview")
        queries.append(f"{topic_clean} {start_year}-{end_year} dataset complete list archive")
        queries.append(f"{topic_clean} historical statistics {start_year} {end_year}")
    else:
        queries.extend([
            f"{topic_clean} complete overview",
            f"{topic_clean} expert guide",
            f"{topic_clean} history timeline dataset",
            f"{topic_clean} key facts concepts examples",
        ])
    # Stable de-dupe preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        q = re.sub(r"\s+", " ", q).strip()
        if q.lower() not in seen:
            out.append(q)
            seen.add(q.lower())
    return out[: max(4, min(len(out), max(10, rounds * 6)))]
