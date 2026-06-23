from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass
from typing import Callable

from .config import Settings
from .db import MonacoDB
from .learning_planner import parse_natural_learning_intent, parse_rounds, parse_year_range
from .llm import LMStudioClient, get_system_prompt
from .memory import learn_from_message
from .personality import load_personality, build_personality_prompt
from .reasoning import ReasoningEngine
from .retrieval import RetrievalEngine
from .web_research import WebResearcher
from .website import WebsiteLearner
from .brain_nodes import BrainGraphBuilder
from .response_guard import finalize_answer
from .language import ensure_dutch_answer
from .worldclass import (
    ConversationQualityScanner, EvidenceVault, FreshnessGuard, SkillMemory, WorkflowTemplates,
    list_scheduled_jobs, project_memory_text, schedule_job, source_rules_text, summarize_knowledge_timeline,
    upsert_project_memory, upsert_source_rule,
)


HELP_TEXT = """
M0N4C0-AI commands

Gewoon praten:
Typ gewoon je vraag zonder command. Voorbeeld: wat is quantum mechanics?
Typ ook gewoon: leer alles over kunstmatige intelligentie

Basis:
/help                               Toon commands
/status                             Bot + database status
/db check                           SQLite quick_check + counts
/self audit                         Controleer omgeving, DB, LLM en kennisstatus
/self improve plan                  Maak verbeterplan op basis van errors/logs
/truth classify <vraag>              Classificeer stable/fresh/uncertain
/knowledge timeline                  Toon wanneer kennis geleerd is
/evidence vault                      Toon recente evidence/source snapshots
/source trust <domain>               Zet bron op whitelist/trust
/source block <domain>               Zet bron op blacklist/block
/project remember key: waarde        Sla project-specifieke memory op
/workflow templates                  Toon one-click workflow templates
/ask <vraag>                         Stel een vraag via lokale memory + kennis + LLM
/vraag <vraag>                       Alias voor /ask
/search <zoekvraag>                  Zoek online, sla nog niks diep op
/knowledge search <query>            Zoek in lokale kennis
/brain stats                         Toon Brain Nodes graph counts
/retrieval debug <query>             Laat zien welke chunks gevonden worden

Self-learning / externe research worker:
/learn topic <onderwerp> rounds=10    Zet expert-learning als background job in queue
/learn expert <onderwerp>             Zet max-level research job in queue
/learn broad <onderwerp> years=1995-2025 rounds=10
                                     Zet breed onderzoek met jaar/tijdslice planning in queue
/research queue <onderwerp>           Zet nieuw onderzoek in de externe worker queue
/research website <url/onderwerp>      Crawl publieke website via externe worker
/research ebooks <url/onderwerp>       Vind/lees publieke e-books/documentlinks via externe worker
/research documents <url/onderwerp>    Lees PDF/EPUB/DOCX/TXT bronnen via externe worker
/research wikipedia <onderwerp/random>  Leer gericht of random van Wikipedia
/research jobs                        Toon jobs + status
/research cancel <id>                 Stop/annuleer job
/learn offline <onderwerp>            Antwoord alleen met lokale kennis
/learn jobs                           Toon recente learning jobs

Voorbeelden zonder slash:
leer alles over elke voetbal wedstrijd tussen 1995 - 2025
word expert in databases
zoek alles uit over AI agents rounds=5

Websites:
/website learn <url>                  Leer publieke websitepagina's
/website login <url>                  Voorbereiding handmatige login-sessie
/website status                       Website profielen tonen

Memory:
/memory stats                         Memory/database stats
/memory search <query>                Zoek opgeslagen facts
/remember <tekst>                     Sla tekst op als memory fact

Telegram/terminal:
/ping                                 Test
/whoami                               Toon chat/user context
/myid                                 Toon jouw Telegram/user id context
""".strip()


@dataclass(slots=True)
class CommandContext:
    platform: str = "terminal"
    chat_id: str = "terminal"
    user_key: str | None = None
    username: str | None = None
    display_name: str | None = None


class CommandRouter:
    def __init__(self, settings: Settings, db: MonacoDB):
        self.settings = settings
        self.db = db
        self.llm = LMStudioClient(settings)
        self.activity_callback: Callable[[str, str], None] | None = None
        self.reasoning = ReasoningEngine(settings, db, self.llm)
        self.web = WebResearcher(settings, db, self.llm, activity_callback=self.log_activity)
        self.website = WebsiteLearner(settings, db)
        self.retrieval = RetrievalEngine(db)
        self.brain = BrainGraphBuilder(db)
        self.freshness_guard = FreshnessGuard()
        self.quality_scanner = ConversationQualityScanner()
        self.evidence = EvidenceVault(db)
        self.skill_memory = SkillMemory(db)

    def set_activity_callback(self, callback: Callable[[str, str], None] | None) -> None:
        self.activity_callback = callback
        if hasattr(self.web, "set_activity_callback"):
            self.web.set_activity_callback(callback)

    def log_activity(self, message: str, level: str = "INFO") -> None:
        if self.activity_callback is not None:
            try:
                self.activity_callback(message, level)
            except Exception:
                pass

    def handle(self, text: str, ctx: CommandContext | None = None) -> str:
        ctx = ctx or CommandContext()
        text = (text or "").strip()
        if not text:
            return "Stuur gewoon een vraag of typ /help voor commands."
        if ctx.user_key:
            self.log_activity(f"Upserting user profile: {ctx.platform}/{ctx.user_key}", "INFO")
            self.db.upsert_user(ctx.platform, ctx.user_key, ctx.username, ctx.display_name)
        self.log_activity("Writing user message to conversations table.", "INFO")
        self.db.add_conversation(ctx.platform, ctx.chat_id, ctx.user_key, "user", text)
        profile = load_personality(self.settings)
        if profile.toggles.get("long_term_memory", True) and profile.toggles.get("learn_from_conversations", True):
            self.log_activity("Running automatic memory extraction.", "STEP")
            learned = learn_from_message(self.db, text, ctx.user_key)
            if learned:
                self.log_activity(f"Memory learned: {len(learned)} fact(s).", "OK")
        else:
            self.log_activity("Automatic memory extraction skipped by Personality settings.", "WARN")
        previous_forced_role = getattr(self.settings, "llm_forced_model_role", "auto")
        try:
            if ctx.platform == "telegram" and previous_forced_role in {"", "auto"}:
                self.settings.llm_forced_model_role = "telegram"
            if text.startswith("/"):
                self.log_activity(f"Command mode detected: {text.split()[0]}", "STEP")
                out = self._command(text, ctx)
            else:
                self.log_activity("Natural language mode detected.", "STEP")
                out = self._natural(text, ctx)
            if out:
                previous_answers = self._recent_assistant_answers(ctx.chat_id, limit=8)
                before_len = len(out)
                out = finalize_answer(out, previous_answers)
                out = ensure_dutch_answer(text, out, self.llm)
                if len(out) != before_len:
                    self.log_activity("ResponseGuard/language guard cleaned the final answer.", "OK")
            if out:
                self.log_activity("Writing assistant response to conversations table.", "INFO")
                self.db.add_conversation(ctx.platform, ctx.chat_id, ctx.user_key, "assistant", out)
            final_out = out or "Ik kreeg geen antwoord terug. Check /status of LM Studio draait."
            self.settings.llm_forced_model_role = previous_forced_role
            return final_out
        except Exception as e:
            tb = traceback.format_exc()
            self.db.log_error("COMMAND_ERROR", str(e), tb, {"text": text, "platform": ctx.platform})
            return (
                "Er ging iets technisch mis in M0N4C0-AI, maar ik heb de fout opgeslagen in SQLite.\n"
                f"Fout: {type(e).__name__}: {e}\n"
                "Gebruik /self audit of /db check om te controleren wat er misgaat."
            )


    def _recent_assistant_answers(self, chat_id: str, limit: int = 8) -> list[str]:
        try:
            with self.db.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT content FROM conversations
                    WHERE chat_id=? AND role='assistant'
                    ORDER BY id DESC LIMIT ?
                    """,
                    (chat_id, limit),
                ).fetchall()
            return [str(r["content"] or "") for r in rows]
        except Exception:
            return []

    def _needs_fresh_web(self, text: str) -> bool:
        return self.freshness_guard.classify(text).needs_web

    def _fresh_web_answer(self, text: str) -> str:
        decision = self.freshness_guard.classify(text)
        results = self.web.search(text, max_results=6)
        if not results:
            answer = (
                "Ik wil dit niet gokken, want dit lijkt actuele informatie. "
                "Ik kon alleen geen live webresultaten ophalen. Daardoor kan ik dit niet actueel verifiëren. "
                "Check je internet/ddgs-instelling of laat de Research worker dit doen."
            )
            scanned, report = self.quality_scanner.scan(text, answer, freshness=decision, sources=[], web_checked=False)
            try:
                self.db.add_quality_report("web", text, scanned[:900], report.get("confidence", "low"), report.get("warnings", []), {"freshness": decision.label, "web_results": 0})
            except Exception:
                pass
            return scanned
        context_lines = []
        source_lines = []
        for i, item in enumerate(results, start=1):
            context_lines.append(f"[Web {i}] {item.title}\nURL: {item.url}\nSnippet: {item.snippet}")
            source_lines.append(f"[{i}] {item.title} — {item.url}")
            try:
                self.evidence.store(source_url=item.url, title=item.title, claim=text[:500], snippet=item.snippet, confidence=0.70, freshness="live_web", metadata={"rank": i})
            except Exception:
                pass
        system = (
            get_system_prompt(self.settings) + "\n" + build_personality_prompt(self.settings) + "\n"
            "Gebruik alleen deze verse webresultaten voor actuele claims. Verzin niets. "
            "Als de snippets onvoldoende zijn, zeg dat eerlijk. Antwoord in het Nederlands. "
            "Geef maximaal 1 korte reasoning/source summary, geen verborgen chain-of-thought."
        )
        result = self.llm.safe_chat(system, text, "\n\n".join(context_lines), attempts=2)
        answer = result.text or "Ik kon de webresultaten wel vinden, maar de lokale LLM gaf geen bruikbare samenvatting."
        scanned, report = self.quality_scanner.scan(text, answer, freshness=decision, sources=source_lines, web_checked=True)
        try:
            self.db.add_quality_report("web", text, scanned[:900], report.get("confidence", "medium"), report.get("warnings", []), {"freshness": decision.label, "web_results": len(results)})
        except Exception:
            pass
        if "Bronnen:" not in scanned:
            scanned = scanned.rstrip() + "\n\nBronnen:\n" + "\n".join(source_lines)
        return scanned

    def _natural(self, text: str, ctx: CommandContext) -> str:
        # Natural self-learning: user does not need /learn.
        profile = load_personality(self.settings)
        intent = parse_natural_learning_intent(text, self.settings.default_learn_rounds, self.settings.max_learn_rounds)
        if intent and profile.toggles.get("auto_research_learning_requests", True):
            depth = profile.sliders.get("learning_depth", 10.0)
            autonomy = profile.sliders.get("research_autonomy", 8.0)
            if depth >= 9 or autonomy >= 8:
                intent.rounds = max(intent.rounds, self.settings.max_learn_rounds)
            self.log_activity(f"Learning intent detected: topic='{intent.topic}', rounds={intent.rounds}, years={intent.start_year}-{intent.end_year}", "STEP")
            mode = "broad" if (intent.broad or intent.start_year is not None or intent.end_year is not None) else "topic"
            return self._enqueue_learning_job(
                topic=intent.topic,
                rounds=intent.rounds,
                mode=mode,
                ctx=ctx,
                start_year=intent.start_year,
                end_year=intent.end_year,
                priority=7,
                source="natural_language",
            )
        if intent and not profile.toggles.get("auto_research_learning_requests", True):
            self.log_activity("Learning intent detected but auto research is disabled in Personality settings.", "WARN")

        # Natural quick-search trigger.
        lower = text.lower()
        if lower.startswith(("zoek ", "zoek op ", "search ", "google ", "check online ")):
            if not profile.toggles.get("auto_web_search_fresh_topics", True):
                self.log_activity("Quick web search skipped by Personality settings.", "WARN")
                return "Online zoeken staat uit in Personality → Auto Web Search Fresh Topics."
            q = re.sub(r"^(zoek op|zoek|search|google|check online)\s+", "", text, flags=re.I).strip()
            self.log_activity(f"Quick web search requested: {q or text}", "STEP")
            return self._fresh_web_answer(q or text)

        decision = self.freshness_guard.classify(text)
        if decision.needs_web and profile.toggles.get("auto_web_search_fresh_topics", True):
            if self.settings.internet_enabled:
                self.log_activity(f"Freshness guard triggered ({decision.reason}): using live web check.", "STEP")
                return self._fresh_web_answer(text)
            self.log_activity("Freshness guard wanted web, but internet is disabled.", "WARN")

        self.log_activity(f"No learn/search trigger. Answering with retrieval + local LLM. freshness={decision.label}", "STEP")
        ans = self.reasoning.answer(text, ctx.chat_id, ctx.user_key, freshness_decision=decision)
        tech = f"\n\n[tech: {ans.technical}]" if self.settings.tech_status in {"verbose", "debug"} else ""
        return ans.text + tech

    def _command(self, text: str, ctx: CommandContext) -> str:
        raw = text[1:].strip()
        if not raw:
            return HELP_TEXT
        lower = raw.lower()
        if lower in {"help", "commands", "cmds"}:
            return HELP_TEXT
        if lower == "ping":
            return "pong ✅"
        if lower in {"whoami", "myid", "id"}:
            return (
                f"platform={ctx.platform}\nchat_id={ctx.chat_id}\nuser_key={ctx.user_key}\n"
                f"username={ctx.username}\ndisplay_name={ctx.display_name}"
            )
        if lower in {"status", "bot status"}:
            return self._status()
        if lower in {"db check", "database check"}:
            return self._db_check()
        if lower in {"brain stats", "brain nodes", "brain graph"}:
            return self._brain_stats()
        if lower in {"self audit", "doctor", "environment doctor"}:
            return self._self_audit()
        if lower in {"self improve plan", "self improvement", "improve plan"}:
            return self._self_improve_plan()
        if lower in {"workflow templates", "workflows", "missions"}:
            return "Beschikbare workflow templates:\n" + WorkflowTemplates.list_text()
        if lower.startswith("truth classify "):
            q = raw[len("truth classify "):].strip()
            d = self.freshness_guard.classify(q)
            return f"Truth/Freshness: {d.label} | web nodig={d.needs_web} | confidence={d.confidence:.2f} | reason={d.reason}"
        if lower in {"knowledge timeline", "timeline"}:
            return summarize_knowledge_timeline(self.db)
        if lower in {"evidence", "evidence vault"}:
            rows = self.evidence.list_recent(20)
            if not rows:
                return "Evidence Vault is leeg."
            return "\n".join([f"#{r['id']} conf={r['confidence']} fresh={r['freshness']} {r['title']} — {r['source_url']}" for r in rows])
        if lower in {"source rules", "sources rules", "source whitelist"}:
            return source_rules_text(self.db)
        if lower.startswith("source trust "):
            rid = upsert_source_rule(self.db, raw[len("source trust "):].strip(), "trust")
            return f"Source trust rule opgeslagen: #{rid}"
        if lower.startswith("source block "):
            rid = upsert_source_rule(self.db, raw[len("source block "):].strip(), "block")
            return f"Source block rule opgeslagen: #{rid}"
        if lower in {"scheduled jobs", "job scheduler"}:
            return list_scheduled_jobs(self.db)
        if lower.startswith("schedule job "):
            rest = raw[len("schedule job "):].strip()
            jid = schedule_job(self.db, rest or "Manual scheduled job", "manual", "manual")
            return f"Scheduled job aangemaakt: #{jid}"
        if lower in {"project memory", "workspace memory"}:
            return project_memory_text(self.db)
        if lower.startswith("project remember "):
            rest = raw[len("project remember "):].strip()
            key, value = (rest.split(":", 1) if ":" in rest else ("note", rest))
            mid = upsert_project_memory(self.db, self.settings.root.name, key.strip(), value.strip())
            return f"Project memory opgeslagen: #{mid}"
        if lower.startswith("skill remember "):
            rest = raw[len("skill remember "):].strip()
            if ":" in rest:
                key, value = rest.split(":", 1)
            else:
                key, value = "user_preference", rest
            self.skill_memory.remember(key.strip(), value.strip(), source="command", confidence=0.9)
            return "Skill memory opgeslagen ✅"
        if lower.startswith(("ask ", "vraag ")):
            q = raw.split(" ", 1)[1].strip() if " " in raw else ""
            if not q:
                return "Stel je vraag na /ask of /vraag, of typ gewoon zonder command."
            profile = load_personality(self.settings)
            decision = self.freshness_guard.classify(q)
            if decision.needs_web and profile.toggles.get("auto_web_search_fresh_topics", True) and self.settings.internet_enabled:
                return self._fresh_web_answer(q)
            ans = self.reasoning.answer(q, ctx.chat_id, ctx.user_key, freshness_decision=decision)
            tech = f"\n\n[tech: {ans.technical}]" if self.settings.tech_status in {"verbose", "debug"} else ""
            return ans.text + tech
        if lower.startswith("search "):
            return self.web.quick_search_answer(raw[7:].strip())
        if lower.startswith("learn expert "):
            topic = raw[len("learn expert "):].strip()
            return self._enqueue_learning_job(topic, self.settings.max_learn_rounds, "topic", ctx, priority=8, source="slash_learn_expert")
        if lower.startswith("learn broad "):
            rest = raw[len("learn broad "):].strip()
            sy, ey = parse_year_range(rest)
            rounds = parse_rounds(rest, self.settings.max_learn_rounds, self.settings.max_learn_rounds)
            topic = re.sub(r"\byears\s*=\s*(19\d{2}|20\d{2})\s*[-–—]\s*(19\d{2}|20\d{2})\b", "", rest, flags=re.I).strip()
            topic = re.sub(r"\b(rounds|rondes)\s*=\s*\d+\b", "", topic, flags=re.I).strip()
            return self._enqueue_learning_job(topic or rest, rounds, "broad", ctx, start_year=sy, end_year=ey, priority=8, source="slash_learn_broad")
        if lower.startswith("learn topic "):
            rest = raw[len("learn topic "):].strip()
            topic, rounds = self._parse_topic_rounds(rest)
            return self._enqueue_learning_job(topic, rounds, "topic", ctx, priority=6, source="slash_learn_topic")
        if lower in {"learn jobs", "learning jobs", "learn status", "research jobs", "research status"}:
            return self._learning_jobs()
        if lower.startswith("research cancel "):
            m = re.search(r"(\d+)", raw)
            if not m:
                return "Geef een job-id mee, bijvoorbeeld: /research cancel 42"
            ok = self.db.request_cancel_learning_job(int(m.group(1)))
            return "Cancel aangevraagd ✅" if ok else "Ik kon die job niet vinden."
        for research_mode in ("website", "ebooks", "documents", "wikipedia", "news", "competitor", "deep"):
            prefix = f"research {research_mode} "
            if lower.startswith(prefix):
                rest = raw[len(prefix):].strip()
                rounds = parse_rounds(rest, self.settings.default_learn_rounds, self.settings.max_learn_rounds)
                clean = re.sub(r"\b(rounds|rondes)\s*=\s*\d+\b", "", rest, flags=re.I).strip()
                urls = re.findall(r"https?://[^\s,;]+", clean)
                return self._enqueue_learning_job(clean or rest, rounds, research_mode, ctx, priority=7, source=f"slash_research_{research_mode}", source_urls=urls, max_depth=2 if research_mode in {"website", "ebooks"} else 1, max_pages=60 if research_mode in {"website", "ebooks"} else 20, max_files=80 if research_mode in {"ebooks", "documents"} else 20)
        if lower.startswith("research queue "):
            rest = raw[len("research queue "):].strip()
            sy, ey = parse_year_range(rest)
            rounds = parse_rounds(rest, self.settings.default_learn_rounds, self.settings.max_learn_rounds)
            topic = re.sub(r"\byears\s*=\s*(19\d{2}|20\d{2})\s*[-–—]\s*(19\d{2}|20\d{2})\b", "", rest, flags=re.I).strip()
            topic = re.sub(r"\b(rounds|rondes)\s*=\s*\d+\b", "", topic, flags=re.I).strip()
            mode = "broad" if sy or ey else "topic"
            return self._enqueue_learning_job(topic or rest, rounds, mode, ctx, start_year=sy, end_year=ey, priority=6, source="research_queue")
        if lower.startswith("learn offline "):
            q = raw[len("learn offline "):].strip()
            r = self.retrieval.retrieve(q, limit=12, max_chars=12000)
            if not r.context:
                return "Ik heb lokaal nog geen kennis hierover gevonden."
            ans = self.llm.safe_chat("Beantwoord alleen met lokale context. Geen internet.", q, r.context)
            return ans.text
        if lower.startswith("knowledge search "):
            q = raw[len("knowledge search "):].strip()
            rows = self.db.fts_search(q, limit=10)
            if not rows:
                return "Geen lokale kennis gevonden."
            lines = [f"Lokale kennisresultaten voor: {q}"]
            for i, row in enumerate(rows, start=1):
                preview = str(row["content"])[:350].replace("\n", " ")
                lines.append(f"{i}. {row['title']} | topic={row['topic']} | id={row['id']}\n   {preview}...")
            return "\n".join(lines)
        if lower.startswith("retrieval debug "):
            return self.retrieval.debug(raw[len("retrieval debug "):].strip())
        if lower.startswith("website learn "):
            return self.website.learn_public_site(raw[len("website learn "):].strip(), max_pages=25)
        if lower.startswith("website login "):
            return self.website.manual_login_note(raw[len("website login "):].strip())
        if lower == "website status":
            return self._website_status()
        if lower in {"memory stats", "knowledge stats"}:
            return self._db_check()
        if lower.startswith("memory search "):
            q = raw[len("memory search "):].strip()
            rows = self.db.search_memory(q, limit=20)
            if not rows:
                return "Geen memory facts gevonden."
            return "\n".join([f"- {r['subject']} | {r['predicate']} | {r['object']}" for r in rows])
        if lower.startswith("remember "):
            note = raw[len("remember "):].strip()
            self.db.add_memory_fact(ctx.user_key or "user", "note", note, user_key=ctx.user_key, source="manual", confidence=0.95)
            return "Onthouden ✅"

        # Slash unknown should not block normal questions. Treat /something text as a question if it looks like one.
        if "?" in raw or len(raw.split()) > 2:
            return self._natural(raw, ctx)
        return "Onbekend command. Gebruik /help. Voor normale vragen hoef je geen slash te gebruiken."

    def _enqueue_learning_job(
        self,
        topic: str,
        rounds: int,
        mode: str,
        ctx: CommandContext,
        *,
        start_year: int | None = None,
        end_year: int | None = None,
        priority: int = 5,
        source: str = "user",
        source_urls: list[str] | None = None,
        max_depth: int = 1,
        max_pages: int = 20,
        max_files: int = 20,
    ) -> str:
        topic = (topic or "").strip()
        if not topic:
            return "Geef een onderwerp mee om te onderzoeken. Bijvoorbeeld: leer alles over bedrijfsvoering."
        rounds = max(1, min(int(rounds or self.settings.default_learn_rounds), self.settings.max_learn_rounds))
        job_id = self.db.enqueue_learning_job(
            topic=topic,
            rounds=rounds,
            mode=mode,
            priority=priority,
            agent="researcher",
            chat_id=ctx.chat_id,
            user_key=ctx.user_key,
            source=source,
            start_year=start_year,
            end_year=end_year,
            metadata={"source": source, "platform": ctx.platform, "start_year": start_year, "end_year": end_year, "source_urls": source_urls or [], "max_depth": max_depth, "max_pages": max_pages, "max_files": max_files},
            source_urls=source_urls or [],
            max_depth=max_depth,
            max_pages=max_pages,
            max_files=max_files,
        )
        self.log_activity(f"Background learning job queued: #{job_id} topic={topic}", "OK")
        years = f" | jaren: {start_year}-{end_year}" if start_year or end_year else ""
        url_line = f"\nBronnen: {len(source_urls or [])} URL(s)" if source_urls else ""
        return (
            f"✅ Research job gestart in de externe learning queue.\n"
            f"Job #{job_id}\n"
            f"Onderwerp: {topic}\n"
            f"Mode: {mode} | rondes: {rounds}{years}{url_line}\n\n"
            "De bot blijft nu gewoon snel reageren. Start de worker met `START_WORKER_CMD.bat` of `py -3.11 learning_worker.py --agents 3`.\n"
            "Status bekijken kan met `/research jobs` of via de GUI-tab Research."
        )

    def _parse_topic_rounds(self, text: str) -> tuple[str, int]:
        rounds = self.settings.max_learn_rounds
        parts = text.split()
        clean_parts = []
        for p in parts:
            if p.lower().startswith(("rounds=", "rondes=")):
                try:
                    rounds = int(p.split("=", 1)[1])
                except Exception:
                    pass
            else:
                clean_parts.append(p)
        topic = " ".join(clean_parts).strip()
        return topic, max(1, min(rounds, self.settings.max_learn_rounds))

    def _status(self) -> str:
        return (
            "M0N4C0-AI status ✅\n"
            f"DB: {self.settings.db_path}\n"
            f"LLM: {self.settings.lmstudio_model}\n"
            f"LM Studio: {self.llm.health()}\n"
            f"Internet: {'aan' if self.settings.internet_enabled else 'uit'}\n"
            f"Telegram: {'aan' if self.settings.telegram_enabled else 'uit'}\n"
            "Normale berichten: aan — /ask is niet nodig"
        )

    def _db_check(self) -> str:
        stats = self.db.stats()
        lines = ["SQLite / knowledge stats"]
        for k, v in stats.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def _brain_stats(self) -> str:
        graph = self.brain.build(include_seed_if_empty=True)
        s = graph.stats
        seeded = "\n- seed: expert football + general + markets brain packs toegevoegd" if graph.seeded else ""
        return (
            "Brain Nodes status ☍\n"
            f"- nodes: {s.get('nodes', 0)}\n"
            f"- relations: {s.get('edges', 0)}\n"
            f"- knowledge chunks: {s.get('knowledge_chunks', 0)}\n"
            f"- memory facts: {s.get('memory_facts', 0)}\n"
            f"- recent conversations: {s.get('conversations', 0)}"
            f"{seeded}"
        )

    def _self_audit(self) -> str:
        stats = self.db.stats()
        lines = ["M0N4C0-AI self-audit"]
        lines.append(f"- SQLite quick_check: {stats.get('quick_check')}")
        lines.append(f"- DB path: {self.settings.db_path}")
        lines.append(f"- LLM health: {self.llm.health()}")
        lines.append(f"- Internet: {'aan' if self.settings.internet_enabled else 'uit'}")
        lines.append(f"- Knowledge chunks: {stats.get('knowledge_chunks')}")
        lines.append(f"- Conversations: {stats.get('conversations')}")
        lines.append(f"- Memory facts: {stats.get('memory_facts')}")
        lines.append(f"- Learning jobs: {stats.get('learning_jobs')}")
        lines.append(f"- Errors: {stats.get('errors')}")
        return "\n".join(lines)

    def _self_improve_plan(self) -> str:
        with self.db.connect() as conn:
            errors = conn.execute("SELECT error_type,message,created_at FROM errors ORDER BY id DESC LIMIT 12").fetchall()
        context = "\n".join([f"{e['created_at']} | {e['error_type']} | {e['message']}" for e in errors]) or "Geen errors gevonden."
        result = self.llm.safe_chat(
            "Je bent een senior Python architect. Maak een concreet verbeterplan voor M0N4C0-AI op basis van errors en status. Geen code uitvoeren, alleen plan.",
            "Maak een prioriteitenlijst met verbeteringen, tests en risico's.",
            context,
        )
        return result.text

    def _website_status(self) -> str:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM website_profiles ORDER BY updated_at DESC LIMIT 20").fetchall()
        if not rows:
            return "Nog geen websites geleerd."
        return "\n".join([f"- {r['domain']} | {r['source_type']} | pages={r['pages_seen']} | {r['root_url']}" for r in rows])

    def _learning_jobs(self) -> str:
        rows = self.db.list_learning_jobs(limit=20)
        if not rows:
            return "Nog geen learning/research jobs."
        lines = ["Research / learning jobs"]
        for r in rows:
            try:
                progress = json.loads(r["progress_json"] or "{}") if "progress_json" in r.keys() else {}
            except Exception:
                progress = {}
            phase = progress.get("phase", "-")
            pct = progress.get("percent", 0)
            mode = r["mode"] if "mode" in r.keys() else "topic"
            worker = r["worker_id"] if "worker_id" in r.keys() else None
            years = ""
            if "start_year" in r.keys() and (r["start_year"] or r["end_year"]):
                years = f" | years={r['start_year']}-{r['end_year']}"
            lines.append(
                f"- #{r['id']} | {r['status']} | {pct}% {phase} | {r['rounds_done']}/{r['rounds_requested']} | {mode} | {r['topic']}{years} | worker={worker or '-'}"
            )
        lines.append("\nWorker starten: `py -3.11 learning_worker.py --agents 3` of `START_WORKER_CMD.bat`.")
        return "\n".join(lines)
