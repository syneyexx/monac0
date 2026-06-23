# M0N4C0 AI update notes

## Added
- Live editable system prompt in the LLM Models page.
- System prompt changes apply immediately to future GUI and Telegram answers without restarting.
- Back to chat button on every major page.
- Sidebar placeholders for Image generation and Trading Dashboard.

## Performance changes
- Database manager table counts are lazy now, so opening the DB page does not force COUNT(*) over every table.
- SQLite connections use WAL, NORMAL sync, memory temp store, cache_size, and mmap_size.
- Extra non-destructive indexes are created automatically on startup.
- LM Studio disk model discovery is cached briefly to avoid repeated expensive scans.

## Database
- No database file is included in this zip.
- No existing data is deleted.
- Optional/manual SQL is in MIGRATION_PERFORMANCE_INDEXES.sql.
