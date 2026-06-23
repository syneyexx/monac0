from __future__ import annotations

import hashlib
import re
import textwrap

from .response_guard import clean_model_output, looks_like_bad_fallback
from datetime import datetime, timezone
from typing import Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_answer(text: str) -> str:
    if not text:
        return ""
    text = clean_model_output(text)
    if not text or looks_like_bad_fallback(text):
        return ""
    return text


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def chunk_text(text: str, max_chars: int = 3000, overlap: int = 300) -> list[str]:
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current.strip())
            if len(para) <= max_chars:
                current = para
            else:
                parts = textwrap.wrap(para, width=max_chars, break_long_words=False, replace_whitespace=False)
                chunks.extend(p.strip() for p in parts[:-1])
                current = parts[-1] if parts else ""
    if current:
        chunks.append(current.strip())
    if overlap <= 0 or len(chunks) < 2:
        return chunks
    overlapped: list[str] = []
    prev_tail = ""
    for ch in chunks:
        combined = (prev_tail + "\n" + ch).strip() if prev_tail else ch
        overlapped.append(combined)
        prev_tail = ch[-overlap:]
    return overlapped


def truncate_middle(text: str, max_chars: int) -> str:
    """Shorten text for internal context without leaking ugly markers.

    Older builds inserted ``...[ingekort]...`` in the middle. Some local LLMs
    copied that marker into their final answer. This version keeps the start and
    end, but uses a quiet separator that is unlikely to be repeated verbatim.
    """
    if len(text) <= max_chars:
        return text
    max_chars = max(200, int(max_chars))
    separator = "\n\n--- omitted internal context ---\n\n"
    head = max_chars // 2
    tail = max(0, max_chars - head - len(separator))
    return text[:head].rstrip() + separator + text[-tail:].lstrip()


def split_telegram(text: str, max_len: int = 3800, add_part_numbers: bool = True) -> list[str]:
    """Split text into Telegram-safe message chunks.

    Telegram text messages have a hard 4096-character limit. The old splitter
    only split on newlines, so a single long paragraph/line could still exceed
    the limit and Telegram would reject or cut the reply. This splitter prefers
    clean boundaries in this order:

    1. paragraphs
    2. lines
    3. sentences
    4. words
    5. hard character fallback

    It also leaves room for optional [1/3] part labels. Plain text is used in
    telegram_bot.py, so we do not need Markdown escaping here.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return [""]

    # Keep a safety margin below Telegram's 4096 limit for prefixes and unicode
    # edge-cases. Never allow a tiny value that would make splitting unstable.
    max_len = max(500, min(int(max_len or 3800), 4000))
    work_limit = max_len - 32 if add_part_numbers else max_len

    def hard_split(piece: str, limit: int) -> list[str]:
        return [piece[i:i + limit] for i in range(0, len(piece), limit)]

    def split_words(piece: str, limit: int) -> list[str]:
        if len(piece) <= limit:
            return [piece]
        chunks: list[str] = []
        current = ""
        for word in re.findall(r"\S+\s*", piece):
            if len(word) > limit:
                if current.strip():
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(hard_split(word.strip(), limit))
                continue
            if len(current) + len(word) > limit:
                if current.strip():
                    chunks.append(current.strip())
                current = word
            else:
                current += word
        if current.strip():
            chunks.append(current.strip())
        return chunks

    def split_sentences(piece: str, limit: int) -> list[str]:
        if len(piece) <= limit:
            return [piece]
        # Keep sentence punctuation attached while allowing Dutch/English text.
        sentences = re.split(r"(?<=[.!?])\s+", piece)
        if len(sentences) <= 1:
            return split_words(piece, limit)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > limit:
                if current:
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(split_words(sentence, limit))
                continue
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) > limit:
                if current:
                    chunks.append(current.strip())
                current = sentence
            else:
                current = candidate
        if current:
            chunks.append(current.strip())
        return chunks

    def split_lines(piece: str, limit: int) -> list[str]:
        if len(piece) <= limit:
            return [piece]
        chunks: list[str] = []
        current = ""
        for line in piece.splitlines():
            line = line.rstrip()
            if not line:
                candidate = (current + "\n").strip("\n")
                if len(candidate) <= limit:
                    current = candidate
                    continue
            if len(line) > limit:
                if current.strip():
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(split_sentences(line, limit))
                continue
            candidate = f"{current}\n{line}".strip("\n") if current else line
            if len(candidate) > limit:
                if current.strip():
                    chunks.append(current.strip())
                current = line
            else:
                current = candidate
        if current.strip():
            chunks.append(current.strip())
        return chunks

    raw_parts: list[str] = []
    current = ""
    paragraphs = re.split(r"\n\s*\n", text)
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) > work_limit:
            if current.strip():
                raw_parts.append(current.strip())
                current = ""
            raw_parts.extend(split_lines(para, work_limit))
            continue
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) > work_limit:
            if current.strip():
                raw_parts.append(current.strip())
            current = para
        else:
            current = candidate
    if current.strip():
        raw_parts.append(current.strip())

    # Final guard: no part may exceed the work limit.
    guarded: list[str] = []
    for part in raw_parts:
        if len(part) <= work_limit:
            guarded.append(part)
        else:
            guarded.extend(split_words(part, work_limit))

    parts = [p.strip() for p in guarded if p.strip()] or [""]
    if add_part_numbers and len(parts) > 1:
        total = len(parts)
        numbered: list[str] = []
        for idx, part in enumerate(parts, start=1):
            prefix = f"[{idx}/{total}]\n"
            available = max_len - len(prefix)
            if len(part) <= available:
                numbered.append(prefix + part)
            else:
                # Extremely rare because work_limit already reserves space, but
                # keep it bulletproof.
                for sub in split_words(part, available):
                    numbered.append(prefix + sub)
        return numbered
    return parts


def safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default
