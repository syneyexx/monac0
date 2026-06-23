-- M0N4C0 / SDEN AI Worldclass V3 migration
-- Safe migration: only adds columns/tables/indexes. It does NOT delete data.
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;
PRAGMA cache_size=-64000;
PRAGMA mmap_size=268435456;

-- Learning job upgrades. SQLite cannot use IF NOT EXISTS for ADD COLUMN on older versions.
-- If a column already exists, ignore the duplicate-column error and continue.
ALTER TABLE learning_jobs ADD COLUMN source_urls_json TEXT DEFAULT '[]';
ALTER TABLE learning_jobs ADD COLUMN worker_profile TEXT DEFAULT 'default';
ALTER TABLE learning_jobs ADD COLUMN max_depth INTEGER DEFAULT 1;
ALTER TABLE learning_jobs ADD COLUMN max_pages INTEGER DEFAULT 20;
ALTER TABLE learning_jobs ADD COLUMN max_files INTEGER DEFAULT 20;
ALTER TABLE learning_jobs ADD COLUMN dedupe_key TEXT;

CREATE INDEX IF NOT EXISTS idx_learning_jobs_status_priority ON learning_jobs(status, priority DESC, id);
CREATE INDEX IF NOT EXISTS idx_learning_jobs_updated ON learning_jobs(updated_at);
CREATE INDEX IF NOT EXISTS idx_learning_jobs_status_updated ON learning_jobs(status, updated_at DESC);

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

PRAGMA optimize;
