from __future__ import annotations

import json
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

from .config import Settings
from .db import MonacoDB
from .utils import chunk_text, normalize_ws, utc_now


class WebsiteLearner:
    def __init__(self, settings: Settings, db: MonacoDB):
        self.settings = settings
        self.db = db

    def classify(self, url: str, title: str = "", text: str = "") -> str:
        host = urlparse(url).netloc.lower()
        hay = f"{host} {title} {text[:3000]}".lower()
        if "instagram" in host:
            return "social_media"
        if "github" in host:
            return "code_repository"
        if "youtube" in host:
            return "video_platform"
        if "docs" in host or "api" in hay or "documentation" in hay:
            return "technical_docs"
        if "shop" in hay or "cart" in hay or "product" in hay:
            return "ecommerce"
        if "login" in hay or "sign in" in hay:
            return "portal_or_login_site"
        if "pdf" in hay or "download" in hay or "ebook" in hay:
            return "document_library"
        return "website"

    def learn_public_site(self, root_url: str, max_pages: int = 20) -> str:
        root_url = root_url.strip()
        if not root_url.startswith("http"):
            root_url = "https://" + root_url
        domain = urlparse(root_url).netloc.lower()
        seen: set[str] = set()
        queue = [root_url]
        pages = 0
        chunks_added = 0
        source_profile_id = self._upsert_profile(domain, root_url, "unknown", False, "public")
        while queue and pages < max_pages:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            title, text, links = self._fetch_page(url)
            if not text:
                continue
            if pages == 0:
                source_type = self.classify(root_url, title, text)
                self._update_profile(source_profile_id, source_type, len(seen))
            source_id = self.db.add_source("website", title or url, url, domain, {"domain": domain}, reliability=0.5)
            for idx, chunk in enumerate(chunk_text(text, max_chars=2800, overlap=250)[:30]):
                if self.db.add_chunk(source_id, domain, title or url, url, idx, chunk, quality_score=0.5):
                    chunks_added += 1
            pages += 1
            for link in links:
                parsed = urlparse(link)
                if parsed.netloc.lower() == domain and link not in seen and len(queue) < max_pages * 3:
                    queue.append(link)
        self._update_profile(source_profile_id, None, pages)
        return f"✅ Website geleerd: {root_url}\nDomein: {domain}\nPagina's: {pages}\nChunks toegevoegd: {chunks_added}"

    def _fetch_page(self, url: str) -> tuple[str, str, list[str]]:
        headers = {"User-Agent": self.settings.web_user_agent}
        try:
            r = requests.get(url, headers=headers, timeout=20)
            soup = BeautifulSoup(r.text, "lxml")
            for tag in soup(["script", "style", "noscript", "svg"]):
                tag.decompose()
            title = normalize_ws(soup.title.get_text(" ") if soup.title else url)
            text = normalize_ws(soup.get_text("\n"))
            links = []
            for a in soup.find_all("a", href=True):
                href = str(a.get("href", ""))
                if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                    continue
                full = urljoin(url, href).split("#")[0]
                if full.startswith("http"):
                    links.append(full)
            return title, text, links
        except Exception as e:
            self.db.log_error("WEBSITE_FETCH", str(e), metadata={"url": url})
            return "", "", []

    def _upsert_profile(self, domain: str, root_url: str, source_type: str, login_required: bool, access_method: str) -> int:
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO website_profiles(domain,root_url,source_type,login_required,access_method,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(root_url) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (domain, root_url, source_type, int(login_required), access_method, "active", now, now),
            )
            return int(conn.execute("SELECT id FROM website_profiles WHERE root_url=?", (root_url,)).fetchone()["id"])

    def _update_profile(self, profile_id: int, source_type: str | None, pages_seen: int) -> None:
        with self.db.connect() as conn:
            if source_type:
                conn.execute("UPDATE website_profiles SET source_type=?, pages_seen=?, updated_at=? WHERE id=?", (source_type, pages_seen, utc_now(), profile_id))
            else:
                conn.execute("UPDATE website_profiles SET pages_seen=?, updated_at=? WHERE id=?", (pages_seen, utc_now(), profile_id))

    def manual_login_note(self, url: str) -> str:
        return (
            "Website-login voorbereiding:\n"
            f"URL: {url}\n\n"
            "M0N4C0-AI kan websites met login leren via een handmatige browser-sessie waar jij zelf inlogt. "
            "Hij omzeilt geen beveiliging, captcha of 2FA. Na inloggen kan de bot pagina's lezen waarvoor jij toegang hebt.\n\n"
            "Installatie voor browserlaag:\n"
            "py -3.11 -m pip install playwright\n"
            "py -3.11 -m playwright install chromium\n\n"
            "Command in terminal komt in een volgende laag: /website browser learn <url>"
        )
