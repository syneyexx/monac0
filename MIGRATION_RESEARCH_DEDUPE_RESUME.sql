-- M0N4C0 Research Dedupe + Resume migration
-- Safe to run multiple times. Does not delete data.

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

PRAGMA optimize;
