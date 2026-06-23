-- M0N4C0 WORLDCLASS NEXT UPGRADES MIGRATION
-- Safe/non-destructive. Run in Database Manager SQL console if you want manual migration.
-- The app also runs equivalent migration automatically on startup.

PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;
PRAGMA cache_size=-64000;
PRAGMA mmap_size=268435456;

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

-- Optional ALTER statements. SQLite has no IF NOT EXISTS for ADD COLUMN on older versions.
-- If a column already exists, ignore the duplicate-column error and continue.
ALTER TABLE knowledge_sources ADD COLUMN last_checked_at TEXT;
ALTER TABLE knowledge_sources ADD COLUMN freshness_score REAL DEFAULT 0.5;
ALTER TABLE knowledge_sources ADD COLUMN confidence REAL DEFAULT 0.5;
ALTER TABLE knowledge_chunks ADD COLUMN last_checked_at TEXT;
ALTER TABLE knowledge_chunks ADD COLUMN freshness_score REAL DEFAULT 0.5;
ALTER TABLE knowledge_chunks ADD COLUMN confidence REAL DEFAULT 0.5;
ALTER TABLE knowledge_chunks ADD COLUMN source_type TEXT DEFAULT 'database';

CREATE INDEX IF NOT EXISTS idx_chunks_freshness ON knowledge_chunks(freshness_score DESC, last_checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_sources_freshness ON knowledge_sources(freshness_score DESC, last_checked_at DESC);

PRAGMA optimize;
