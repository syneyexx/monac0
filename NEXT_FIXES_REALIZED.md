# M0N4C0 — NEXT FIXES REALIZED

This build implements the new fix-list as functional code, not just todo text.

## Completed

1. LLM page system prompt editor fixed:
   - Live prompt text box remains editable.
   - Page has a vertical scrollbar.
   - Added a large standalone prompt editor window with its own scrollbar.
   - Apply Live saves and updates runtime config without restart.

2. Sidebar/menu rebuilt:
   - Grouped menu sections.
   - Sidebar has its own scrollbar.
   - Live Feed is visible near the top.
   - Added a dedicated Live Feed page.

3. Telegram token visibility:
   - Token input is no longer masked by default.
   - Status view shows the configured token from local GUI state.

4. Telegram username permissions:
   - Added owner_usernames support in runtime settings.
   - GUI now lets the user enter usernames like @username.
   - Bot permission checks usernames when Allow all users is disabled.
   - Legacy numeric IDs remain supported only for backwards compatibility.

5. Premium branding:
   - Added M0N4C0 logo assets.
   - Added app icon PNG/ICO.
   - GUI title and sidebar branding updated for a more exclusive feel.

6. Technical pages usability:
   - Performance page redesigned with presets, sliders, toggles, helper text and clear actions.
   - SQLite tuning controls are safer and more user-friendly.

## Database

No required database schema changes in this build.
No database file is included.
No .env file is included.
