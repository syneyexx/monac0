from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .db import MonacoDB
from .learning_planner import build_broad_queries
from .llm import LMStudioClient
from .utils import chunk_text, normalize_ws, utc_now
from .web_research import WebResearcher
from .document_ingest import discover_links, fetch_and_extract, is_document_url, is_ebook_url, document_link_score
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup


@dataclass(slots=True)
class WorkerStats:
    worker_id: str
    jobs_done: int = 0
    jobs_failed: int = 0
    pages: int = 0
    chunks: int = 0


class ExternalLearningWorker:
    """Background learning worker for M0N4C0.

    The GUI/Telegram bot only enqueues jobs in SQLite. This worker runs as a
    separate process and claims jobs from the DB. That keeps chat fast while
    research, fetching, chunking and summaries happen in the background.
    """

    def __init__(
        self,
        settings: Settings,
        db: MonacoDB,
        *,
        agent_count: int = 2,
        poll_interval: float = 2.0,
        max_pages_per_query: int | None = None,
        low_llm_mode: bool = False,
    ) -> None:
        self.settings = settings
        self.db = db
        self.agent_count = max(1, min(int(agent_count or 1), 8))
        self.poll_interval = max(0.5, float(poll_interval or 2.0))
        self.max_pages_per_query = max_pages_per_query or settings.max_pages_per_round
        self.low_llm_mode = low_llm_mode
        self.stop_event = threading.Event()
        self.worker_group = f"worker-{os.getpid()}"
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        resumed = 0
        try:
            resumed = self.db.requeue_interrupted_learning_jobs()
        except Exception as exc:
            self.log(None, "WARN", f"Could not requeue interrupted jobs: {type(exc).__name__}: {exc}")
        self.log(None, "OK", f"External learning worker started with {self.agent_count} agent(s). Resumed jobs={resumed}.")
        for idx in range(1, self.agent_count + 1):
            thread = threading.Thread(target=self._agent_loop, args=(idx,), daemon=True)
            thread.start()
            self.threads.append(thread)

    def run_forever(self) -> None:
        self.start()
        try:
            while not self.stop_event.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.stop_event.set()
            self.log(None, "WARN", "External learning worker stopping by keyboard interrupt.")
        finally:
            for thread in self.threads:
                thread.join(timeout=2.0)
            self.log(None, "WARN", "External learning worker stopped.")

    def log(self, job_id: int | None, level: str, message: str, worker_id: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        wid = worker_id or self.worker_group
        print(f"[{utc_now()}] [{level.upper()}] [{wid}] {message}", flush=True)
        try:
            self.db.log_learning_event(job_id, wid, level, message, metadata=metadata)
        except Exception:
            pass

    def _agent_loop(self, idx: int) -> None:
        worker_id = f"{self.worker_group}-agent-{idx}"
        llm = LMStudioClient(self.settings)
        researcher = WebResearcher(self.settings, self.db, llm, activity_callback=lambda msg, level="INFO": self.log(None, level, str(msg), worker_id))
        self.log(None, "OK", "Agent online and waiting for jobs.", worker_id)
        while not self.stop_event.is_set():
            try:
                job = self.db.claim_next_learning_job(worker_id)
                if not job:
                    time.sleep(self.poll_interval)
                    continue
                self._run_job(job, researcher, worker_id)
            except Exception as exc:
                self.log(None, "ERR", f"Agent loop error: {type(exc).__name__}: {exc}", worker_id)
                time.sleep(self.poll_interval)

    def _run_job(self, job: Any, researcher: WebResearcher, worker_id: str) -> None:
        job_id = int(job["id"])
        topic = str(job["topic"])
        mode = str(job["mode"] or "topic") if "mode" in job.keys() else "topic"
        rounds = max(1, min(int(job["rounds_requested"] or 1), self.settings.max_learn_rounds))
        start_year = job["start_year"] if "start_year" in job.keys() else None
        end_year = job["end_year"] if "end_year" in job.keys() else None
        researcher.set_activity_callback(lambda msg, level="INFO": self.log(job_id, level, str(msg), worker_id))
        self.log(job_id, "STEP", f"Starting job #{job_id}: mode={mode}, topic={topic}, rounds={rounds}", worker_id)
        try:
            if mode in {"website", "ebooks", "documents"}:
                result = self._run_source_job(job, job_id, topic, rounds, mode, researcher, worker_id)
            elif mode == "wikipedia":
                result = self._run_wikipedia_job(job, job_id, topic, rounds, researcher, worker_id)
            elif mode in {"deep", "competitor", "news"}:
                result = self._run_broad_job(job_id, self._mode_prefixed_topic(mode, topic), rounds, start_year, end_year, researcher, worker_id)
            elif mode == "broad" or start_year or end_year:
                result = self._run_broad_job(job_id, topic, rounds, start_year, end_year, researcher, worker_id)
            else:
                result = self._run_topic_job(job_id, topic, rounds, researcher, worker_id)
            self.db.update_learning_job(
                job_id,
                status="done",
                notes=result.get("notes", ""),
                progress={"phase": "done", "percent": 100, **result},
                finished=True,
            )
            self.log(job_id, "OK", f"Job #{job_id} complete: pages={result.get('pages', 0)}, chunks={result.get('chunks', 0)}", worker_id, result)
        except CancelledJob:
            self.db.update_learning_job(job_id, status="cancelled", progress={"phase": "cancelled", "percent": 100}, finished=True)
            self.log(job_id, "WARN", f"Job #{job_id} cancelled.", worker_id)
        except Exception as exc:
            self.db.update_learning_job(
                job_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                progress={"phase": "failed", "percent": 100},
                finished=True,
            )
            self.log(job_id, "ERR", f"Job #{job_id} failed: {type(exc).__name__}: {exc}", worker_id)

    def _check_cancelled(self, job_id: int) -> None:
        row = self.db.get_learning_job(job_id)
        if row and int(row["cancel_requested"] or 0):
            raise CancelledJob()

    def _update_progress(self, job_id: int, round_no: int, rounds: int, phase: str, **extra: Any) -> None:
        percent = int(min(99, max(1, (round_no - 1) / max(1, rounds) * 100)))
        if phase.startswith("summar"):
            percent = int(min(99, max(percent, round_no / max(1, rounds) * 100 - 3)))
        self.db.update_learning_job(job_id, rounds_done=max(0, round_no - 1), progress={"phase": phase, "percent": percent, **extra})

    def _job_metadata(self, job: Any) -> dict[str, Any]:
        raw = ""
        try:
            raw = str(job["notes"] or "")
            data = json.loads(raw) if raw else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _job_source_urls(self, job: Any, topic: str) -> list[str]:
        urls: list[str] = []
        try:
            raw = job["source_urls_json"] if "source_urls_json" in job.keys() else "[]"
            data = json.loads(raw or "[]")
            if isinstance(data, list):
                urls.extend(str(u).strip() for u in data if str(u).strip())
        except Exception:
            pass
        meta = self._job_metadata(job)
        for key in ("source_urls", "urls", "url"):
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                urls.append(value.strip())
            elif isinstance(value, list):
                urls.extend(str(u).strip() for u in value if str(u).strip())
        for token in str(topic).split():
            if token.startswith(("http://", "https://")):
                urls.append(token.strip().rstrip(",.;"))
        clean: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            if url not in seen:
                seen.add(url)
                clean.append(url)
        return clean

    def _mode_prefixed_topic(self, mode: str, topic: str) -> str:
        if mode == "news":
            return f"actueel nieuws betrouwbare bronnen {topic}"
        if mode == "competitor":
            return f"concurrentieanalyse bedrijf markt prijzen diensten SEO {topic}"
        if mode == "deep":
            return f"deep research expert bronnen overzicht {topic}"
        return topic

    def _fetch_html_links(self, url: str, same_domain_only: bool = True) -> tuple[str, str, list[str]]:
        headers = {"User-Agent": self.settings.web_user_agent}
        r = requests.get(url, headers=headers, timeout=25)
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype.lower() and not url.lower().endswith((".html", ".htm", "/")):
            return url, "", []
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        title = normalize_ws(soup.title.get_text(" ") if soup.title else url)
        text = normalize_ws(soup.get_text("\n"))
        return title, text, discover_links(r.text, url, same_domain_only=same_domain_only)

    def _store_extracted_document(self, job_id: int, topic: str, mode: str, worker_id: str, doc: Any, *, reliability: float = 0.58) -> tuple[int, int]:
        """Store one extracted document safely and return (source_id, chunks_written)."""
        if not getattr(doc, "text", None) or len(str(doc.text)) < 80:
            return 0, 0
        source_id = self.db.add_source(
            f"worker_{mode}_document",
            doc.title,
            doc.url,
            topic,
            {"job_id": job_id, "worker": worker_id, "content_type": doc.content_type, "bytes": doc.bytes_len, "ingest_kind": "document_only"},
            reliability=reliability,
        )
        written = 0
        for idx, chunk in enumerate(chunk_text(doc.text, max_chars=2600, overlap=220)[:90]):
            if self.db.add_chunk(source_id, topic, doc.title, doc.url, idx, chunk, quality_score=min(0.82, reliability + 0.08)):
                written += 1
        return source_id, written

    def _rank_links_for_mode(self, links: list[str], mode: str, max_files: int) -> tuple[list[str], list[str]]:
        doc_links = [l for l in links if is_document_url(l)]
        page_links = [l for l in links if not is_document_url(l)]
        doc_links = sorted(doc_links, key=lambda u: document_link_score(u), reverse=True)
        if mode == "ebooks":
            # E-book mode scans HTML as a discovery layer only. It never stores
            # the HTML body, and it prefers real e-book/document URLs first.
            return doc_links[:max_files], page_links
        return doc_links, page_links

    def _run_source_job(self, job: Any, job_id: int, topic: str, rounds: int, mode: str, researcher: WebResearcher, worker_id: str) -> dict[str, Any]:
        """Crawl website/document sources with duplicate protection and resume checkpoints.

        Every discovered URL is stored in research_job_items. If the worker/app
        stops, the job is requeued on next worker startup and only unfinished
        items continue. Document URLs are checked against the document registry
        before download; after download, content/text hashes prevent duplicate
        storage even when the same PDF appears under another URL.
        """
        urls = self._job_source_urls(job, topic)
        if not urls:
            search_topic = topic if mode != "ebooks" else f"{topic} ebooks pdf epub download public domain"
            urls = [r.url for r in researcher.search(search_topic, max_results=max(3, min(8, self.max_pages_per_query)))]

        max_depth = int(job["max_depth"] if "max_depth" in job.keys() and job["max_depth"] is not None else 1)
        max_pages = int(job["max_pages"] if "max_pages" in job.keys() and job["max_pages"] is not None else 20)
        max_files = int(job["max_files"] if "max_files" in job.keys() and job["max_files"] is not None else 20)
        if mode == "ebooks":
            max_depth = max(1, max_depth)
            discovery_page_limit = max(1, max_pages)
            store_html_pages = False
        else:
            discovery_page_limit = max_pages
            store_html_pages = mode == "website"

        # Seed checkpoint table. Existing done/skipped items are preserved, so a
        # resumed job does not start from zero.
        for u in urls:
            item_type = "document" if is_document_url(u) else "page"
            priority = 1000 if item_type == "document" else 10
            self.db.register_research_item(job_id, u, item_type=item_type, depth=0, priority=priority, metadata={"seed": True, "mode": mode})

        scanned_pages = 0
        stored_pages = 0
        learned_files = 0
        learned_chunks = 0
        skipped_duplicates = 0
        notes: list[str] = []
        iterations = 0
        max_iterations = max(100, (discovery_page_limit + max_files) * 8)

        while iterations < max_iterations:
            self._check_cancelled(job_id)
            counts = self.db.count_research_items(job_id)
            if learned_files >= max_files and scanned_pages >= discovery_page_limit:
                break
            item = self.db.next_research_item(job_id)
            if item is None:
                break
            iterations += 1
            item_id = int(item["id"])
            url = str(item["url"])
            depth = int(item["depth"] or 0)
            item_type = str(item["item_type"] or ("document" if is_document_url(url) else "page"))
            self._update_progress(
                job_id,
                min(rounds, scanned_pages + learned_files + 1),
                max(rounds, 1),
                f"crawling_{mode}",
                url=url,
                depth=depth,
                files=learned_files,
                scanned_pages=scanned_pages,
                checkpoint_counts=counts,
            )

            try:
                if item_type == "document" or is_document_url(url):
                    if learned_files >= max_files:
                        self.db.update_research_item(item_id, "skipped", metadata={"reason": "max_files_reached", "max_files": max_files})
                        continue
                    if mode == "ebooks" and not (is_ebook_url(url) or document_link_score(url) >= 100):
                        self.db.update_research_item(item_id, "skipped", metadata={"reason": "not_ebook_document"})
                        continue

                    # URL-level pre-download dedupe. This saves time/storage for
                    # repeated local/XAMPP ebook crawls.
                    existing_url = self.db.get_document_registry_by_url(url)
                    if existing_url and str(existing_url["status"] or "") == "processed":
                        skipped_duplicates += 1
                        self.db.update_research_item(
                            item_id,
                            "skipped",
                            source_id=int(existing_url["source_id"] or 0) if existing_url["source_id"] else None,
                            content_hash=existing_url["content_hash"],
                            text_hash=existing_url["text_hash"],
                            bytes_len=int(existing_url["bytes_len"] or 0),
                            metadata={"reason": "url_already_processed", "source_id": existing_url["source_id"]},
                        )
                        self.log(job_id, "INFO", f"SKIPPED duplicate document URL: {url}", worker_id)
                        continue

                    doc = fetch_and_extract(self.settings, url)
                    existing_hash = self.db.get_document_registry_by_hash(doc.content_hash, doc.text_hash)
                    if existing_hash:
                        skipped_duplicates += 1
                        # Register this URL too, so the next run can skip before download.
                        if existing_hash["source_id"]:
                            self.db.mark_document_processed(
                                url,
                                title=doc.title,
                                topic=topic,
                                source_id=int(existing_hash["source_id"]),
                                content_hash=doc.content_hash,
                                text_hash=doc.text_hash,
                                bytes_len=doc.bytes_len,
                                content_type=doc.content_type,
                                metadata={"duplicate_of": existing_hash["url"], "job_id": job_id, "worker": worker_id},
                            )
                        self.db.update_research_item(
                            item_id,
                            "skipped",
                            source_id=int(existing_hash["source_id"] or 0) if existing_hash["source_id"] else None,
                            content_hash=doc.content_hash,
                            text_hash=doc.text_hash,
                            bytes_len=doc.bytes_len,
                            metadata={"reason": "content_hash_duplicate", "duplicate_of": existing_hash["url"]},
                        )
                        self.log(job_id, "INFO", f"SKIPPED duplicate document hash: {doc.title[:90]} | duplicate_of={existing_hash['url']}", worker_id)
                        continue

                    source_id, written = self._store_extracted_document(job_id, topic, mode, worker_id, doc, reliability=0.62 if mode == "ebooks" else 0.56)
                    if source_id and written:
                        learned_chunks += written
                        learned_files += 1
                        self.db.mark_document_processed(
                            url,
                            title=doc.title,
                            topic=topic,
                            source_id=source_id,
                            content_hash=doc.content_hash,
                            text_hash=doc.text_hash,
                            bytes_len=doc.bytes_len,
                            content_type=doc.content_type,
                            metadata={"job_id": job_id, "worker": worker_id, "mode": mode, "chunks": written},
                        )
                        self.db.update_research_item(item_id, "done", source_id=source_id, content_hash=doc.content_hash, text_hash=doc.text_hash, bytes_len=doc.bytes_len, metadata={"chunks": written, "title": doc.title})
                        self.log(job_id, "OK", f"Stored document: chunks={written}, sha={doc.content_hash[:12]}, title={doc.title[:90]}", worker_id)
                        notes.append(f"Document: {doc.title} ({written} chunks)")
                    else:
                        self.db.update_research_item(item_id, "skipped", content_hash=doc.content_hash, text_hash=doc.text_hash, bytes_len=doc.bytes_len, metadata={"reason": "no_extractable_text", "title": doc.title})
                        self.log(job_id, "WARN", f"Skipped document without usable text: {url}", worker_id)
                    time.sleep(0.05)
                    continue

                # HTML/page discovery.
                if scanned_pages >= discovery_page_limit:
                    self.db.update_research_item(item_id, "skipped", metadata={"reason": "max_discovery_pages_reached"})
                    continue
                title, text, links = self._fetch_html_links(url, same_domain_only=True)
                scanned_pages += 1

                if store_html_pages and text and len(text) > 350 and stored_pages < max_pages:
                    source_id = self.db.add_source(
                        f"worker_{mode}_page",
                        title or url,
                        url,
                        topic,
                        {"job_id": job_id, "worker": worker_id, "depth": depth, "note": "website page stored intentionally"},
                        reliability=0.50,
                    )
                    written = 0
                    for idx, chunk in enumerate(chunk_text(text, max_chars=2600, overlap=220)[:35]):
                        if self.db.add_chunk(source_id, topic, title or url, url, idx, chunk, quality_score=0.50):
                            learned_chunks += 1
                            written += 1
                    stored_pages += 1
                    self.db.update_research_item(item_id, "done", source_id=source_id, metadata={"chunks": written, "title": title or url})
                    self.log(job_id, "OK", f"Stored website page: chunks={written}, title={normalize_ws(title)[:90]}", worker_id)
                    notes.append(f"Page: {title or url} ({written} chunks)")
                else:
                    self.db.update_research_item(item_id, "done", metadata={"title": title or url, "links_found": len(links), "stored": False})
                    if mode == "ebooks":
                        self.log(job_id, "STEP", f"Scanned ebook index page only, not stored: {normalize_ws(title or url)[:90]} | links={len(links)}", worker_id)

                if depth < max_depth and links:
                    doc_links, page_links = self._rank_links_for_mode(links, mode, max_files=max_files)
                    for link in doc_links:
                        self.db.register_research_item(
                            job_id,
                            link,
                            item_type="document",
                            depth=depth + 1,
                            priority=1000 + document_link_score(link),
                            metadata={"discovered_from": url, "mode": mode},
                        )
                    # Keep page discovery bounded and lower priority. In ebooks mode
                    # these pages are only crawled to discover actual documents.
                    current_counts = self.db.count_research_items(job_id)
                    pending_pages_budget = max(0, discovery_page_limit * 2 - current_counts.get("pending", 0) - current_counts.get("processing", 0))
                    for link in page_links[:pending_pages_budget]:
                        self.db.register_research_item(
                            job_id,
                            link,
                            item_type="page",
                            depth=depth + 1,
                            priority=max(1, document_link_score(link) // 4),
                            metadata={"discovered_from": url, "mode": mode},
                        )
            except Exception as exc:
                self.log(job_id, "ERR", f"Source ingest failed: {type(exc).__name__}: {exc} url={url}", worker_id)
                self.db.update_research_item(item_id, "failed", error=f"{type(exc).__name__}: {exc}", metadata={"url": url, "mode": mode})
                self.db.log_error("SOURCE_INGEST", f"{type(exc).__name__}: {exc}", metadata={"url": url, "job_id": job_id, "mode": mode})
            time.sleep(0.05)

        if notes and not self.low_llm_mode:
            context = "\n".join(notes[:60])
            summary = self._summarize_round(researcher, topic, 1, 1, None, None, [context])
            sid = self.db.add_source(f"worker_{mode}_summary", f"{mode.title()} ingest summary: {topic}", None, topic, {"job_id": job_id, "worker": worker_id}, reliability=0.66)
            self.db.add_chunk(sid, topic, f"{mode.title()} summary: {topic}", None, 0, summary, summary=summary, quality_score=0.74)

        final_counts = self.db.count_research_items(job_id)
        return {
            "pages": stored_pages,
            "pages_scanned": scanned_pages,
            "files": learned_files,
            "chunks": learned_chunks,
            "skipped_duplicates": skipped_duplicates,
            "checkpoint_counts": final_counts,
            "notes": "\n".join(notes[:100]),
        }

    def _run_wikipedia_job(self, job: Any, job_id: int, topic: str, rounds: int, researcher: WebResearcher, worker_id: str) -> dict[str, Any]:
        """Learn from Wikipedia. Empty/general topics use random pages."""
        base = "https://en.wikipedia.org/w/api.php"
        learned_pages = 0
        learned_chunks = 0
        notes: list[str] = []
        query = normalize_ws(topic or "")
        generic = not query or query.lower() in {"wikipedia", "random", "general", "algemeen", "random wikipedia"}
        for round_no in range(1, rounds + 1):
            self._check_cancelled(job_id)
            self._update_progress(job_id, round_no, rounds, "wikipedia_fetch", query=query or "random")
            try:
                if generic:
                    data = requests.get(base, params={"action": "query", "format": "json", "generator": "random", "grnnamespace": 0, "grnlimit": 5, "prop": "extracts|info", "explaintext": 1, "exintro": 0, "inprop": "url"}, headers={"User-Agent": self.settings.web_user_agent}, timeout=25).json()
                    pages = list((data.get("query", {}) or {}).get("pages", {}).values())
                else:
                    search = requests.get(base, params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 5}, headers={"User-Agent": self.settings.web_user_agent}, timeout=25).json()
                    titles = [r.get("title") for r in ((search.get("query", {}) or {}).get("search", []) or []) if r.get("title")]
                    if not titles:
                        titles = [query]
                    data = requests.get(base, params={"action": "query", "format": "json", "titles": "|".join(titles[:5]), "prop": "extracts|info", "explaintext": 1, "exintro": 0, "inprop": "url"}, headers={"User-Agent": self.settings.web_user_agent}, timeout=25).json()
                    pages = list((data.get("query", {}) or {}).get("pages", {}).values())
                round_texts: list[str] = []
                for page in pages[:5]:
                    title = normalize_ws(str(page.get("title") or "Wikipedia"))
                    extract = normalize_ws(str(page.get("extract") or ""))
                    url = str(page.get("fullurl") or f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}")
                    if len(extract) < 350:
                        continue
                    source_id = self.db.add_source("worker_wikipedia", title, url, query or "random wikipedia", {"job_id": job_id, "round": round_no, "worker": worker_id, "random": generic}, reliability=0.72)
                    written = 0
                    for idx, chunk in enumerate(chunk_text(extract, max_chars=2600, overlap=220)[:30]):
                        if self.db.add_chunk(source_id, query or "random wikipedia", title, url, idx, chunk, quality_score=0.72):
                            learned_chunks += 1
                            written += 1
                    learned_pages += 1
                    round_texts.append(extract[:4200])
                    notes.append(f"Wikipedia: {title} ({written} chunks)")
                    self.log(job_id, "OK", f"Wikipedia stored: {title} chunks={written}", worker_id)
                if round_texts and not self.low_llm_mode:
                    summary = self._summarize_round(researcher, query or "random wikipedia", round_no, rounds, None, None, round_texts)
                    sid = self.db.add_source("worker_wikipedia_summary", f"Wikipedia learning summary ronde {round_no}: {query or 'random'}", None, query or "random wikipedia", {"job_id": job_id, "round": round_no}, reliability=0.76)
                    self.db.add_chunk(sid, query or "random wikipedia", f"Wikipedia summary ronde {round_no}", None, 0, summary, summary=summary, quality_score=0.80)
                    notes.append(summary[:1000])
            except Exception as exc:
                self.log(job_id, "ERR", f"Wikipedia learning failed: {type(exc).__name__}: {exc}", worker_id)
                self.db.log_error("WIKIPEDIA_LEARNING", f"{type(exc).__name__}: {exc}", metadata={"job_id": job_id, "topic": topic})
            self.db.update_learning_job(job_id, rounds_done=round_no, progress={"phase": "wikipedia_round_done", "percent": int(round_no / rounds * 100), "pages": learned_pages, "chunks": learned_chunks})
        return {"pages": learned_pages, "chunks": learned_chunks, "notes": "\n\n".join(notes[:20])}

    def _run_topic_job(self, job_id: int, topic: str, rounds: int, researcher: WebResearcher, worker_id: str) -> dict[str, Any]:
        learned_pages = 0
        learned_chunks = 0
        queries = [topic]
        notes: list[str] = []
        for round_no in range(1, rounds + 1):
            self._check_cancelled(job_id)
            query = queries[-1] if queries else topic
            self._update_progress(job_id, round_no, rounds, "searching", query=query)
            self.log(job_id, "STEP", f"Round {round_no}/{rounds} search: {query}", worker_id)
            results = researcher.search(query, max_results=self.max_pages_per_query)
            round_texts: list[str] = []
            for result in results:
                self._check_cancelled(job_id)
                title, text, status = researcher.fetch(result.url)
                if not text or len(text) < 600:
                    continue
                source_id = self.db.add_source(
                    "worker_web_learning",
                    title or result.title or result.url,
                    result.url,
                    topic,
                    {"job_id": job_id, "round": round_no, "query": query, "snippet": result.snippet, "worker": worker_id},
                    reliability=0.47,
                )
                chunks = chunk_text(text, max_chars=2600, overlap=220)
                written_here = 0
                for idx, chunk in enumerate(chunks[:30]):
                    if self.db.add_chunk(source_id, topic, title or result.title, result.url, idx, chunk, quality_score=0.47):
                        learned_chunks += 1
                        written_here += 1
                learned_pages += 1
                round_texts.append(text[:4500])
                self.log(job_id, "OK", f"Stored source={source_id}, chunks={written_here}, title={normalize_ws(title or result.title)[:80]}", worker_id)
                time.sleep(0.1)
            if round_texts and not self.low_llm_mode:
                self._check_cancelled(job_id)
                self._update_progress(job_id, round_no, rounds, "summarizing", pages=len(round_texts))
                summary = self._summarize_round(researcher, topic, round_no, rounds, None, None, round_texts)
                source_id = self.db.add_source(
                    "worker_research_summary",
                    f"Worker research summary: {topic} ronde {round_no}",
                    None,
                    topic,
                    {"job_id": job_id, "round": round_no, "worker": worker_id},
                    reliability=0.60,
                )
                self.db.add_chunk(source_id, topic, f"Worker summary ronde {round_no}: {topic}", None, 0, summary, summary=summary, quality_score=0.70)
                notes.append(summary[:1400])
                for c in self._extract_followup_queries(summary):
                    if c.lower() not in {q.lower() for q in queries}:
                        queries.append(c)
                        break
            self.db.update_learning_job(job_id, rounds_done=round_no, progress={"phase": "round_done", "percent": int(round_no / rounds * 100), "pages": learned_pages, "chunks": learned_chunks})
        return {"pages": learned_pages, "chunks": learned_chunks, "notes": "\n\n".join(notes[:10])}

    def _run_broad_job(self, job_id: int, topic: str, rounds: int, start_year: int | None, end_year: int | None, researcher: WebResearcher, worker_id: str) -> dict[str, Any]:
        learned_pages = 0
        learned_chunks = 0
        query_count = 0
        queue = build_broad_queries(topic, start_year, end_year, rounds) or [topic]
        notes: list[str] = []
        for round_no in range(1, rounds + 1):
            self._check_cancelled(job_id)
            self.log(job_id, "STEP", f"Broad round {round_no}/{rounds}; query queue={len(queue)}", worker_id)
            round_queries = queue[: max(1, min(self.max_pages_per_query, len(queue)))] or [f"{topic} expert overzicht ronde {round_no}"]
            queue = queue[len(round_queries):]
            round_texts: list[str] = []
            for query in round_queries:
                self._check_cancelled(job_id)
                query_count += 1
                self._update_progress(job_id, round_no, rounds, "searching_broad", query=query, query_count=query_count)
                self.log(job_id, "STEP", f"Broad query {query_count}: {query}", worker_id)
                results = researcher.search(query, max_results=max(3, min(8, self.max_pages_per_query)))
                for result in results:
                    self._check_cancelled(job_id)
                    title, text, status = researcher.fetch(result.url)
                    if not text or len(text) < 500:
                        continue
                    source_id = self.db.add_source(
                        "worker_broad_learning",
                        title or result.title or result.url,
                        result.url,
                        topic,
                        {"job_id": job_id, "round": round_no, "query": query, "year_range": [start_year, end_year], "worker": worker_id},
                        reliability=0.47,
                    )
                    chunks = chunk_text(text, max_chars=2600, overlap=220)
                    written_here = 0
                    for idx, chunk in enumerate(chunks[:24]):
                        if self.db.add_chunk(source_id, topic, title or result.title, result.url, idx, chunk, quality_score=0.47):
                            learned_chunks += 1
                            written_here += 1
                    learned_pages += 1
                    round_texts.append(text[:4200])
                    self.log(job_id, "OK", f"Broad store: source={source_id}, chunks={written_here}, title={normalize_ws(title or result.title)[:80]}", worker_id)
                    time.sleep(0.1)
            if round_texts and not self.low_llm_mode:
                self._check_cancelled(job_id)
                self._update_progress(job_id, round_no, rounds, "summarizing_broad", pages=len(round_texts))
                summary = self._summarize_round(researcher, topic, round_no, rounds, start_year, end_year, round_texts)
                source_id = self.db.add_source(
                    "worker_broad_summary",
                    f"Worker broad summary: {topic} ronde {round_no}",
                    None,
                    topic,
                    {"job_id": job_id, "round": round_no, "query_count": query_count, "worker": worker_id},
                    reliability=0.62,
                )
                self.db.add_chunk(source_id, topic, f"Worker broad summary ronde {round_no}: {topic}", None, 0, summary, summary=summary, quality_score=0.72)
                notes.append(summary[:1600])
                for c in self._extract_followup_queries(summary)[:5]:
                    if c.lower() not in {q.lower() for q in queue}:
                        queue.append(c)
            self.db.update_learning_job(job_id, rounds_done=round_no, progress={"phase": "round_done", "percent": int(round_no / rounds * 100), "pages": learned_pages, "chunks": learned_chunks, "queries": query_count})
        return {"pages": learned_pages, "chunks": learned_chunks, "queries": query_count, "notes": "\n\n".join(notes[:10])}

    def _summarize_round(self, researcher: WebResearcher, topic: str, round_no: int, rounds: int, start_year: int | None, end_year: int | None, texts: list[str]) -> str:
        context = "\n\n".join(texts[:8])
        result = researcher.llm.safe_chat(
            system=(
                "Je bent de externe research-worker van M0N4C0. Schrijf altijd in helder Nederlands. "
                "Maak compacte maar rijke expert-notities. Scheid feiten, patronen, tijdlijn, risico's, onzekerheden, fact-check status, bronconflicten en vervolgzoekvragen. Geen verzinsels."
            ),
            user=(
                f"Onderwerp: {topic}\nRonde: {round_no}/{rounds}\n"
                f"Jaarbereik: {start_year or 'n.v.t.'}-{end_year or 'n.v.t.'}\n"
                "Maak expert-notities, kernfeiten, relaties met bestaande kennis, minimaal 5 open vragen die nog beantwoord moeten worden, 5 concrete vervolgzoekvragen en een korte fact-check lijst. Geef bij twijfel aan wat opnieuw gezocht moet worden."
            ),
            context=context,
            attempts=2,
        )
        return result.text or f"Samenvatting niet beschikbaar voor ronde {round_no}; ruwe bronnen zijn wel opgeslagen."

    def _extract_followup_queries(self, summary: str) -> list[str]:
        candidates = []
        for line in (summary or "").splitlines():
            line = normalize_ws(line)
            if not line:
                continue
            m = __import__('re').search(r"(?:zoekvraag|query|vervolgzoekvraag|open vraag|vraag)[:\- ]+(.+)", line, flags=__import__('re').I)
            if m:
                candidates.append(m.group(1)[:180])
        return candidates


class CancelledJob(Exception):
    pass
