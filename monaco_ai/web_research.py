from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .config import Settings
from .db import MonacoDB
from .llm import LMStudioClient
from .utils import chunk_text, normalize_ws, sha256_text, utc_now
from .learning_planner import build_broad_queries


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class WebResearcher:
    def __init__(self, settings: Settings, db: MonacoDB, llm: LMStudioClient, activity_callback: Callable[[str, str], None] | None = None):
        self.settings = settings
        self.db = db
        self.llm = llm
        self.activity_callback = activity_callback

    def set_activity_callback(self, callback: Callable[[str, str], None] | None) -> None:
        self.activity_callback = callback

    def log(self, message: str, level: str = "INFO") -> None:
        if self.activity_callback is not None:
            try:
                self.activity_callback(message, level)
            except Exception:
                pass


    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        if not self.settings.internet_enabled:
            self.log("Internet disabled: skipping search.", "WARN")
            return []
        self.log(f"Search query => {query} (max_results={max_results})", "STEP")
        results: list[SearchResult] = []
        # Try ddgs first.
        try:
            from ddgs import DDGS  # type: ignore
            with DDGS() as ddgs:
                for item in ddgs.text(query, max_results=max_results):
                    url = item.get("href") or item.get("url") or ""
                    if not url.startswith("http"):
                        continue
                    results.append(SearchResult(title=item.get("title", ""), url=url, snippet=item.get("body", "")))
            if results:
                self.log(f"Search returned {len(results[:max_results])} results.", "OK")
                return results[:max_results]
        except Exception as exc:
            self.log(f"Search backend failed: {type(exc).__name__}: {exc}", "WARN")
        # Fallback: no search backend.
        self.log("No search backend results available. Install/check ddgs if needed.", "WARN")
        return []

    def fetch(self, url: str, timeout: int = 20) -> tuple[str, str, int | None]:
        headers = {"User-Agent": self.settings.web_user_agent}
        self.log(f"Fetching page => {url}", "STEP")
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            status = r.status_code
            content_type = r.headers.get("content-type", "")
            if "text" not in content_type and "html" not in content_type and not r.text:
                return "", "", status
            soup = BeautifulSoup(r.text, "lxml")
            for tag in soup(["script", "style", "noscript", "svg"]):
                tag.decompose()
            title = normalize_ws(soup.title.get_text(" ") if soup.title else url)
            text = normalize_ws(soup.get_text("\n"))
            self._save_page(url, title, status, text)
            self.log(f"Fetched status={status}, chars={len(text)}, title={title[:80] or url[:80]}", "OK")
            return title, text, status
        except Exception as e:
            self.log(f"Fetch failed: {type(e).__name__}: {e}", "ERR")
            self.db.log_error("WEB_FETCH", str(e), metadata={"url": url})
            return "", "", None

    def _save_page(self, url: str, title: str, status: int | None, text: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO web_pages(url,title,status_code,fetched_at,text,metadata_json,hash)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET title=excluded.title,status_code=excluded.status_code,fetched_at=excluded.fetched_at,text=excluded.text,hash=excluded.hash
                """,
                (url, title, status, utc_now(), text, json.dumps({}, ensure_ascii=False), sha256_text(text)),
            )

    def learn_topic(self, topic: str, rounds: int = 3) -> str:
        if not self.settings.internet_enabled:
            return "Internet staat uit. Ik kan alleen lokale kennis gebruiken."
        rounds = max(1, min(rounds, self.settings.max_learn_rounds))
        with self.db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO learning_jobs(topic,rounds_requested,status,created_at,updated_at) VALUES(?,?,?,?,?)",
                (topic, rounds, "running", utc_now(), utc_now()),
            )
            job_id = int(cur.lastrowid)
        self.log(f"Learning job #{job_id} created for topic='{topic}' rounds={rounds}", "OK")
        learned_pages = 0
        learned_chunks = 0
        queries = [topic]
        notes: list[str] = []
        for round_no in range(1, rounds + 1):
            query = queries[-1]
            self.log(f"Learning round {round_no}/{rounds}: query='{query}'", "STEP")
            results = self.search(query, max_results=self.settings.max_pages_per_round)
            round_texts: list[str] = []
            for result in results:
                title, text, status = self.fetch(result.url)
                if not text or len(text) < 800:
                    continue
                source_id = self.db.add_source("web", title or result.title or result.url, result.url, topic, {"round": round_no, "snippet": result.snippet}, reliability=0.45)
                chunks = chunk_text(text, max_chars=2800, overlap=250)
                written_here = 0
                for idx, chunk in enumerate(chunks[:35]):
                    if self.db.add_chunk(source_id, topic, title or result.title, result.url, idx, chunk, quality_score=0.45):
                        learned_chunks += 1
                        written_here += 1
                self.log(f"Stored source_id={source_id}, chunks={written_here}, title={title[:70] or result.title[:70]}", "OK")
                round_texts.append((text[:5000]))
                learned_pages += 1
                time.sleep(0.2)
            summary_context = "\n\n".join(round_texts[:6])
            if summary_context:
                self.log(f"Summarizing round {round_no}: context chars={len(summary_context)}", "STEP")
                result = self.llm.safe_chat(
                    system="Je bent een research-assistent. Schrijf altijd in het Nederlands. Vat de gevonden bronnen samen, maak expert-level notities en geef 3 betere vervolgzoekvragen. Geen verzinsels.",
                    user=f"Onderwerp: {topic}\nRonde: {round_no}\nMaak in het Nederlands: samenvatting, kernconcepten, onzekerheden, vervolgzoekvragen.",
                    context=summary_context,
                )
                summary = result.text
                source_id = self.db.add_source("research_summary", f"Research summary: {topic} ronde {round_no}", None, topic, {"round": round_no}, reliability=0.55)
                self.db.add_chunk(source_id, topic, f"Research summary ronde {round_no}: {topic}", None, 0, summary, summary=summary, quality_score=0.65)
                notes.append(summary[:1000])
                self.log(f"Round {round_no} summary stored as research_summary source_id={source_id}.", "OK")
                # Extract possible next queries from LLM text.
                candidates = re.findall(r"(?:zoekvraag|query|vervolgzoekvraag)[:\- ]+(.+)", summary, flags=re.I)
                if candidates:
                    queries.append(candidates[0][:160])
                else:
                    queries.append(f"{topic} advanced concepts expert overview")
            with self.db.connect() as conn:
                conn.execute("UPDATE learning_jobs SET rounds_done=?, updated_at=? WHERE id=?", (round_no, utc_now(), job_id))
        with self.db.connect() as conn:
            conn.execute("UPDATE learning_jobs SET status=?, notes=?, updated_at=? WHERE id=?", ("done", "\n\n".join(notes), utc_now(), job_id))
        self.log(f"Learning job #{job_id} done. pages={learned_pages}, chunks={learned_chunks}", "OK")
        return f"✅ Learning klaar voor '{topic}'. Rondes: {rounds}. Pagina's geleerd: {learned_pages}. Chunks opgeslagen: {learned_chunks}. Job id: {job_id}"


    def learn_broad_topic(self, topic: str, rounds: int = 10, start_year: int | None = None, end_year: int | None = None) -> str:
        """Deep learning job for very broad requests.

        Example: "leer alles over elke voetbalwedstrijd 1995-2025".
        It creates many focused search queries (by year/time slice when possible),
        stores pages/chunks locally, and writes a research summary per phase.
        """
        if not self.settings.internet_enabled:
            return "Internet staat uit. Ik kan alleen lokale kennis gebruiken."
        rounds = max(1, min(rounds, self.settings.max_learn_rounds))
        plan_queries = build_broad_queries(topic, start_year, end_year, rounds)
        metadata = {"mode": "broad", "start_year": start_year, "end_year": end_year, "planned_queries": plan_queries}
        with self.db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO learning_jobs(topic,rounds_requested,status,notes,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (topic, rounds, "running", json.dumps(metadata, ensure_ascii=False), utc_now(), utc_now()),
            )
            job_id = int(cur.lastrowid)
        self.log(f"Broad learning job #{job_id} created for topic='{topic}' years={start_year}-{end_year} rounds={rounds}", "OK")
        self.log(f"Planning generated {len(plan_queries)} focused research queries.", "STEP")
        learned_pages = 0
        learned_chunks = 0
        query_count = 0
        notes: list[str] = []
        # Distribute queries across rounds. Broad mode can do many focused searches.
        queue = list(plan_queries)
        if not queue:
            queue = [topic]
        for round_no in range(1, rounds + 1):
            self.log(f"Broad round {round_no}/{rounds} started. queue={len(queue)}", "STEP")
            round_queries = queue[: self.settings.max_pages_per_round]
            queue = queue[self.settings.max_pages_per_round:]
            if not round_queries:
                round_queries = [f"{topic} expert details round {round_no}"]
            round_texts: list[str] = []
            for query in round_queries:
                query_count += 1
                self.log(f"Broad query {query_count}: {query}", "STEP")
                results = self.search(query, max_results=max(3, min(8, self.settings.max_pages_per_round)))
                for result in results:
                    title, text, status = self.fetch(result.url)
                    if not text or len(text) < 500:
                        continue
                    source_id = self.db.add_source(
                        "web_broad_learning",
                        title or result.title or result.url,
                        result.url,
                        topic,
                        {"round": round_no, "query": query, "snippet": result.snippet, "year_range": [start_year, end_year]},
                        reliability=0.46,
                    )
                    chunks = chunk_text(text, max_chars=2600, overlap=220)
                    written_here = 0
                    for idx, chunk in enumerate(chunks[:28]):
                        if self.db.add_chunk(source_id, topic, title or result.title, result.url, idx, chunk, quality_score=0.46):
                            learned_chunks += 1
                            written_here += 1
                    self.log(f"Broad store: source_id={source_id}, chunks={written_here}, title={title[:70] or result.title[:70]}", "OK")
                    round_texts.append(text[:4500])
                    learned_pages += 1
                    time.sleep(0.15)
            summary_context = "\n\n".join(round_texts[:8])
            if summary_context:
                self.log(f"Broad round {round_no}: summarizing {len(round_texts)} pages, context chars={len(summary_context)}", "STEP")
                result = self.llm.safe_chat(
                    system=(
                        "Je bent een expert research-engine. Maak compacte maar rijke expert-notities. "
                        "Bewaar feiten, patronen, tijdlijn, bronnen, onzekerheden en vervolgzoekvragen. Geen verzinsels."
                    ),
                    user=(
                        f"Onderwerp: {topic}\nRonde: {round_no}/{rounds}\n"
                        f"Jaarbereik: {start_year or 'n.v.t.'}-{end_year or 'n.v.t.'}\n"
                        "Maak expert-notities + kernfeiten + ontbrekende data + 5 vervolgzoekvragen."
                    ),
                    context=summary_context,
                )
                summary = result.text
                source_id = self.db.add_source(
                    "broad_research_summary",
                    f"Broad research summary: {topic} ronde {round_no}",
                    None,
                    topic,
                    {"round": round_no, "job_id": job_id, "query_count": query_count},
                    reliability=0.58,
                )
                self.db.add_chunk(source_id, topic, f"Broad research summary ronde {round_no}: {topic}", None, 0, summary, summary=summary, quality_score=0.68)
                notes.append(summary[:1500])
                self.log(f"Broad summary stored for round {round_no}, source_id={source_id}.", "OK")
                # Add follow-up queries generated by model, but keep queue bounded.
                candidates = re.findall(r"(?:zoekvraag|query|vervolgzoekvraag)[:\- ]+(.+)", summary, flags=re.I)
                for c in candidates[:5]:
                    c = normalize_ws(c)[:180]
                    if c and c.lower() not in {x.lower() for x in queue}:
                        queue.append(c)
            with self.db.connect() as conn:
                conn.execute("UPDATE learning_jobs SET rounds_done=?, updated_at=? WHERE id=?", (round_no, utc_now(), job_id))
        final_note = json.dumps({"metadata": metadata, "notes_preview": notes[:5]}, ensure_ascii=False)
        with self.db.connect() as conn:
            conn.execute("UPDATE learning_jobs SET status=?, notes=?, updated_at=? WHERE id=?", ("done", final_note, utc_now(), job_id))
        self.log(f"Broad learning job #{job_id} done. queries={query_count}, pages={learned_pages}, chunks={learned_chunks}", "OK")
        return (
            f"✅ Breed self-learning klaar voor '{topic}'.\n"
            f"Rondes: {rounds}. Zoekopdrachten: {query_count}. Pagina's geleerd: {learned_pages}. "
            f"Chunks opgeslagen: {learned_chunks}. Job id: {job_id}\n"
            "Alle kennis staat lokaal in SQLite en is via /knowledge search en normale vragen terug te vinden."
        )

    def quick_search_answer(self, query: str) -> str:
        results = self.search(query, max_results=5)
        if not results:
            return "Geen webresultaten gevonden of internet/search backend is niet beschikbaar."
        lines = [f"Zoekresultaten voor: {query}"]
        for i, r in enumerate(results, start=1):
            lines.append(f"{i}. {r.title}\n   {r.url}\n   {r.snippet}")
        return "\n".join(lines)
