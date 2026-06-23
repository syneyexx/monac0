# M0N4C0-AI Commands

## Gewoon praten
Je hoeft geen `/ask` of `/vraag` te typen. Stuur gewoon een bericht:

```txt
wat is quantum mechanics?
kan je dit uitleggen?
zoek alles uit over AI agents
leer alles over elke voetbal wedstrijd tussen 1995 - 2025
```

De router herkent automatisch of het een gewone vraag, zoekopdracht of self-learning opdracht is.

## Basis

```txt
/help
/status
/db check
/self audit
/self improve plan
/ping
/whoami
/myid
```

## Vragen

```txt
/ask <vraag>
/vraag <vraag>
```

Maar dit hoeft dus niet meer. Normale tekst werkt ook.

## Web/search

```txt
/search <zoekvraag>
zoek <zoekvraag>
zoek op <zoekvraag>
check online <zoekvraag>
```

## Self-learning

```txt
/learn topic <onderwerp> rounds=3
/learn expert <onderwerp>
/learn broad <onderwerp> years=1995-2025 rounds=10
/learn jobs
/learn offline <onderwerp>
```

Natuurlijk taal werkt ook:

```txt
leer alles over kunstmatige intelligentie
word expert in databases
zoek alles uit over quantum mechanics rounds=5
leer alles over elke voetbal wedstrijd tussen 1995 - 2025
```

Bij brede opdrachten met jaartallen maakt M0N4C0-AI automatisch meerdere zoekrondes en tijd-slices aan. De gevonden pagina’s, samenvattingen en chunks worden lokaal in SQLite opgeslagen.

## Kennis/memory

```txt
/knowledge search <query>
/retrieval debug <query>
/memory stats
/memory search <query>
/remember <tekst>
```

## Websites

```txt
/website learn <url>
/website login <url>
/website status
```

`/website login` gebruikt alleen handmatige login/sessies waarvoor jij toegang hebt. Geen bypass of omzeiling.

## Brain Nodes

```txt
/brain stats
/brain nodes
/brain graph
```

Geeft graph-statistieken terug en seedt, indien de database nog leeg is, automatisch de lokale expert football + general + markets demo-kennis.

## Live Core Terminal

De GUI heeft links nu een kleine terminal-style activity stream. Bij gewone vragen, learning jobs en broad research toont hij live stappen zoals search queries, fetched pages, chunk writes, summaries en SQLite updates.

## Extra Seed Pack

Brain Nodes seedt nu naast voetbal en algemene basiskennis ook een expert pack voor aandelen- en cryptomarkten van 2000 t/m 2026. Dit pack wordt maar één keer toegevoegd en behoudt bestaande database-inhoud.

## GUI: Personality

Geen command nodig. Start de GUI en klik links op **Personality**.

De opgeslagen personality staat in:

```text
data/personality_profile.json
```

M0N4C0 voegt deze personality-instellingen automatisch toe aan de lokale system prompt bij normale chat-antwoorden.

## Personality / Behavior

De Personality GUI heeft nu volledige behavior controls. De belangrijkste Telegram regels:

- Commands blijven altijd werken.
- `Telegram Group Replies` bepaalt hoe vaak M0N4C0 in groepen spontaan reageert.
- `Require Mention In Groups` maakt hem stil tot iemand hem noemt of op hem replyt.
- `Ignore Low-value Chatter` filtert korte ruis zoals lol/haha/test.
- `Response Frequency` is de globale praat-neiging.
- `Telegram DM Replies` regelt private chat reacties.

## Telegram long replies

Long Telegram answers are now split automatically into multiple safe messages. This prevents Telegram's 4096-character limit from cutting off large learning/research answers.

Personality → All Switches includes:
- Split Long Telegram Messages
- Number Split Messages


## GUI: LLM Models

Open the desktop app and click **LLM Models**.

Recommended flow:
1. Start LM Studio and run the local server on `http://localhost:1234/v1`.
2. Click **Refresh Models**.
3. Select a downloaded/served model.
4. Click **Use Selected + Save**.
5. Click **Test Model**.

Saved config path:

```txt
data/llm_model_settings.json
```

## Context/No-repeat fix

Deze versie voorkomt dat oude assistant-antwoorden als volledige context worden teruggevoerd. Daardoor hoort M0N4C0 niet meer eerst een oud antwoord en daarna het nieuwe antwoord te sturen.

Nieuwe interne safeguards:
- compressed recent assistant context
- duplicate paragraph/line cleanup
- previous-answer prefix stripping
- single final answer pipeline

## External Research Commands

```txt
/research queue <onderwerp> rounds=5
/research jobs
/research cancel <id>
/learn topic <onderwerp> rounds=5
/learn expert <onderwerp>
/learn broad <onderwerp> years=2000-2026 rounds=10
```

Worker starten:

```bat
py -3.11 learning_worker.py --agents 3
```

## GUI-only runtime pages

- **Local Database**: browse/search/export SQLite memory, run safe SQL, rebuild FTS, make backups.
- **Telegram**: save token, manage allowed users, live start/stop/restart polling.
- **LLM Models**: select a normal chat model and a separate coding/programming model.
