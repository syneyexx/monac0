# M0N4C0-AI

Nieuwe, schone Python 3.11 AI-bot vanaf nul gebouwd. De bot kan draaien via terminal en Telegram, gebruikt standaard LM Studio met Dolphin3.0 Llama3.1 8B via OpenAI-compatible endpoint, slaat kennis/gesprekken/memory lokaal op in SQLite en kan zelf leren via internet en websites.

## Belangrijk

M0N4C0-AI is lokaal-first. Alles wordt opgeslagen in `data/monaco_memory.db`.

De website-login laag werkt alleen met toegang die jij rechtmatig hebt. De bot omzeilt geen beveiliging, captchas, 2FA of toegangscontrole. Voor 2FA/manual login gebruikt hij een browservenster waar jij zelf kunt inloggen.

## Installatie

```bat
cd M0N4C0_AI
py -3.11 -m venv .venv
.venv\Scripts\activate
py -3.11 -m pip install -U pip
py -3.11 -m pip install -r requirements.txt
copy .env.example .env
```

Zorg dat LM Studio draait op:

```txt
http://localhost:1234/v1
```

En laad je Dolphin model in LM Studio.


## Start GUI

Standaard start `main.py` nu direct de desktop-GUI:

```bat
py -3.11 main.py
```

Of expliciet:

```bat
py -3.11 main.py --gui
```

De GUI gebruikt dezelfde `CommandRouter`, SQLite database, LM Studio client, memory en self-learning als terminal/Telegram. Je hoeft dus niet meer via de terminal te chatten.

## Terminal blijft optioneel

```bat
py -3.11 main.py --terminal
```

## Telegram + GUI samen

```bat
py -3.11 main.py --both
```

## Start terminal

```bat
py -3.11 main.py --terminal
```

## Start Telegram

Vul in `.env` je Telegram token in:

```txt
TELEGRAM_BOT_TOKEN=123456:ABC
TELEGRAM_ENABLED=true
```

Start:

```bat
py -3.11 main.py --telegram
```

Of terminal + Telegram samen:

```bat
py -3.11 main.py --both
```

## Eerste commands

```txt
/help
/status
/memory stats
wat kan jij?
leer alles over quantum mechanics
/learn topic quantum mechanics rounds=3
/search laatste AI nieuws
/knowledge search quantum mechanics
/website learn https://example.com
/website login https://example.com
/db check
```

## Kernfuncties

- Terminal interface
- Telegram interface
- LM Studio / Dolphin LLM client
- SQLite memory database
- FTS5 full-text search
- Conversation memory
- User profile memory
- Self-learning via web search/fetch/chunk/summarize
- Website learning
- Manual browser login support via Playwright
- Knowledge retrieval
- Context budgeting
- Context overflow recovery
- Answer cleaning
- Local-first memory
- Export/import basics
- Command registry
- Background-ish learning jobs via task records

## Config

Zie `.env.example` en `monaco_ai/config.py`.

## Disclaimer

Deze bot kan informatie vergaren en structureren, maar echte webacties/accountacties moeten binnen jouw eigen toegangsrechten blijven. Voor gevoelige handelingen hoort menselijke bevestiging gebruikt te worden.


## Update: gewone berichten zonder /ask

M0N4C0-AI behandelt normale Telegram- en terminalberichten nu automatisch als gesprek of vraag. Je hoeft dus geen `/ask` of `/vraag` te gebruiken.

Voorbeelden:

```txt
wat weet je over databases?
kan je dit uitleggen?
zoek alles uit over crypto trading
leer alles over elke voetbal wedstrijd tussen 1995 - 2025
```

## Update: brede self-learning opdrachten

De bot herkent natuurlijke opdrachten zoals:

```txt
leer alles over <onderwerp>
word expert in <onderwerp>
zoek alles uit over <onderwerp>
leer alles over <onderwerp> tussen 1995 - 2025
```

Bij jaarreeksen maakt hij automatisch een breed leerplan met zoekopdrachten per jaar/tijdslice. Alles wordt lokaal opgeslagen in SQLite als bronnen, chunks, webpagina’s en learning jobs.

Expert-level learning is nu de standaard. Voor natuurlijke opdrachten zoals `Leer elke pokemon, vanaf het jaar 2000 tot en met het jaar 2026` pakt de bot automatisch maximale researchdiepte.

## LLM foutmeldingen

Als LM Studio of Dolphin niet bereikbaar is, geeft M0N4C0-AI nu een duidelijke technische melding in plaats van een vage “het spijt me...” fallback. Check dan:

```txt
/status
/self audit
```

## Update: Brain Nodes GUI ☍

De linkerknop **Brain Nodes** is nu functioneel. Hij opent een Obsidian-achtige visualisatie van het lokale brein van M0N4C0-AI.

Wat werkt nu:

- Graph view direct vanuit de GUI-sidebar
- Nodes uit SQLite:
  - knowledge chunks
  - memory facts
  - recente gesprekken
  - keywords/topics
- Relaties tussen nodes via lijnen
- Hover op een node toont uitleg, type, score en directe relaties
- Klik/selecteer nodes om relaties vast te houden
- Sleep nodes rond om het brein handmatig te ordenen
- Scroll in de graph om te zoomen
- Filter/search bovenin de Brain Nodes pagina
- Refresh-knop om nieuwe kennis na learning/import meteen te visualiseren
- Als de database leeg is, wordt automatisch een lokale expert football + general + markets brain packs toegevoegd zodat de visualisatie direct gevuld is

Extra command:

```txt
/brain stats
```

Deze command toont hoeveel nodes/relaties Brain Nodes kan bouwen uit de database.

## Brain Nodes Expert Update

Brain Nodes is now a real visual second-brain view:

- Sidebar button opens an Obsidian-style graph.
- Click a node to inspect stored knowledge.
- Hover a node for preview.
- Drag nodes to arrange them.
- Drag empty space to pan across the map.
- Mouse wheel zooms.
- Filter searches topics/nodes.
- Research/learning results are stored in SQLite and appear after refresh; if Brain Nodes is open, the graph refreshes after a chat request finishes.
- Empty or old seed databases are automatically filled with football + general + markets foundational knowledge.

Run:

```bat
py -3.11 main.py
```

Then click **Brain Nodes** in the sidebar.

## Fix update - Brain Nodes Inspector

Deze build fixt een Tkinter crash in Brain Nodes waarbij de Node Inspector als `Label` was aangemaakt terwijl de update-code een `Text` widget verwachtte. De inspector is nu scrollbaar en stabiel bij hover/click/drag.

Gecheckt:
- `python -m py_compile` over alle Python-bestanden
- GUI smoke-test onder Xvfb
- Brain Nodes openen, hoveren, klikken, resetten en inspector updaten

## Update: Live Core Terminal + Expert Markets Pack

Deze build voegt in de linker sidebar een **LIVE CORE** mini-terminal toe. Daar zie je tijdens chat/research wat M0N4C0 doet:

- prompt ontvangen
- routing door CommandRouter
- memory extraction
- learning intent detection
- zoekqueries
- pagina fetches
- chunks schrijven naar SQLite
- summaries opslaan
- Brain Nodes refreshen
- errors/warnings

Ook is de database uitgebreid met een lokale **Expert Stocks & Crypto Markets 2000-2026** seed pack. Bestaande voetbal/general knowledge blijft behouden. De marktkennis is bedoeld als educatief framework en historisch/structureel brein; live prijzen, actuele ETF-flows en regelgeving moeten altijd vers worden gecontroleerd voordat je financiële conclusies trekt.

## Personality Page

De GUI heeft nu een werkende **Personality** pagina. Klik links op `Personality` om de stijl van M0N4C0 aan te passen.

Wat werkt:
- Core trait sliders: intelligence, curiosity, creativity, empathy, confidence, humor, patience, directness.
- Behavior sliders: formality, response length, proactivity, analytical depth, decision style.
- Communication sliders: warmth, motivation, storytelling, examples.
- Speech & tone: tone dropdown, language style dropdown, vocabulary complexity, emoji use, sarcasm/wit.
- Memory & learning toggles.
- Presets + quick actions.
- Import/export JSON profile.
- Save Changes schrijft naar `data/personality_profile.json`.
- Nieuwe chat-antwoorden gebruiken de opgeslagen personality prompt automatisch.

Let op: schuiven verandert de preview direct. Klik **Save Changes** om het echt op te slaan en toe te passen op nieuwe chat-antwoorden.

## Personality Full Control Update

Deze build breidt de Personality-pagina uit van alleen stijl naar een volledige behavior-console.

Nieuwe groepen:
- Core Traits
- Reply Rules / When To Talk
- Speech & Tone
- Behavior Style
- Autonomy / Research
- Memory Behavior
- Communication Style
- Safety / Privacy
- All Switches

Belangrijkste nieuwe opties:
- Response Frequency
- Telegram DM Replies
- Telegram Group Replies
- Mention Priority
- Require Mention In Groups
- Ignore Low-value Chatter
- Silence Threshold
- Interruptiveness
- Auto Research Learning Requests
- Auto Web Search Fresh Topics
- Learning Depth
- Research Autonomy
- Brain Update Aggression
- Memory Write Frequency
- Memory Recall Strength
- Privacy Guard
- Hallucination Caution

Telegram gebruikt de reply-rules nu echt:
- Slash commands reageren altijd.
- Mentions/replies kunnen quiet mode overrulen.
- Groepschat zonder mention wordt geregeld door Telegram Group Replies, Silence Threshold en Low-value Chatter Filter.

### Update: Telegram long message splitter

Large Telegram replies are now sent in multiple numbered parts automatically. This is enabled by default through Personality → All Switches:

- Split Long Telegram Messages
- Number Split Messages

This keeps long research answers from being rejected or cut off by Telegram's message-size limit.


## LLM Models page

The left sidebar button **LLM Models** is now functional.

Features:
- Lists models visible through LM Studio's OpenAI-compatible `/v1/models` endpoint.
- Tries LM Studio local API endpoints when available.
- Scans common LM Studio download folders for `.gguf` models, including `%USERPROFILE%\.lmstudio\models`.
- Selects a model, saves it to `data/llm_model_settings.json`, and applies it immediately to the running router.
- Persists Base URL, temperature, max tokens, context size, top_p, repeat_penalty, top_k and min_p.
- Includes connection test, chat test, benchmark, import/export, reset defaults and Open LM Studio actions.

If LM Studio does not expose a model-load endpoint, M0N4C0 will still save the selected model id. Load the model manually inside LM Studio if the chat test fails.

## Update: Context & No-Repeat Guard

Deze build bevat een context-fix voor antwoorden die soms een oud antwoord eerst herhaalden en daarna pas het nieuwe antwoord gaven.

Wat is aangepast:
- ReasoningEngine schrijft geen extra interne assistant-response meer naar `conversations`.
- Recente chatcontext comprimeert oude assistant-antwoorden tot korte samenvattingen.
- De huidige user-vraag wordt niet meer dubbel in de context gezet.
- Een ResponseGuard verwijdert per ongeluk herhaalde paragrafen/regels.
- Een old-answer echo guard stript een vorige assistant-response als het model die vóór het nieuwe antwoord plakt.
- GUI, Telegram en terminal gaan nu via dezelfde final-answer cleanup.

Start normaal met:

```bat
py -3.11 main.py
```

Voor GUI + Telegram:

```bat
py -3.11 main.py --both
```

## Context leak fix

Deze build bevat een extra ResponseGuard-laag tegen context-leaks:
- `...[ingekort]...` en interne contextmarkers worden niet meer zichtbaar in antwoorden.
- Oude assistant-antwoorden worden niet meer als rauwe chat-context terug naar het model gestuurd.
- Retrieval/context truncation gebruikt geen zichtbare `[ingekort]` markers meer.
- GUI, Telegram en terminal laten het antwoord eerst door `finalize_answer()` gaan.

## Dutch language guard

Deze build forceert Nederlands als standaardtaal:
- Nederlandse vragen krijgen Nederlandse antwoorden.
- Bij gemengde NL/EN tech-taal antwoordt M0N4C0 Nederlands en laat code/commands/modelnamen intact.
- Als het lokale model per ongeluk Engels teruggeeft, herschrijft de language guard het antwoord automatisch naar Nederlands.
- Engels blijft mogelijk wanneer je daar expliciet om vraagt, bijvoorbeeld: "antwoord in English".


## External Learning Worker + Research Agents

Deze build verplaatst zware research/learning naar een aparte worker queue:

- Chat/GUI/Telegram zetten alleen een learning job in SQLite.
- `learning_worker.py` claimt queued jobs en doet zoeken, fetchen, chunking en samenvatten.
- Meerdere agents kunnen tegelijk jobs verwerken met `--agents`.
- De GUI heeft een nieuwe **Research** tab voor queue, status, live events, cancel en worker start.

Start alleen de GUI:

```bat
py -3.11 main.py
```

Start de externe worker los:

```bat
py -3.11 learning_worker.py --agents 3
```

Of dubbelklik:

```bat
START_WORKER_CMD.bat
```

GUI + Telegram + worker in losse vensters:

```bat
start_all.bat
```

Commands:

```txt
/research queue <onderwerp> rounds=5
/research jobs
/research cancel <id>
/learn topic <onderwerp> rounds=5
/learn broad <onderwerp> years=2000-2026 rounds=10
```

Natuurlijke vragen zoals `Leer alles over bedrijfsvoering` worden nu ook als background job geplaatst.

## Extra general knowledge seed

De lokale database bevat nu extra algemene basiskennis naast voetbal/markets, o.a. bedrijfsvoering, verdienmodellen, cashflow, boekhouding, btw, belastingbasis, sales, marketing, inkoop, voorraad, HR, juridische basis, productiviteit, risico, strategie, data-analyse en AI-automatisering. Dit is educatieve seed-kennis en geen persoonlijk financieel/fiscaal/juridisch advies.
