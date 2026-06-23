# M0N4C0 Tools Roadmap Realized

This build realizes the current Tools roadmap as working modules instead of a todo list.

## Implemented

1. **Tools page**
   - Telegram username normalizer.
   - Telegram token diagnostics via official `getMe` check.
   - Runtime Telegram settings overview.
   - URL/source validator with redirect, content-type, status and document/e-book detection.
   - Research URL advice.
   - Database quick health.
   - Latest logs/errors viewer.
   - Consent-based network diagnostic link using a transparent local HTTP server.
   - Public IP self-check.

2. **GUI Build Agent / Source Editor**
   - Select source zip or project folder.
   - Enter build instruction.
   - Analyze safely in `data/build_agent_workspaces`.
   - Run LLM-assisted patch flow in a temporary workspace only.
   - Review plan, changed files, checks and export path in the GUI.
   - Export patched zip without `.env`, SQLite databases, caches or pyc files.
   - Runs Python compile and JSON checks.

3. **Clean chat output**
   - User-facing answers no longer show `[tech: chunks=0 ...]` metadata by default.
   - Technical metadata is scrubbed by the final response guard.
   - Tech details only appear when explicitly enabled through verbose/debug logic and should still be kept out of normal chat output.

4. **Consent-based IP/network diagnostic**
   - No Telegram-username IP grabbing.
   - Network/IP diagnostic only works when someone opens a clearly labelled diagnostic link or runs a self-check.
   - Diagnostic records are stored transparently under `data/diagnostics` when used.

## Database

No schema migration is required for this build.

## Safety

- The Build Agent never edits the real selected project directly.
- Source zip/folder is copied/extracted into a temporary workspace first.
- `.env`, `.db`, `.db-wal`, `.db-shm`, `.git`, caches and virtual environments are excluded.
- Consent diagnostic page clearly explains what is measured.
