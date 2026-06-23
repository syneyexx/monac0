from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from .utils import utc_now, sha256_text


SCHEMA_VERSION = 6


class MonacoDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA cache_size=-64000")
            conn.execute("PRAGMA mmap_size=268435456")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    user_key TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    username TEXT,
                    display_name TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    profile_json TEXT DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    user_key TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_chat_created ON conversations(chat_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_conversations_chat_role_id ON conversations(chat_id, role, id DESC);

                CREATE TABLE IF NOT EXISTS memory_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    confidence REAL DEFAULT 0.75,
                    source TEXT DEFAULT 'conversation',
                    user_key TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    hash TEXT UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_memory_subject ON memory_facts(subject);
                CREATE INDEX IF NOT EXISTS idx_memory_user_updated ON memory_facts(user_key, updated_at);

                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    topic TEXT,
                    status TEXT DEFAULT 'active',
                    reliability REAL DEFAULT 0.5,
                    metadata_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    hash TEXT UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_sources_topic ON knowledge_sources(topic);
                CREATE INDEX IF NOT EXISTS idx_sources_type ON knowledge_sources(source_type);

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER,
                    topic TEXT,
                    title TEXT,
                    url TEXT,
                    chunk_index INTEGER DEFAULT 0,
                    content TEXT NOT NULL,
                    summary TEXT,
                    keywords_json TEXT DEFAULT '[]',
                    quality_score REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    hash TEXT UNIQUE,
                    FOREIGN KEY(source_id) REFERENCES knowledge_sources(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_topic ON knowledge_chunks(topic);
                CREATE INDEX IF NOT EXISTS idx_chunks_source ON knowledge_chunks(source_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_topic_quality_id ON knowledge_chunks(topic, quality_score DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_chunks_created ON knowledge_chunks(created_at);

                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(
                    title, topic, content, summary, url, content='knowledge_chunks', content_rowid='id'
                );
                CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ai AFTER INSERT ON knowledge_chunks BEGIN
                    INSERT INTO knowledge_chunks_fts(rowid, title, topic, content, summary, url)
                    VALUES (new.id, new.title, new.topic, new.content, coalesce(new.summary,''), coalesce(new.url,''));
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ad AFTER DELETE ON knowledge_chunks BEGIN
                    INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts, rowid, title, topic, content, summary, url)
                    VALUES('delete', old.id, old.title, old.topic, old.content, coalesce(old.summary,''), coalesce(old.url,''));
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_chunks_au AFTER UPDATE ON knowledge_chunks BEGIN
                    INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts, rowid, title, topic, content, summary, url)
                    VALUES('delete', old.id, old.title, old.topic, old.content, coalesce(old.summary,''), coalesce(old.url,''));
                    INSERT INTO knowledge_chunks_fts(rowid, title, topic, content, summary, url)
                    VALUES (new.id, new.title, new.topic, new.content, coalesce(new.summary,''), coalesce(new.url,''));
                END;

                CREATE TABLE IF NOT EXISTS learning_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    rounds_requested INTEGER NOT NULL,
                    rounds_done INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learning_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    worker_id TEXT,
                    level TEXT DEFAULT 'INFO',
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}',
                    FOREIGN KEY(job_id) REFERENCES learning_jobs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_learning_events_job_created ON learning_events(job_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_learning_events_created ON learning_events(created_at);

                CREATE TABLE IF NOT EXISTS web_pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE,
                    title TEXT,
                    status_code INTEGER,
                    fetched_at TEXT NOT NULL,
                    text TEXT,
                    metadata_json TEXT DEFAULT '{}',
                    hash TEXT
                );

                CREATE TABLE IF NOT EXISTS website_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    root_url TEXT NOT NULL UNIQUE,
                    source_type TEXT DEFAULT 'unknown',
                    login_required INTEGER DEFAULT 0,
                    access_method TEXT DEFAULT 'public',
                    status TEXT DEFAULT 'active',
                    pages_seen INTEGER DEFAULT 0,
                    actions_json TEXT DEFAULT '[]',
                    metadata_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS website_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    website_id INTEGER,
                    action_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending_approval',
                    created_at TEXT NOT NULL,
                    executed_at TEXT,
                    result TEXT,
                    metadata_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS answer_cache (
                    key TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    context_hash TEXT,
                    created_at TEXT NOT NULL,
                    used_count INTEGER DEFAULT 0,
                    metadata_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_answer_cache_created ON answer_cache(created_at);

                CREATE TABLE IF NOT EXISTS bot_writes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    traceback TEXT,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS research_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    source_kind TEXT DEFAULT 'website',
                    enabled INTEGER DEFAULT 1,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_research_sources_enabled_kind ON research_sources(enabled, source_kind);

                CREATE TABLE IF NOT EXISTS idle_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL UNIQUE,
                    enabled INTEGER DEFAULT 1,
                    priority INTEGER DEFAULT 5,
                    rounds INTEGER DEFAULT 2,
                    mode TEXT DEFAULT 'topic',
                    source_urls_json TEXT DEFAULT '[]',
                    last_queued_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_idle_topics_enabled_priority ON idle_topics(enabled, priority DESC, updated_at);

                CREATE TABLE IF NOT EXISTS app_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT DEFAULT 'open',
                    progress INTEGER DEFAULT 0,
                    message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_app_tasks_status_type ON app_tasks(status, task_type, updated_at DESC);

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evidence_vault (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_url TEXT,
                    title TEXT,
                    claim TEXT,
                    snippet TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    freshness TEXT DEFAULT 'unknown',
                    created_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}',
                    hash TEXT UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_created ON evidence_vault(created_at);
                CREATE INDEX IF NOT EXISTS idx_evidence_confidence ON evidence_vault(confidence DESC);

                CREATE TABLE IF NOT EXISTS source_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern TEXT NOT NULL UNIQUE,
                    action TEXT NOT NULL DEFAULT 'trust',
                    enabled INTEGER DEFAULT 1,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_source_rules_action ON source_rules(action, enabled);

                CREATE TABLE IF NOT EXISTS skill_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT DEFAULT 'manual',
                    confidence REAL DEFAULT 0.8,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    hash TEXT UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_skill_memory_key ON skill_memory(key);

                CREATE TABLE IF NOT EXISTS project_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_key TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    hash TEXT UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_project_memory_project ON project_memory(project_key);

                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    cadence TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    last_run_at TEXT,
                    next_run_hint TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_enabled ON scheduled_jobs(enabled, task_type);

                CREATE TABLE IF NOT EXISTS release_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version TEXT NOT NULL,
                    notes TEXT,
                    artifact_path TEXT,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS quality_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT,
                    question TEXT,
                    answer_preview TEXT,
                    confidence TEXT,
                    warnings_json TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_quality_reports_created ON quality_reports(created_at);
                                CREATE TABLE IF NOT EXISTS research_document_registry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE,
                    canonical_url TEXT,
                    content_hash TEXT,
                    text_hash TEXT,
                    title TEXT,
                    topic TEXT,
                    source_id INTEGER,
                    bytes_len INTEGER DEFAULT 0,
                    content_type TEXT,
                    status TEXT DEFAULT 'processed',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_processed_at TEXT,
                    metadata_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_research_doc_hash ON research_document_registry(content_hash);
                CREATE INDEX IF NOT EXISTS idx_research_doc_text_hash ON research_document_registry(text_hash);
                CREATE INDEX IF NOT EXISTS idx_research_doc_status ON research_document_registry(status, last_seen_at);

                CREATE TABLE IF NOT EXISTS research_job_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    item_type TEXT DEFAULT 'page',
                    depth INTEGER DEFAULT 0,
                    priority INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    source_id INTEGER,
                    content_hash TEXT,
                    text_hash TEXT,
                    bytes_len INTEGER DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}',
                    UNIQUE(job_id, url),
                    FOREIGN KEY(job_id) REFERENCES learning_jobs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_research_job_items_next ON research_job_items(job_id, status, priority DESC, id);
                CREATE INDEX IF NOT EXISTS idx_research_job_items_hash ON research_job_items(content_hash);

"""
            )
            self._migrate_learning_jobs(conn)
            self._migrate_worldclass(conn)
            self._migrate_research_resume(conn)
            self.set_meta("schema_version", str(SCHEMA_VERSION), conn=conn)


    def _migrate_worldclass(self, conn: sqlite3.Connection) -> None:
        """Non-destructive upgrades for freshness/source metadata tables."""
        def cols(table: str) -> set[str]:
            try:
                return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            except Exception:
                return set()

        source_cols = cols("knowledge_sources")
        source_additions = {
            "last_checked_at": "TEXT",
            "freshness_score": "REAL DEFAULT 0.5",
            "confidence": "REAL DEFAULT 0.5",
        }
        for name, spec in source_additions.items():
            if name not in source_cols:
                conn.execute(f"ALTER TABLE knowledge_sources ADD COLUMN {name} {spec}")

        chunk_cols = cols("knowledge_chunks")
        chunk_additions = {
            "last_checked_at": "TEXT",
            "freshness_score": "REAL DEFAULT 0.5",
            "confidence": "REAL DEFAULT 0.5",
            "source_type": "TEXT DEFAULT 'database'",
        }
        for name, spec in chunk_additions.items():
            if name not in chunk_cols:
                conn.execute(f"ALTER TABLE knowledge_chunks ADD COLUMN {name} {spec}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_freshness ON knowledge_chunks(freshness_score DESC, last_checked_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_freshness ON knowledge_sources(freshness_score DESC, last_checked_at DESC)")

    def _migrate_research_resume(self, conn: sqlite3.Connection) -> None:
        """Non-destructive tables for duplicate document detection and resumable research jobs."""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_document_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                canonical_url TEXT,
                content_hash TEXT,
                text_hash TEXT,
                title TEXT,
                topic TEXT,
                source_id INTEGER,
                bytes_len INTEGER DEFAULT 0,
                content_type TEXT,
                status TEXT DEFAULT 'processed',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_processed_at TEXT,
                metadata_json TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_research_doc_hash ON research_document_registry(content_hash);
            CREATE INDEX IF NOT EXISTS idx_research_doc_text_hash ON research_document_registry(text_hash);
            CREATE INDEX IF NOT EXISTS idx_research_doc_status ON research_document_registry(status, last_seen_at);

            CREATE TABLE IF NOT EXISTS research_job_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                item_type TEXT DEFAULT 'page',
                depth INTEGER DEFAULT 0,
                priority INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                source_id INTEGER,
                content_hash TEXT,
                text_hash TEXT,
                bytes_len INTEGER DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT DEFAULT '{}',
                UNIQUE(job_id, url),
                FOREIGN KEY(job_id) REFERENCES learning_jobs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_research_job_items_next ON research_job_items(job_id, status, priority DESC, id);
            CREATE INDEX IF NOT EXISTS idx_research_job_items_hash ON research_job_items(content_hash);
            """
        )

    def _migrate_learning_jobs(self, conn: sqlite3.Connection) -> None:
        """Upgrade old SQLite DBs without losing queued/history jobs."""
        row_cols = conn.execute("PRAGMA table_info(learning_jobs)").fetchall()
        cols = {str(row[1]) for row in row_cols}
        additions = {
            "mode": "TEXT DEFAULT 'topic'",
            "priority": "INTEGER DEFAULT 5",
            "agent": "TEXT DEFAULT 'researcher'",
            "chat_id": "TEXT",
            "user_key": "TEXT",
            "source": "TEXT DEFAULT 'user'",
            "start_year": "INTEGER",
            "end_year": "INTEGER",
            "worker_id": "TEXT",
            "progress_json": "TEXT DEFAULT '{}'",
            "error": "TEXT",
            "cancel_requested": "INTEGER DEFAULT 0",
            "started_at": "TEXT",
            "finished_at": "TEXT",
            "source_urls_json": "TEXT DEFAULT '[]'",
            "worker_profile": "TEXT DEFAULT 'default'",
            "max_depth": "INTEGER DEFAULT 1",
            "max_pages": "INTEGER DEFAULT 20",
            "max_files": "INTEGER DEFAULT 20",
            "dedupe_key": "TEXT",
        }
        for name, ddl in additions.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE learning_jobs ADD COLUMN {name} {ddl}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_learning_jobs_status_priority ON learning_jobs(status, priority DESC, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_learning_jobs_updated ON learning_jobs(updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_learning_jobs_status_updated ON learning_jobs(status, updated_at DESC)")

    def set_meta(self, key: str, value: str, conn: sqlite3.Connection | None = None) -> None:
        now = utc_now()
        if conn is None:
            with self.connect() as c:
                c.execute("INSERT OR REPLACE INTO meta(key,value,updated_at) VALUES(?,?,?)", (key, value, now))
        else:
            conn.execute("INSERT OR REPLACE INTO meta(key,value,updated_at) VALUES(?,?,?)", (key, value, now))

    def enqueue_learning_job(
        self,
        topic: str,
        rounds: int,
        mode: str = "topic",
        priority: int = 5,
        agent: str = "researcher",
        chat_id: str | None = None,
        user_key: str | None = None,
        source: str = "user",
        start_year: int | None = None,
        end_year: int | None = None,
        notes: str | None = None,
        metadata: dict[str, Any] | None = None,
        source_urls: list[str] | None = None,
        worker_profile: str = "default",
        max_depth: int = 1,
        max_pages: int = 20,
        max_files: int = 20,
    ) -> int:
        now = utc_now()
        allowed_modes = {"topic", "broad", "website", "ebooks", "documents", "news", "competitor", "deep", "wikipedia", "mission"}
        mode = mode if mode in allowed_modes else "topic"
        priority = max(0, min(10, int(priority or 5)))
        meta_notes = notes
        if metadata:
            meta_notes = json.dumps(metadata, ensure_ascii=False)
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO learning_jobs(
                    topic, rounds_requested, rounds_done, status, notes, created_at, updated_at,
                    mode, priority, agent, chat_id, user_key, source, start_year, end_year,
                    progress_json, cancel_requested, source_urls_json, worker_profile, max_depth, max_pages, max_files, dedupe_key
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    topic.strip(), int(rounds), 0, "queued", meta_notes, now, now,
                    mode, priority, agent, chat_id, user_key, source, start_year, end_year,
                    json.dumps({"phase": "queued", "percent": 0}, ensure_ascii=False), 0,
                    json.dumps(source_urls or [], ensure_ascii=False), worker_profile, int(max_depth), int(max_pages), int(max_files),
                    sha256_text(f"{mode}|{topic.strip().lower()}|{json.dumps(source_urls or [], sort_keys=True)}"),
                ),
            )
            job_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO learning_events(job_id,worker_id,level,message,created_at,metadata_json) VALUES(?,?,?,?,?,?)",
                (job_id, None, "OK", f"Job queued: {topic}", now, json.dumps({"mode": mode, "rounds": rounds, "source_urls": source_urls or [], "worker_profile": worker_profile}, ensure_ascii=False)),
            )
            return job_id

    def claim_next_learning_job(self, worker_id: str) -> sqlite3.Row | None:
        now = utc_now()
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM learning_jobs
                WHERE status IN ('queued','pending') AND coalesce(cancel_requested,0)=0
                ORDER BY priority DESC, id ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return None
            conn.execute(
                """
                UPDATE learning_jobs
                SET status='running', worker_id=?, started_at=coalesce(started_at,?), updated_at=?,
                    progress_json=?
                WHERE id=?
                """,
                (worker_id, now, now, json.dumps({"phase": "claimed", "percent": 1}, ensure_ascii=False), int(row["id"])),
            )
            conn.execute(
                "INSERT INTO learning_events(job_id,worker_id,level,message,created_at,metadata_json) VALUES(?,?,?,?,?,?)",
                (int(row["id"]), worker_id, "STEP", f"Worker claimed job #{int(row['id'])}", now, "{}"),
            )
            conn.execute("COMMIT")
            return conn.execute("SELECT * FROM learning_jobs WHERE id=?", (int(row["id"]),)).fetchone()
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def update_learning_job(
        self,
        job_id: int,
        *,
        status: str | None = None,
        rounds_done: int | None = None,
        notes: str | None = None,
        progress: dict[str, Any] | None = None,
        error: str | None = None,
        finished: bool = False,
    ) -> None:
        now = utc_now()
        fields = ["updated_at=?"]
        values: list[Any] = [now]
        if status is not None:
            fields.append("status=?")
            values.append(status)
        if rounds_done is not None:
            fields.append("rounds_done=?")
            values.append(int(rounds_done))
        if notes is not None:
            fields.append("notes=?")
            values.append(notes)
        if progress is not None:
            fields.append("progress_json=?")
            values.append(json.dumps(progress, ensure_ascii=False))
        if error is not None:
            fields.append("error=?")
            values.append(error)
        if finished:
            fields.append("finished_at=?")
            values.append(now)
        values.append(int(job_id))
        with self.connect() as conn:
            conn.execute(f"UPDATE learning_jobs SET {', '.join(fields)} WHERE id=?", values)

    def log_learning_event(self, job_id: int | None, worker_id: str | None, level: str, message: str, metadata: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO learning_events(job_id,worker_id,level,message,created_at,metadata_json) VALUES(?,?,?,?,?,?)",
                (job_id, worker_id, level.upper(), message, utc_now(), json.dumps(metadata or {}, ensure_ascii=False)),
            )

    def list_learning_jobs(self, limit: int = 30) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM learning_jobs ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()

    def get_learning_job(self, job_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM learning_jobs WHERE id=?", (int(job_id),)).fetchone()

    def list_learning_events(self, job_id: int | None = None, limit: int = 80) -> list[sqlite3.Row]:
        with self.connect() as conn:
            if job_id is None:
                return conn.execute(
                    "SELECT * FROM learning_events ORDER BY id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM learning_events WHERE job_id=? ORDER BY id DESC LIMIT ?",
                (int(job_id), int(limit)),
            ).fetchall()

    def request_cancel_learning_job(self, job_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT id,status FROM learning_jobs WHERE id=?", (int(job_id),)).fetchone()
            if not row:
                return False
            now = utc_now()
            if str(row["status"]) in {"done", "failed", "cancelled"}:
                return True
            conn.execute(
                "UPDATE learning_jobs SET cancel_requested=1,status=CASE WHEN status IN ('queued','pending') THEN 'cancelled' ELSE status END, updated_at=? WHERE id=?",
                (now, int(job_id)),
            )
            conn.execute(
                "INSERT INTO learning_events(job_id,worker_id,level,message,created_at,metadata_json) VALUES(?,?,?,?,?,?)",
                (int(job_id), None, "WARN", "Cancel requested", now, "{}"),
            )
            return True

    def upsert_research_source(self, name: str, url: str, source_kind: str = "website", enabled: bool = True, notes: str | None = None, metadata: dict[str, Any] | None = None) -> int:
        now = utc_now()
        url = (url or "").strip()
        name = (name or url).strip()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO research_sources(name,url,source_kind,enabled,notes,created_at,updated_at,metadata_json)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET name=excluded.name, source_kind=excluded.source_kind, enabled=excluded.enabled, notes=excluded.notes, updated_at=excluded.updated_at, metadata_json=excluded.metadata_json
                """,
                (name, url, source_kind, int(bool(enabled)), notes, now, now, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            row = conn.execute("SELECT id FROM research_sources WHERE url=?", (url,)).fetchone()
            return int(row["id"])

    def list_research_sources(self, enabled_only: bool = False, limit: int = 200) -> list[sqlite3.Row]:
        with self.connect() as conn:
            if enabled_only:
                return conn.execute("SELECT * FROM research_sources WHERE enabled=1 ORDER BY updated_at DESC LIMIT ?", (int(limit),)).fetchall()
            return conn.execute("SELECT * FROM research_sources ORDER BY updated_at DESC LIMIT ?", (int(limit),)).fetchall()

    def delete_research_source(self, source_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM research_sources WHERE id=?", (int(source_id),))
            return cur.rowcount > 0

    def requeue_interrupted_learning_jobs(self) -> int:
        """Requeue jobs that were running when the app/worker was stopped.

        Called once on worker startup. This is intentionally conservative and
        only touches unfinished running jobs that were not cancelled. The
        research_job_items table keeps per-URL checkpoints, so the next worker
        continues instead of starting from zero.
        """
        now = utc_now()
        with self.connect() as conn:
            interrupted_ids = [int(r["id"]) for r in conn.execute(
                "SELECT id FROM learning_jobs WHERE status='running' AND coalesce(cancel_requested,0)=0 AND finished_at IS NULL"
            ).fetchall()]
            if interrupted_ids:
                placeholders = ",".join("?" for _ in interrupted_ids)
                conn.execute(
                    f"UPDATE research_job_items SET status='pending', updated_at=? WHERE status='processing' AND job_id IN ({placeholders})",
                    [now, *interrupted_ids],
                )
            cur = conn.execute(
                """
                UPDATE learning_jobs
                SET status='queued', worker_id=NULL, updated_at=?,
                    progress_json=?
                WHERE status='running' AND coalesce(cancel_requested,0)=0 AND finished_at IS NULL
                """,
                (now, json.dumps({"phase": "resumed_after_restart", "percent": 1}, ensure_ascii=False)),
            )
            count = int(cur.rowcount or 0)
            if count:
                conn.execute(
                    "INSERT INTO learning_events(job_id,worker_id,level,message,created_at,metadata_json) SELECT id,NULL,'WARN','Job requeued after interrupted worker/app restart',?, '{}' FROM learning_jobs WHERE status='queued' AND updated_at=?",
                    (now, now),
                )
            return count

    def register_research_item(self, job_id: int, url: str, item_type: str = "page", depth: int = 0, priority: int = 0, metadata: dict[str, Any] | None = None) -> int:
        now = utc_now()
        url = (url or "").strip()
        if not url:
            return 0
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO research_job_items(job_id,url,item_type,depth,priority,status,created_at,updated_at,metadata_json)
                VALUES(?,?,?,?,?,'pending',?,?,?)
                ON CONFLICT(job_id,url) DO UPDATE SET
                    priority=max(priority, excluded.priority),
                    depth=min(depth, excluded.depth),
                    updated_at=excluded.updated_at,
                    metadata_json=CASE WHEN research_job_items.status IN ('done','skipped','failed') THEN research_job_items.metadata_json ELSE excluded.metadata_json END
                """,
                (int(job_id), url, item_type, int(depth), int(priority), now, now, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            row = conn.execute("SELECT id FROM research_job_items WHERE job_id=? AND url=?", (int(job_id), url)).fetchone()
            return int(row["id"] if row else 0)

    def next_research_item(self, job_id: int) -> sqlite3.Row | None:
        now = utc_now()
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM research_job_items
                WHERE job_id=? AND status IN ('pending','queued')
                ORDER BY priority DESC, item_type='document' DESC, depth ASC, id ASC
                LIMIT 1
                """,
                (int(job_id),),
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return None
            conn.execute(
                "UPDATE research_job_items SET status='processing', attempts=attempts+1, updated_at=? WHERE id=?",
                (now, int(row["id"])),
            )
            conn.execute("COMMIT")
            return conn.execute("SELECT * FROM research_job_items WHERE id=?", (int(row["id"]),)).fetchone()
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def update_research_item(self, item_id: int, status: str, *, source_id: int | None = None, content_hash: str | None = None, text_hash: str | None = None, bytes_len: int | None = None, error: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        fields = ["status=?", "updated_at=?"]
        values: list[Any] = [status, utc_now()]
        for name, value in (("source_id", source_id), ("content_hash", content_hash), ("text_hash", text_hash), ("bytes_len", bytes_len), ("error", error)):
            if value is not None:
                fields.append(f"{name}=?")
                values.append(value)
        if metadata is not None:
            fields.append("metadata_json=?")
            values.append(json.dumps(metadata, ensure_ascii=False))
        values.append(int(item_id))
        with self.connect() as conn:
            conn.execute(f"UPDATE research_job_items SET {', '.join(fields)} WHERE id=?", values)

    def count_research_items(self, job_id: int) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS c FROM research_job_items WHERE job_id=? GROUP BY status", (int(job_id),)).fetchall()
        return {str(r["status"]): int(r["c"]) for r in rows}

    def get_document_registry_by_url(self, url: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM research_document_registry WHERE url=?", ((url or '').strip(),)).fetchone()

    def get_document_registry_by_hash(self, content_hash: str | None = None, text_hash: str | None = None) -> sqlite3.Row | None:
        with self.connect() as conn:
            if content_hash:
                row = conn.execute("SELECT * FROM research_document_registry WHERE content_hash=? AND status='processed' LIMIT 1", (content_hash,)).fetchone()
                if row:
                    return row
            if text_hash:
                return conn.execute("SELECT * FROM research_document_registry WHERE text_hash=? AND status='processed' LIMIT 1", (text_hash,)).fetchone()
        return None

    def mark_document_processed(self, url: str, *, title: str, topic: str, source_id: int, content_hash: str | None, text_hash: str | None, bytes_len: int = 0, content_type: str = "", metadata: dict[str, Any] | None = None) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO research_document_registry(url,canonical_url,content_hash,text_hash,title,topic,source_id,bytes_len,content_type,status,first_seen_at,last_seen_at,last_processed_at,metadata_json)
                VALUES(?,?,?,?,?,?,?,?,?,'processed',?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET
                    content_hash=excluded.content_hash, text_hash=excluded.text_hash, title=excluded.title, topic=excluded.topic, source_id=excluded.source_id, bytes_len=excluded.bytes_len, content_type=excluded.content_type, status='processed', last_seen_at=excluded.last_seen_at, last_processed_at=excluded.last_processed_at, metadata_json=excluded.metadata_json
                """,
                (url.strip(), url.strip(), content_hash, text_hash, title, topic, int(source_id), int(bytes_len or 0), content_type, now, now, now, json.dumps(metadata or {}, ensure_ascii=False)),
            )

    def backup_database(self, suffix: str = "backup") -> Path:
        ts = utc_now().replace(':', '-').replace('.', '-')
        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        out = backup_dir / f"{self.db_path.stem}_{suffix}_{ts}.db"
        src = sqlite3.connect(self.db_path)
        try:
            dst = sqlite3.connect(out)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return out

    def wipe_brain_data(self, *, make_backup: bool = True) -> dict[str, Any]:
        """Clear learned/private brain data without dropping schema.

        This intentionally keeps app_settings/meta and table structure. It removes
        memory, knowledge, research history, idle topics/sources, users and cached
        answers so the bot starts with an empty brain.
        """
        backup = str(self.backup_database("before_empty_brain")) if make_backup else None
        tables = [
            "knowledge_chunks", "knowledge_sources", "memory_facts", "conversations",
            "users", "web_pages", "website_actions", "website_profiles",
            "answer_cache", "bot_writes", "learning_events", "learning_jobs",
            "research_sources", "idle_topics", "app_tasks", "errors",
            "evidence_vault", "skill_memory", "project_memory", "quality_reports",
        ]
        counts: dict[str, int] = {}
        with self.connect() as conn:
            for table in tables:
                try:
                    row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
                    counts[table] = int(row["c"] if row else 0)
                    conn.execute(f"DELETE FROM {table}")
                except sqlite3.OperationalError:
                    counts[table] = 0
            try:
                conn.execute("INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts) VALUES('rebuild')")
            except Exception:
                pass
            conn.execute("PRAGMA optimize")
        return {"backup": backup, "deleted_counts": counts}


    def add_quality_report(self, platform: str, question: str, answer_preview: str, confidence: str, warnings: list[str] | None = None, metadata: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO quality_reports(platform,question,answer_preview,confidence,warnings_json,created_at,metadata_json) VALUES(?,?,?,?,?,?,?)",
                (platform, question[:2000], answer_preview[:2000], confidence, json.dumps(warnings or [], ensure_ascii=False), utc_now(), json.dumps(metadata or {}, ensure_ascii=False)),
            )

    def list_quality_reports(self, limit: int = 80) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM quality_reports ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()

    def add_release_history(self, version: str, notes: str, artifact_path: str | None = None, metadata: dict[str, Any] | None = None) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO release_history(version,notes,artifact_path,created_at,metadata_json) VALUES(?,?,?,?,?)",
                (version, notes, artifact_path, utc_now(), json.dumps(metadata or {}, ensure_ascii=False)),
            )
            return int(cur.lastrowid)

    def list_release_history(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM release_history ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()

    def upsert_idle_topic(self, topic: str, enabled: bool = True, priority: int = 5, rounds: int = 2, mode: str = "topic", source_urls: list[str] | None = None, metadata: dict[str, Any] | None = None) -> int:
        now = utc_now()
        topic = (topic or "").strip()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO idle_topics(topic,enabled,priority,rounds,mode,source_urls_json,created_at,updated_at,metadata_json)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(topic) DO UPDATE SET enabled=excluded.enabled, priority=excluded.priority, rounds=excluded.rounds, mode=excluded.mode, source_urls_json=excluded.source_urls_json, updated_at=excluded.updated_at, metadata_json=excluded.metadata_json
                """,
                (topic, int(bool(enabled)), int(priority), int(rounds), mode, json.dumps(source_urls or [], ensure_ascii=False), now, now, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            row = conn.execute("SELECT id FROM idle_topics WHERE topic=?", (topic,)).fetchone()
            return int(row["id"])

    def list_idle_topics(self, enabled_only: bool = False, limit: int = 200) -> list[sqlite3.Row]:
        with self.connect() as conn:
            if enabled_only:
                return conn.execute("SELECT * FROM idle_topics WHERE enabled=1 ORDER BY priority DESC, updated_at ASC LIMIT ?", (int(limit),)).fetchall()
            return conn.execute("SELECT * FROM idle_topics ORDER BY enabled DESC, priority DESC, updated_at DESC LIMIT ?", (int(limit),)).fetchall()

    def mark_idle_topic_queued(self, topic_id: int) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute("UPDATE idle_topics SET last_queued_at=?, updated_at=? WHERE id=?", (now, now, int(topic_id)))

    def get_app_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value_json FROM app_settings WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(str(row["value_json"]))
        except Exception:
            return default

    def set_app_setting(self, key: str, value: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_settings(key,value_json,updated_at) VALUES(?,?,?)",
                (key, json.dumps(value, ensure_ascii=False), utc_now()),
            )

    def create_app_task(self, task_type: str, title: str, status: str = "open", progress: int = 0, message: str | None = None, metadata: dict[str, Any] | None = None) -> int:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO app_tasks(task_type,title,status,progress,message,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?)",
                (task_type, title, status, int(progress), message, now, now, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            return int(cur.lastrowid)

    def list_app_tasks(self, limit: int = 80) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM app_tasks ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()

    def last_activity_at(self) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT max(ts) AS ts FROM (
                    SELECT max(created_at) AS ts FROM conversations
                    UNION ALL SELECT max(updated_at) AS ts FROM learning_jobs WHERE status IN ('queued','running','pending')
                    UNION ALL SELECT max(created_at) AS ts FROM learning_events
                )
                """
            ).fetchone()
            return str(row["ts"]) if row and row["ts"] else None

    def upsert_user(self, platform: str, user_key: str, username: str | None = None, display_name: str | None = None) -> None:
        now = utc_now()
        with self.connect() as conn:
            existing = conn.execute("SELECT user_key FROM users WHERE user_key=?", (user_key,)).fetchone()
            if existing:
                conn.execute("UPDATE users SET username=?, display_name=?, last_seen=? WHERE user_key=?", (username, display_name, now, user_key))
            else:
                conn.execute(
                    "INSERT INTO users(user_key,platform,username,display_name,first_seen,last_seen) VALUES(?,?,?,?,?,?)",
                    (user_key, platform, username, display_name, now, now),
                )

    def add_conversation(self, platform: str, chat_id: str, user_key: str | None, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO conversations(platform,chat_id,user_key,role,content,created_at,metadata_json) VALUES(?,?,?,?,?,?,?)",
                (platform, chat_id, user_key, role, content, utc_now(), json.dumps(metadata or {}, ensure_ascii=False)),
            )
            conn.execute(
                "INSERT INTO bot_writes(kind,content,created_at,metadata_json) VALUES(?,?,?,?)",
                (f"conversation_{role}", content, utc_now(), json.dumps({"platform": platform, "chat_id": chat_id}, ensure_ascii=False)),
            )

    def recent_conversation(self, chat_id: str, limit: int = 12) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM conversations WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        return list(reversed(rows))

    def add_memory_fact(self, subject: str, predicate: str, obj: str, user_key: str | None = None, source: str = "conversation", confidence: float = 0.75) -> None:
        h = sha256_text(f"{subject}|{predicate}|{obj}|{user_key or ''}".lower())
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_facts(subject,predicate,object,confidence,source,user_key,created_at,updated_at,hash)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(hash) DO UPDATE SET confidence=max(confidence, excluded.confidence), updated_at=excluded.updated_at
                """,
                (subject, predicate, obj, confidence, source, user_key, now, now, h),
            )

    def search_memory(self, query: str, limit: int = 12) -> list[sqlite3.Row]:
        like = f"%{query}%"
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM memory_facts
                WHERE subject LIKE ? OR predicate LIKE ? OR object LIKE ?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()

    def add_source(self, source_type: str, title: str, url: str | None, topic: str | None, metadata: dict[str, Any] | None = None, reliability: float = 0.5, confidence: float | None = None, freshness_score: float | None = None, last_checked_at: str | None = None) -> int:
        h = sha256_text(f"{source_type}|{title}|{url or ''}|{topic or ''}".lower())
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_sources(source_type,title,url,topic,reliability,metadata_json,created_at,updated_at,hash,confidence,freshness_score,last_checked_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(hash) DO UPDATE SET updated_at=excluded.updated_at, metadata_json=excluded.metadata_json, confidence=excluded.confidence, freshness_score=excluded.freshness_score, last_checked_at=excluded.last_checked_at
                """,
                (source_type, title, url, topic, reliability, json.dumps(metadata or {}, ensure_ascii=False), now, now, h, float(confidence if confidence is not None else reliability), float(freshness_score if freshness_score is not None else 0.5), last_checked_at or now),
            )
            row = conn.execute("SELECT id FROM knowledge_sources WHERE hash=?", (h,)).fetchone()
            return int(row["id"])

    def add_chunk(self, source_id: int | None, topic: str | None, title: str | None, url: str | None, chunk_index: int, content: str, summary: str | None = None, keywords: list[str] | None = None, quality_score: float = 0.5, confidence: float | None = None, freshness_score: float | None = None, source_type: str = "database", last_checked_at: str | None = None) -> bool:
        h = sha256_text(f"{source_id}|{chunk_index}|{content[:500]}".lower())
        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO knowledge_chunks(source_id,topic,title,url,chunk_index,content,summary,keywords_json,quality_score,created_at,hash,confidence,freshness_score,source_type,last_checked_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (source_id, topic, title, url, chunk_index, content, summary, json.dumps(keywords or [], ensure_ascii=False), quality_score, utc_now(), h, float(confidence if confidence is not None else quality_score), float(freshness_score if freshness_score is not None else 0.5), source_type, last_checked_at or utc_now()),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def fts_search(self, query: str, limit: int = 8) -> list[sqlite3.Row]:
        safe_query = " ".join([token.replace('"', '') for token in query.split()[:12]])
        if not safe_query:
            return []
        with self.connect() as conn:
            try:
                return conn.execute(
                    """
                    SELECT kc.*, bm25(knowledge_chunks_fts) AS score
                    FROM knowledge_chunks_fts
                    JOIN knowledge_chunks kc ON kc.id = knowledge_chunks_fts.rowid
                    WHERE knowledge_chunks_fts MATCH ?
                    ORDER BY score LIMIT ?
                    """,
                    (safe_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                like = f"%{query}%"
                return conn.execute(
                    "SELECT * FROM knowledge_chunks WHERE content LIKE ? OR title LIKE ? OR topic LIKE ? LIMIT ?",
                    (like, like, like, limit),
                ).fetchall()

    def stats(self) -> dict[str, int | str]:
        with self.connect() as conn:
            tables = [
                "users", "conversations", "memory_facts", "knowledge_sources", "knowledge_chunks",
                "learning_jobs", "learning_events", "web_pages", "website_profiles", "website_actions", "answer_cache", "bot_writes", "errors",
                "evidence_vault", "source_rules", "skill_memory", "project_memory", "scheduled_jobs", "quality_reports"
            ]
            out: dict[str, int | str] = {}
            for table in tables:
                out[table] = int(conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"])
            out["quick_check"] = conn.execute("PRAGMA quick_check").fetchone()[0]
            return out

    def cache_get(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT answer FROM answer_cache WHERE key=?", (key,)).fetchone()
            if row:
                conn.execute("UPDATE answer_cache SET used_count=used_count+1 WHERE key=?", (key,))
                return str(row["answer"])
            return None

    def cache_set(self, key: str, question: str, answer: str, context_hash: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO answer_cache(key,question,answer,context_hash,created_at,metadata_json) VALUES(?,?,?,?,?,?)",
                (key, question, answer, context_hash, utc_now(), json.dumps(metadata or {}, ensure_ascii=False)),
            )

    def log_error(self, error_type: str, message: str, traceback: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO errors(error_type,message,traceback,created_at,metadata_json) VALUES(?,?,?,?,?)",
                (error_type, message, traceback, utc_now(), json.dumps(metadata or {}, ensure_ascii=False)),
            )
