# M0N4C0 / SDEN AI — Worldclass V3 Release Notes

Deze build gebruikt de vorige `M0N4C0_AI_WORLDCLASS_LIVE_PROMPT_FAST_UI` als basis en voegt de roadmap-functies laag-voor-laag toe zonder jouw bestaande database mee te sturen of te verwijderen.

## Grote wijzigingen

### Research
- Research pagina ondersteunt nu modes: `topic`, `broad`, `website`, `ebooks`, `documents`, `news`, `competitor`, `deep`.
- Je kunt specifieke bron-URL's invoeren en opslaan als research source.
- Jobs krijgen extra worker-instellingen: depth, max pages, max files, priority en rounds.
- Worker start vanuit GUI als los process / aparte CMD op Windows.
- Worker kan publieke HTML-pagina's crawlen en PDF/EPUB/DOCX/TXT/HTML documenten uitlezen.
- E-book/document ingest doet geen DRM-bypass en is bedoeld voor publieke/toegankelijke bronnen.

### Idle Learning
- Nieuwe `Idle Learning` pagina.
- Idle topics beheren vanuit GUI.
- `idle_worker.py` queue't automatisch research wanneer de bot langer dan ingestelde tijd idle is.
- Idle learning gebruikt externe research jobs, zodat de GUI soepel blijft.

### GUI / UX
- Main chatbox heeft nu een modelselector per bericht: Auto, Chat, Code, Research, Telegram, Image, Trading.
- Zware pagina's zijn verder gescheiden in losse panels.
- Brain Nodes opent nu met background loading in plaats van alles direct te blokkeren.
- Extra pagina's: Performance, Memory, Logs, Image Generation, Trading Dashboard.

### LLM
- LLM pagina heeft nu split/single model mode.
- `Use for ALL + Save` zet één geselecteerd model voor chat/code/research/telegram/image/trading.
- Runtime config ondersteunt aparte rollen voor toekomstige modules.

### Performance / maintenance
- Nieuwe Performance Center pagina met optimize, FTS rebuild, backup en cache clear.
- Nieuwe Memory Manager en Logs pagina.
- Nieuwe database-tabellen voor research sources, idle topics, app tasks en app settings.
- Migratie staat los in `MIGRATION_WORLDCLASS_V3.sql`.

### Installer / start scripts
- Oude losse .bat-spaghetti is vervangen door:
  - `INSTALL.bat`
  - `START_GUI.bat`
  - `START_WORKER_CMD.bat`
- Nieuwe Python launchers:
  - `install_m0n4c0.py`
  - `run_m0n4c0.py`

## Database
De build bevat geen `monaco_memory.db`. Laat jouw bestaande database in `data/monaco_memory.db` staan.

De app voert migraties ook zelf veilig uit bij startup. Wil je handmatig migreren via Database Manager, gebruik `MIGRATION_WORLDCLASS_V3.sql`.
