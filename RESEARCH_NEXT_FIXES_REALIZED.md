# M0N4C0 — Research Next Fixes Realized

Deze build realiseert de nieuwste research/idle/knowledge todo-punten als echte functies, op basis van de vorige `M0N4C0_AI_WORLDCLASS_NEXT_FIXES_REALIZED` source.

## Ingebouwd

1. **E-book mode is nu document-only**
   - HTML pagina's worden alleen nog gebruikt om echte document/e-book links te vinden.
   - E-book mode slaat geen willekeurige category/menu/search HTML-pagina's meer op als kennis.
   - Ondersteunt documentdetectie voor PDF, EPUB, DOCX, TXT, MD, RTF en e-book extensies.
   - Crawlen gebeurt via requests en respecteert geen robots.txt-parser in deze app; het blijft wel gelimiteerd met depth/pages/files.

2. **Idle Learning + Wikipedia**
   - Idle pagina heeft een Wikipedia-optie.
   - Als er geen topic klaarstaat en Wikipedia random aan staat, queue't de idle worker automatisch een `wikipedia` job.
   - Je kunt ook handmatig een Wikipedia idle topic toevoegen.

3. **Saved Sources verwijderen**
   - Research pagina heeft nu een Remove Source flow.
   - Vul het ID in uit de Saved Sources lijst en verwijder direct vanuit de GUI.

4. **Next-level learning verbeterd**
   - Research summaries vragen nu expliciet om open vragen, vervolgzoekvragen en fact-check status.
   - Worker gebruikt follow-up queries uit de samenvatting om volgende rondes slimmer te maken.

5. **Mission Control / Autopilot Planner**
   - Nieuwe pagina in het menu.
   - Vul een groot doel in, maak een plan en start een missie.
   - Missie queue't research jobs en start externe worker CMD.

6. **Lege Brein / Wipe Knowledge**
   - Memory pagina heeft nu een gevaarlijke knop om het brein te wissen.
   - Eerst verschijnt de bevestiging: `WEET JE ZEKER DAT JE HET BREIN WILT WISSEN?`
   - De app maakt automatisch een SQLite backup voordat hij kennis/memory/research/sources/personen wist.

7. **Logo opnieuw gemaakt**
   - Nieuwe premium M0N4C0 icon/logo assets.
   - Sidebar toont niet dubbel nog eens losse M0N4C0 tekst als het logo geladen is.

## Database

Geen verplichte SQL-migratie nodig voor deze build. De nieuwe functionaliteit gebruikt bestaande tabellen en app settings.

## Checks

- Python compile-check op alle `.py` files.
- DB init smoke-test.
- Document URL test: HTML wordt niet meer als document gezien, PDF wel.
- Worker/GUI modules importeren zonder syntax errors.

