from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from monaco_ai.config import load_settings, ensure_dirs
from monaco_ai.db import MonacoDB
from monaco_ai.utils import chunk_text

ROOT = Path(__file__).resolve().parents[1]


async def main_async(url: str, pages: int) -> None:
    settings = load_settings(ROOT)
    ensure_dirs(settings)
    db = MonacoDB(settings.db_path)
    try:
        from playwright.async_api import async_playwright
    except Exception:
        print("Installeer: py -3.11 -m pip install playwright && py -3.11 -m playwright install chromium")
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(str(settings.playwright_user_data_dir), headless=False)
        page = await browser.new_page()
        await page.goto(url)
        print("Browser geopend. Log handmatig in als nodig. Druk ENTER in deze terminal als de pagina klaar is.")
        input()
        title = await page.title()
        text = await page.locator("body").inner_text(timeout=15000)
        source_id = db.add_source("website_login_session", title or url, url, url, {"manual_session": True}, reliability=0.6)
        count = 0
        for idx, chunk in enumerate(chunk_text(text, max_chars=2800, overlap=250)):
            if db.add_chunk(source_id, url, title, url, idx, chunk, quality_score=0.6):
                count += 1
        print(f"Opgeslagen chunks: {count}")
        await browser.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--pages", type=int, default=1)
    args = ap.parse_args()
    asyncio.run(main_async(args.url, args.pages))


if __name__ == "__main__":
    main()
