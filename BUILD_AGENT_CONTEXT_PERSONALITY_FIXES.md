# M0N4C0 Build Agent Context + Personality/Freshness Fixes

Deze build realiseert de nieuwste todo-punten:

## Build Agent
- Context Overflow Auto-Recovery bij `context size exceeded`.
- Small-context patch mode met bestandslijst/samenvatting en 3-5 gerichte files.
- Relevante snippets rondom functies/classes/matches in plaats van altijd hele files.
- Patch per bestand met hash-verificatie na schrijven.
- Manual File Target Mode in de GUI: geef exacte files op die de agent mag analyseren/aanpassen.
- Betere foutmelding met tips wanneer het coding model te weinig context heeft.
- Retry zonder fake success: alleen export bij echte gewijzigde bestanden.

## GUI
- Build Agent pagina heeft een Manual File Target Mode veld.
- De pagina meldt duidelijk dat small-context retry actief is.

## Personality + anti-hallucination
- GUI en Telegram routes gebruiken de actieve personality/system-prompt consequenter.
- Telegram forceert standaard de Telegram-modelrol wanneer geen andere rol gekozen is.
- Actuele/tijdgevoelige vragen triggeren web/freshness guard wanneer internet aan staat.
- Antwoorden krijgen strengere bron- en onzekerheidsregels: geen verzonnen feiten, geen oude data als actueel verkopen, eerlijk melden bij onzekerheid.

## Database
Geen verplichte database-migratie.
