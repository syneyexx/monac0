# M0N4C0 Research Dedupe + Resume — Realized

Deze build maakt research/e-book jobs betrouwbaarder voor grote lokale libraries zoals XAMPP/localhost mappen met honderden of duizenden PDF/e-book bestanden.

## Gerealiseerd

- Pre-download duplicate skip via `research_document_registry.url`.
- Post-download duplicate skip via SHA256 file/content hash en extracted-text hash.
- Duidelijke worker logs: `SKIPPED duplicate document URL` en `SKIPPED duplicate document hash`.
- Per-job checkpoint tabel `research_job_items`.
- Crawled/discovered URLs worden opgeslagen als pending/done/skipped/failed items.
- Als een worker/app stopt, worden unfinished running jobs bij worker-start opnieuw queued.
- Items met status `processing` worden teruggezet naar `pending`, zodat de volgende worker ze opnieuw veilig oppakt.
- E-book mode blijft HTML alleen als discovery gebruiken en slaat alleen echte documenten/e-books op.
- GUI-antwoorden worden nu ook opgesplitst in meerdere bubbles als ze te lang zijn, zodat de tekst niet zichtbaar halverwege lijkt afgekapt.

## Belangrijk

De zip bevat geen database en geen `.env`. De app migreert automatisch bij startup. De losse migratie staat in `MIGRATION_RESEARCH_DEDUPE_RESUME.sql`.

## Getest

- SQLite init + nieuwe tabellen.
- URL/hash registry methods.
- Interrupted job requeue.
- Local HTTP/XAMPP-style e-book crawl met duplicate content.
- Tweede run skipte dezelfde documenten vóór download op URL-niveau.
- Python compile-check op alle `.py` bestanden.
