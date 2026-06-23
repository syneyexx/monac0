from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .utils import utc_now, sha256_text

FRESH_KEYWORDS = {
    "vandaag", "morgen", "gisteren", "nu", "actueel", "recent", "laatste", "nieuwste", "latest",
    "news", "nieuws", "prijs", "prijzen", "koers", "schema", "planning", "regels", "wet", "wetten",
    "download", "downloadlink", "link", "versie", "update", "release", "werkt dit nog", "beschikbaar",
    "ceo", "president", "minister", "wie is nu", "beste", "top", "aanbevolen", "2026",
    "crypto", "aandeel", "aandelen", "comfyui", "lm studio", "telegram bot api",
}

STABLE_HINTS = {
    "wat is", "leg uit", "betekenis", "samenvat", "vertaling", "reken", "hoe schrijf", "voorbeeldzin",
    "python uitleg", "basis", "definitie", "geschiedenis", "napoleon", "formule",
}

OFFICIAL_DOMAINS = {
    "docs.python.org", "github.com", "huggingface.co", "core.telegram.org", "wikipedia.org", "en.wikipedia.org",
    "nl.wikipedia.org", "docs.comfy.org", "sqlite.org", "microsoft.com", "openai.com", "anthropic.com",
}

BAD_DOMAIN_HINTS = {"pinterest", "quora", "reddit", "medium", "blogspot", "wordpress", "unknown"}


@dataclass(slots=True)
class FreshnessDecision:
    label: str
    confidence: float
    needs_web: bool
    reason: str


class FreshnessGuard:
    def classify(self, text: str) -> FreshnessDecision:
        t = (text or "").lower().strip()
        if not t:
            return FreshnessDecision("uncertain", 0.2, False, "empty question")
        hits = [kw for kw in FRESH_KEYWORDS if kw in t]
        if hits:
            return FreshnessDecision("fresh", min(0.95, 0.65 + len(hits) * 0.05), True, "fresh terms: " + ", ".join(hits[:6]))
        if re.search(r"\b20(2[5-9]|3\d)\b", t):
            return FreshnessDecision("fresh", 0.8, True, "recent/future year mentioned")
        if any(h in t for h in STABLE_HINTS):
            return FreshnessDecision("stable", 0.72, False, "stable/general explanation pattern")
        if "?" in t and any(w in t for w in ["waar", "welke", "wie", "kan ik", "hoeveel kost"]):
            return FreshnessDecision("uncertain", 0.58, True, "question may depend on current facts")
        return FreshnessDecision("stable", 0.55, False, "no current/freshness trigger detected")


@dataclass(slots=True)
class SourceVerdict:
    url: str
    domain: str
    reliability: float
    freshness_score: float
    label: str
    reason: str


class SourceJudge:
    def __init__(self, db: Any | None = None):
        self.db = db

    def _rules(self) -> dict[str, str]:
        rules: dict[str, str] = {}
        if self.db is None:
            return rules
        try:
            with self.db.connect() as conn:
                rows = conn.execute("SELECT pattern, action FROM source_rules WHERE enabled=1").fetchall()
            for r in rows:
                rules[str(r["pattern"]).lower()] = str(r["action"]).lower()
        except Exception:
            pass
        return rules

    def judge(self, url: str | None, title: str = "", source_type: str = "web", created_at: str | None = None) -> SourceVerdict:
        u = url or ""
        domain = urlparse(u).netloc.lower().replace("www.", "") if u else "local/database"
        reliability = 0.50
        reason: list[str] = []
        rules = self._rules()
        for pattern, action in rules.items():
            if pattern and pattern in (domain + " " + u.lower() + " " + title.lower()):
                if action in {"block", "blacklist"}:
                    return SourceVerdict(u, domain, 0.0, 0.0, "blocked", f"blocked by rule: {pattern}")
                if action in {"trust", "whitelist", "boost"}:
                    reliability += 0.30
                    reason.append(f"trusted rule: {pattern}")
        if any(domain.endswith(d) or d in domain for d in OFFICIAL_DOMAINS):
            reliability += 0.25
            reason.append("official/well-known source")
        if any(b in domain for b in BAD_DOMAIN_HINTS):
            reliability -= 0.12
            reason.append("lower-trust domain type")
        if source_type in {"research_summary", "broad_research_summary"}:
            reliability -= 0.05
            reason.append("summary generated from other sources")
        if source_type in {"local", "conversation", "memory"}:
            reliability -= 0.08
            reason.append("local stored memory/source")
        freshness_score = self._freshness_from_date(created_at)
        label = "high" if reliability >= 0.72 else "medium" if reliability >= 0.42 else "low"
        return SourceVerdict(u, domain, max(0.0, min(1.0, reliability)), freshness_score, label, "; ".join(reason) or "default scoring")

    def _freshness_from_date(self, created_at: str | None) -> float:
        if not created_at:
            return 0.50
        # lightweight ISO-year estimate; good enough for scoring without dateutil.
        try:
            y = int(str(created_at)[:4])
            current = int(time.strftime("%Y"))
            age = max(0, current - y)
            return max(0.10, 1.0 - age * 0.18)
        except Exception:
            return 0.50


class EvidenceVault:
    def __init__(self, db: Any):
        self.db = db

    def store(self, *, source_url: str | None, title: str, claim: str, snippet: str, confidence: float = 0.5, freshness: str = "unknown", metadata: dict[str, Any] | None = None) -> int:
        now = utc_now()
        h = sha256_text(f"{source_url}|{title}|{claim}|{snippet[:300]}".lower())
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO evidence_vault(source_url,title,claim,snippet,confidence,freshness,created_at,metadata_json,hash)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(hash) DO UPDATE SET confidence=excluded.confidence, freshness=excluded.freshness, metadata_json=excluded.metadata_json
                """,
                (source_url, title, claim, snippet[:5000], float(confidence), freshness, now, json.dumps(metadata or {}, ensure_ascii=False), h),
            )
            row = conn.execute("SELECT id FROM evidence_vault WHERE hash=?", (h,)).fetchone()
            return int(row["id"])

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM evidence_vault ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]


class ContextBudgetManager:
    def __init__(self, max_chars: int = 18000):
        self.max_chars = max(3000, int(max_chars or 18000))

    def budget_for(self, classification: str, task_type: str = "chat") -> dict[str, int]:
        base = self.max_chars
        if classification == "fresh":
            return {"retrieval_limit": 4, "context_chars": min(base, 9000), "history_turns": 4}
        if task_type in {"code", "build_agent"}:
            return {"retrieval_limit": 3, "context_chars": min(base, 7000), "history_turns": 3}
        return {"retrieval_limit": 8, "context_chars": min(base, 14000), "history_turns": 6}

    def trim(self, text: str, max_chars: int | None = None) -> str:
        max_chars = max_chars or self.max_chars
        if len(text or "") <= max_chars:
            return text or ""
        head = max_chars // 2
        tail = max_chars - head - 80
        return (text or "")[:head].rstrip() + "\n\n[...context trimmed by Context Budget Manager...]\n\n" + (text or "")[-tail:].lstrip()


class ConversationQualityScanner:
    def scan(self, question: str, answer: str, *, freshness: FreshnessDecision | None = None, sources: list[str] | None = None, web_checked: bool = False) -> tuple[str, dict[str, Any]]:
        text = (answer or "").strip()
        report = {"ok": True, "warnings": [], "confidence": "medium", "web_checked": web_checked}
        if not text:
            report["ok"] = False
            report["warnings"].append("empty answer")
            return "Ik kreeg geen bruikbaar antwoord terug.", report
        if freshness and freshness.needs_web and not web_checked:
            report["confidence"] = "low"
            report["warnings"].append("fresh question without live web check")
            note = "\n\n⚠️ Niet live geverifieerd: dit kan verouderd zijn."
            if note not in text:
                text += note
        elif web_checked:
            report["confidence"] = "high" if sources else "medium"
        if re.search(r"\[tech:\s*chunks=", text, re.I):
            text = re.sub(r"\n?\s*\[tech:[^\]]+\]\s*", "", text, flags=re.I).strip()
            report["warnings"].append("removed technical metadata")
        # Keep source summary short and user-facing.
        if freshness:
            source_type = "live web-check" if web_checked else "database/LLM"
            if "Gebaseerd op:" not in text and (web_checked or freshness.label != "stable"):
                text += f"\n\nGebaseerd op: {source_type}. Zekerheid: {report['confidence']}."
        return text, report


class SkillMemory:
    def __init__(self, db: Any):
        self.db = db

    def remember(self, key: str, value: str, source: str = "manual", confidence: float = 0.8) -> None:
        now = utc_now()
        h = sha256_text(f"{key}|{value}".lower())
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO skill_memory(key,value,source,confidence,created_at,updated_at,hash)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(hash) DO UPDATE SET value=excluded.value, confidence=excluded.confidence, updated_at=excluded.updated_at
                """,
                (key, value, source, float(confidence), now, now, h),
            )

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM skill_memory ORDER BY updated_at DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    def context(self, limit: int = 12) -> str:
        rows = self.list(limit)
        if not rows:
            return ""
        return "\n".join(f"- {r['key']}: {r['value']}" for r in rows)


class WorkflowTemplates:
    TEMPLATES: dict[str, dict[str, Any]] = {
        "Leer website": {"type": "research", "mode": "website", "description": "Crawl een website, sla nuttige kennis op."},
        "Leer e-books": {"type": "research", "mode": "ebooks", "description": "Vind alleen echte document/e-book files en leer die."},
        "Fix source zip": {"type": "build_agent", "description": "Patch source veilig in workspace en exporteer clean zip."},
        "Scan error logs": {"type": "repair", "description": "Analyseer laatste errors en maak repair-plan."},
        "Benchmark model": {"type": "benchmark", "description": "Meet chat/code snelheid en kwaliteit."},
        "Clean build": {"type": "release", "description": "Maak export zonder database/.env/caches."},
        "Check Telegram": {"type": "self_test", "description": "Controleer token, config en runtime status."},
    }

    @classmethod
    def list_text(cls) -> str:
        return "\n".join(f"- {name}: {data['description']}" for name, data in cls.TEMPLATES.items())


class SelfTestLab:
    def __init__(self, settings: Any, db: Any, router: Any | None = None):
        self.settings = settings
        self.db = db
        self.router = router

    def run(self) -> str:
        lines = ["M0N4C0 Self-Test Lab", ""]
        # DB
        try:
            stats = self.db.stats()
            lines.append(f"✅ Database quick_check: {stats.get('quick_check')}")
            lines.append(f"   chunks={stats.get('knowledge_chunks')} sources={stats.get('knowledge_sources')} errors={stats.get('errors')}")
        except Exception as exc:
            lines.append(f"❌ Database: {type(exc).__name__}: {exc}")
        # settings/plugins
        try:
            plugin_path = Path(self.settings.root) / "data" / "plugin_settings.json"
            lines.append(f"✅ Plugin settings: {'found' if plugin_path.exists() else 'defaults'}")
        except Exception as exc:
            lines.append(f"⚠️ Plugin settings: {exc}")
        # LM Studio
        try:
            import requests
            r = requests.get(str(self.settings.lmstudio_base_url).rstrip('/') + "/models", timeout=2)
            lines.append(f"✅ LM Studio reachable: HTTP {r.status_code}")
        except Exception as exc:
            lines.append(f"⚠️ LM Studio not reachable: {type(exc).__name__}: {exc}")
        # freshness tables
        try:
            with self.db.connect() as conn:
                for t in ["evidence_vault", "source_rules", "skill_memory", "scheduled_jobs"]:
                    conn.execute(f"SELECT 1 FROM {t} LIMIT 1")
            lines.append("✅ Worldclass DB tables ready")
        except Exception as exc:
            lines.append(f"❌ Worldclass DB tables: {type(exc).__name__}: {exc}")
        # safe mode
        lines.append(f"✅ Safe Mode starter: {'found' if (Path(self.settings.root) / 'START_SAFE_MODE.bat').exists() else 'missing'}")
        return "\n".join(lines)


class ReleaseManager:
    PROTECTED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pyc"}
    PROTECTED_NAMES = {".env", "monaco_memory.db", "monaco_memory.db-wal", "monaco_memory.db-shm"}

    def __init__(self, root: Path):
        self.root = Path(root)

    def clean_zip(self, out_path: Path | None = None) -> Path:
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_path = out_path or (self.root.parent / f"M0N4C0_CLEAN_RELEASE_{ts}.zip")
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for p in self.root.rglob("*"):
                if not p.is_file():
                    continue
                rel = p.relative_to(self.root)
                parts = set(rel.parts)
                if any(part in {"__pycache__", ".git", ".venv", "venv", "build_agent_workspaces", "backups"} for part in parts):
                    continue
                if p.name in self.PROTECTED_NAMES or p.suffix.lower() in self.PROTECTED_SUFFIXES:
                    continue
                if p.name.endswith(".zip"):
                    continue
                z.write(p, str(Path(self.root.name) / rel))
        return out_path

    def changelog_entry(self, version: str, notes: str) -> Path:
        p = self.root / "RELEASE_HISTORY.md"
        entry = f"\n## {version} — {utc_now()}\n\n{notes.strip()}\n"
        old = p.read_text(encoding="utf-8") if p.exists() else "# M0N4C0 Release History\n"
        p.write_text(old.rstrip() + "\n" + entry, encoding="utf-8")
        return p


def detect_current_project(root: Path) -> str:
    root = Path(root)
    markers = ["main.py", "run_m0n4c0.py", "pyproject.toml", "requirements.txt"]
    hits = [m for m in markers if (root / m).exists()]
    return root.name + (" (" + ", ".join(hits) + ")" if hits else "")


def summarize_knowledge_timeline(db: Any, limit: int = 80) -> str:
    lines = ["Knowledge Timeline", ""]
    try:
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT substr(created_at,1,10) AS day, topic, COUNT(*) AS chunks
                FROM knowledge_chunks
                GROUP BY day, topic
                ORDER BY day DESC, chunks DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        if not rows:
            return "Knowledge Timeline\n\nNog geen kennis/chunks gevonden."
        for r in rows:
            lines.append(f"{r['day']} — {r['chunks']} chunks — {r['topic'] or 'zonder topic'}")
    except Exception as exc:
        lines.append(f"Timeline kon niet laden: {type(exc).__name__}: {exc}")
    return "\n".join(lines)


def source_rules_text(db: Any) -> str:
    try:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM source_rules ORDER BY action, pattern LIMIT 200").fetchall()
        if not rows:
            return "Geen source whitelist/blacklist regels ingesteld."
        return "\n".join(f"#{r['id']} {r['action'].upper()} {r['pattern']} | {r['notes'] or ''}" for r in rows)
    except Exception as exc:
        return f"Source rules konden niet laden: {type(exc).__name__}: {exc}"


def upsert_source_rule(db: Any, pattern: str, action: str, notes: str = "") -> int:
    pattern = (pattern or "").strip().lower()
    action = (action or "trust").strip().lower()
    if action not in {"trust", "boost", "block", "blacklist"}:
        action = "trust"
    now = utc_now()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO source_rules(pattern,action,notes,enabled,created_at,updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(pattern) DO UPDATE SET action=excluded.action, notes=excluded.notes, enabled=1, updated_at=excluded.updated_at
            """,
            (pattern, action, notes, 1, now, now),
        )
        row = conn.execute("SELECT id FROM source_rules WHERE pattern=?", (pattern,)).fetchone()
        return int(row["id"])


def delete_source_rule(db: Any, rule_id: int) -> bool:
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM source_rules WHERE id=?", (int(rule_id),))
        return cur.rowcount > 0


def schedule_job(db: Any, title: str, task_type: str, cadence: str, enabled: bool = True, metadata: dict[str, Any] | None = None) -> int:
    now = utc_now()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO scheduled_jobs(title,task_type,cadence,enabled,last_run_at,next_run_hint,created_at,updated_at,metadata_json)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (title, task_type, cadence, int(enabled), None, cadence, now, now, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def list_scheduled_jobs(db: Any, limit: int = 100) -> str:
    try:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM scheduled_jobs ORDER BY enabled DESC, updated_at DESC LIMIT ?", (int(limit),)).fetchall()
        if not rows:
            return "Geen geplande AI jobs."
        return "\n".join(f"#{r['id']} [{'ON' if r['enabled'] else 'OFF'}] {r['title']} | {r['task_type']} | {r['cadence']}" for r in rows)
    except Exception as exc:
        return f"Scheduler kon niet laden: {type(exc).__name__}: {exc}"


def project_memory_text(db: Any, project: str | None = None, limit: int = 100) -> str:
    try:
        with db.connect() as conn:
            if project:
                rows = conn.execute("SELECT * FROM project_memory WHERE project_key=? ORDER BY updated_at DESC LIMIT ?", (project, int(limit))).fetchall()
            else:
                rows = conn.execute("SELECT * FROM project_memory ORDER BY updated_at DESC LIMIT ?", (int(limit),)).fetchall()
        if not rows:
            return "Geen project memory gevonden."
        return "\n".join(f"#{r['id']} [{r['project_key']}] {r['key']}: {r['value']}" for r in rows)
    except Exception as exc:
        return f"Project memory kon niet laden: {type(exc).__name__}: {exc}"


def upsert_project_memory(db: Any, project_key: str, key: str, value: str) -> int:
    now = utc_now()
    h = sha256_text(f"{project_key}|{key}".lower())
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO project_memory(project_key,key,value,created_at,updated_at,hash)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(hash) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (project_key, key, value, now, now, h),
        )
        row = conn.execute("SELECT id FROM project_memory WHERE hash=?", (h,)).fetchone()
        return int(row["id"])
