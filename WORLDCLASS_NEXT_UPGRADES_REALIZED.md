# M0N4C0 Worldclass Next Upgrades — Realized

This build implements the next worldclass roadmap layer on top of the previous source.

## Implemented

- Freshness Guard / Anti-Stale Knowledge classification (`stable`, `fresh`, `uncertain`).
- GUI + Telegram shared web fact-check routing for current/fresh questions.
- Database freshness metadata migration for knowledge sources/chunks.
- Source labels, confidence and freshness headers in retrieval context.
- Honest offline behavior when a live fact-check is needed but web is unavailable.
- Reasoning/source summary without exposing hidden chain-of-thought.
- Truth Engine / Source Judge with built-in official-source scoring and GUI source rules.
- Evidence Vault for web-check/source snapshots.
- Skill Memory and Project Memory storage.
- Self-Test Lab inside the new Worldclass Lab page.
- Command Center / Global Search via `Ctrl+K`.
- Context Budget Manager for safer prompt/context sizing.
- Workflow Templates / One-Click Missions list.
- Permission & Safety Center settings view/toggles in Worldclass Lab / Command Center.
- Release Manager clean zip export tool.
- Database Manager "Lege Brein" button.
- Knowledge Timeline view.
- Smart Source Blacklist/Whitelist.
- Conversation Quality Scanner and quality reports.
- AI Job Scheduler storage/overview.
- New slash commands: `/truth classify`, `/knowledge timeline`, `/evidence vault`, `/source trust`, `/source block`, `/project remember`, `/workflow templates`.

## Notes

- No database or `.env` is included in the zip.
- The app auto-migrates the DB on startup.
- Manual SQL is included in `MIGRATION_WORLDCLASS_NEXT_UPGRADES.sql`.
- Live web checking depends on your local internet + ddgs/research setup.
- LM Studio-dependent outputs cannot be fully validated in this headless build environment, but compile and smoke checks pass.
