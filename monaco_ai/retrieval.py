from __future__ import annotations

from dataclasses import dataclass

from .db import MonacoDB
from .utils import sha256_text
from .worldclass import SourceJudge


@dataclass(slots=True)
class RetrievalResult:
    context: str
    chunks: list[dict]
    context_hash: str


class RetrievalEngine:
    def __init__(self, db: MonacoDB):
        self.db = db
        self.source_judge = SourceJudge(db)

    def retrieve(self, query: str, limit: int = 8, max_chars: int = 9000, *, allow_stale: bool = True) -> RetrievalResult:
        rows = self.db.fts_search(query, limit=limit * 3)
        seen: set[int] = set()
        chunks: list[dict] = []
        for row in rows:
            rid = int(row["id"])
            if rid in seen:
                continue
            seen.add(rid)
            keys = set(row.keys())
            created_at = str(row["created_at"] or "") if "created_at" in keys else ""
            source_type = str(row["source_type"] or "database") if "source_type" in keys else "database"
            verdict = self.source_judge.judge(row["url"] if "url" in keys else None, row["title"] if "title" in keys else "", source_type, created_at)
            freshness = float(row["freshness_score"] if "freshness_score" in keys and row["freshness_score"] is not None else verdict.freshness_score)
            confidence = float(row["confidence"] if "confidence" in keys and row["confidence"] is not None else verdict.reliability)
            if not allow_stale and freshness < 0.35:
                continue
            chunks.append({
                "id": rid,
                "title": row["title"],
                "topic": row["topic"],
                "url": row["url"],
                "content": row["content"],
                "summary": row["summary"],
                "score": float(row["score"]) if "score" in keys and row["score"] is not None else 0.0,
                "created_at": created_at,
                "last_checked_at": str(row["last_checked_at"] or "") if "last_checked_at" in keys else "",
                "freshness_score": freshness,
                "confidence": confidence,
                "source_type": source_type,
                "source_label": verdict.label,
            })
            if len(chunks) >= limit:
                break
        lines: list[str] = []
        used_chars = 0
        for i, ch in enumerate(chunks, start=1):
            header = (
                f"[Bron {i}] {ch.get('title') or 'Onbekende bron'} | topic={ch.get('topic') or '-'} | "
                f"url={ch.get('url') or '-'} | source={ch.get('source_type')} | "
                f"freshness={ch.get('freshness_score'):.2f} | confidence={ch.get('confidence'):.2f} | "
                f"created={ch.get('created_at') or '-'} | last_checked={ch.get('last_checked_at') or '-'}"
            )
            content = ch["content"] or ""
            block = header + "\n" + content.strip()
            if used_chars + len(block) > max_chars:
                remaining = max_chars - used_chars
                if remaining > 700:
                    block = block[:remaining].rstrip()
                    lines.append(block)
                break
            lines.append(block)
            used_chars += len(block)
        context = "\n\n".join(lines)
        return RetrievalResult(context=context, chunks=chunks, context_hash=sha256_text(context))

    def debug(self, query: str) -> str:
        result = self.retrieve(query, limit=10, max_chars=4000)
        lines = [f"Retrieval debug voor: {query}", f"Chunks gevonden: {len(result.chunks)}", ""]
        for i, ch in enumerate(result.chunks, start=1):
            lines.append(
                f"{i}. id={ch['id']} title={ch.get('title')} topic={ch.get('topic')} "
                f"score={ch.get('score')} freshness={ch.get('freshness_score'):.2f} confidence={ch.get('confidence'):.2f}"
            )
            preview = (ch.get("content") or "")[:220].replace("\n", " ")
            lines.append(f"   {preview}...")
        return "\n".join(lines)
