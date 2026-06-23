-- M0N4C0 AI performance indexes
-- Safe / non-destructive. Run against your existing data/monaco_memory.db if you want to apply manually.
-- The updated app also creates these automatically on startup.

PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;
PRAGMA cache_size=-64000;
PRAGMA mmap_size=268435456;

CREATE INDEX IF NOT EXISTS idx_conversations_chat_role_id
ON conversations(chat_id, role, id DESC);

CREATE INDEX IF NOT EXISTS idx_memory_user_updated
ON memory_facts(user_key, updated_at);

CREATE INDEX IF NOT EXISTS idx_chunks_topic_quality_id
ON knowledge_chunks(topic, quality_score DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_chunks_created
ON knowledge_chunks(created_at);

CREATE INDEX IF NOT EXISTS idx_learning_events_created
ON learning_events(created_at);

CREATE INDEX IF NOT EXISTS idx_answer_cache_created
ON answer_cache(created_at);

CREATE INDEX IF NOT EXISTS idx_learning_jobs_status_updated
ON learning_jobs(status, updated_at DESC);

PRAGMA optimize;
