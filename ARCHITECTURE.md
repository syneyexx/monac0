# M0N4C0-AI architectuur

## Filosofie

M0N4C0-AI is lokaal-first en SQLite-first. Geen losse tekstbestanden als hoofdgeheugen. Alles wordt opgeslagen in `data/monaco_memory.db`.

## Hoofdmodules

- `main.py` — start terminal/Telegram
- `monaco_ai/config.py` — settings uit `.env`
- `monaco_ai/db.py` — SQLite schema, FTS5, memory, chunks
- `monaco_ai/llm.py` — LM Studio / Dolphin client
- `monaco_ai/commands.py` — command router
- `monaco_ai/reasoning.py` — context + retrieval + LLM-answer flow
- `monaco_ai/memory.py` — gesprek leren / facts opslaan
- `monaco_ai/retrieval.py` — FTS retrieval
- `monaco_ai/web_research.py` — internet search/fetch/self-learning
- `monaco_ai/website.py` — publieke website learning
- `monaco_ai/telegram_bot.py` — Telegram interface
- `tools/import_documents.py` — documenten importeren
- `tools/website_browser_learn.py` — manual login browser learning
- `tools/db_doctor.py` — database diagnose

## SQLite tabellen

- `users`
- `conversations`
- `memory_facts`
- `knowledge_sources`
- `knowledge_chunks`
- `knowledge_chunks_fts`
- `learning_jobs`
- `web_pages`
- `website_profiles`
- `website_actions`
- `answer_cache`
- `bot_writes`
- `errors`

## Context limit bescherming

De LLM-client gebruikt `safe_chat()` met retries. Bij errors of lege antwoorden wordt context verkleind en opnieuw geprobeerd.

## Website login

Website login werkt via Playwright persistent browser profile. De gebruiker logt zelf in. De bot slaat daarna alleen toegestane pagina-inhoud op.

## Uitbreidbaar

Je kunt later modules toevoegen voor vectors, GUI, image, voice, trading, Instagram, etc. De kern is schoon en vanaf nul gebouwd.

## Brain Nodes architecture

`monaco_ai/brain_nodes.py` bouwt runtime een graph uit bestaande SQLite-tabellen. Er is bewust geen extra externe dependency gebruikt.

Bronnen:

- `knowledge_chunks` → topic-, chunk- en keyword-nodes
- `memory_facts` → subject/object-nodes met predicate-relaties
- `conversations` → recente conversatie-termen

De GUI rendert deze graph met Tkinter Canvas in `monaco_ai/gui.py`. De view ondersteunt hover-inspector, select highlighting, draggen, filteren, refresh en canvas zoom.

Als `knowledge_chunks` en `memory_facts` allebei leeg zijn, seedt `seed_default_football_knowledge()` automatisch een lokale football knowledge pack. Daardoor heeft een verse installatie meteen een zichtbaar brein zonder internet of LM Studio nodig.

## External Learning Worker Architecture

M0N4C0 gebruikt nu een queue-gebaseerde research architectuur:

```txt
GUI / Telegram / Terminal
  -> CommandRouter detecteert leer-intent
  -> learning_jobs row in SQLite met status=queued
  -> learning_worker.py claimt job via claim_next_learning_job()
  -> WebResearcher zoekt/fetcht/chunkt/summarizet
  -> knowledge_sources + knowledge_chunks + learning_events worden opgeslagen
  -> GUI Research tab en Brain Nodes lezen live uit dezelfde SQLite DB
```

Voordeel: de chatbot blijft responsief terwijl zware research buiten de hoofd-GUI draait. Meerdere worker-agents kunnen tegelijk verschillende jobs verwerken.

## 2026 GUI Runtime Upgrade

- Local Database Manager is now wired to the existing sidebar button. It is read-only by default, supports table/view browsing, pagination, full-table search, schema/index inspection, CSV/JSON export, integrity checks, FTS rebuild, and timestamped SQLite backups before write operations.
- Telegram Manager is now wired to the existing sidebar button. It saves live settings in `data/telegram_settings.json`, supports token/owner/allow-all settings, and can start/stop/restart polling from the GUI without restarting the desktop app.
- LLM Models now supports two roles: Chat Model and Coding Model. The runtime can auto-route programming/code/debug/codebase prompts to the Coding Model while normal chat keeps using the Chat Model.

No existing database tables are dropped or recreated by this upgrade. Existing `data/monaco_memory.db` files stay compatible.
