# M0N4C0 Build Agent & Tools Final Realized

Deze build realiseert de nieuwe Build Agent / Tools todo-lijst als werkende modules.

## Gerealiseerd

1. **Run Preview Build**
   - Build Agent kan een gepatchte workspace handmatig starten vanuit de GUI.
   - Knoppen: Run preview build, Stop preview, Run compile checks, Open workspace, Export final zip.
   - Preview draait vanuit de tijdelijke workspace, niet vanuit de echte projectmap.

2. **Echte wijzigingen verplicht**
   - Build Agent vergelijkt file hashes vóór en na patchen.
   - Zonder echte changed-files wordt export geblokkeerd.
   - Output zip wordt gecontroleerd op aanwezigheid van gewijzigde files.

3. **Diff Preview + Apply Patch**
   - Na een patch toont de GUI een unified diff per aangepast bestand.
   - Changed-files lijst en checks staan los zichtbaar.

4. **Rollback / Restore**
   - Elke Build Agent-run bewaart een rollback snapshot.
   - De GUI heeft een Rollback-knop om de workspace terug te zetten.

5. **Auto Test Report**
   - Build Agent maakt een test report met py_compile, JSON check, requirements, .env/database exclusion en export-verificatie.

6. **No Fake Success**
   - Geen echte filewijziging = geen succesmelding en geen automatische export.

7. **Source Cleaner**
   - Dependency Doctor bevat Source Cleaner preview en run.
   - Verwijdert veilige caches/tempbestanden; beschermt database en .env.

8. **Dependency Doctor**
   - Nieuwe pagina met Python/package checks, LM Studio status en install commands.

9. **Model Benchmark**
   - Nieuwe pagina voor snelle chat/code model benchmark via LM Studio.

10. **Smart Error Explainer**
   - Nieuwe pagina waar je tracebacks kunt plakken.
   - Geeft uitleg + Build Agent fix-instructie en kan die direct naar Build Agent sturen.

11. **Safe Mode**
   - Nieuwe `START_SAFE_MODE.bat`.
   - `run_m0n4c0.py --gui --safe-mode` en `main.py --safe-mode` ondersteund.
   - Safe mode toont alleen repair/tools modules en autostart Telegram niet.

12. **Plugin Manager**
   - Nieuwe pagina om modules aan/uit te zetten.
   - Instellingen worden opgeslagen in `data/plugin_settings.json`.
   - Sidebar respecteert disabled modules en toont ze als uitgeschakeld.

## Veiligheid

- Geen database meegeleverd.
- Geen `.env` meegeleverd.
- Build Agent werkt alleen in `data/build_agent_workspaces/`.
- Export sluit database, `.env`, caches en bytecode uit.

## Checks uitgevoerd

- Python compile-check op alle `.py` bestanden.
- BuildAgent smoke-test met dummy LLM: echte wijziging → diff → export → verificatie.
- Dependency Doctor smoke-test.
- Safe mode starter gegenereerd.
