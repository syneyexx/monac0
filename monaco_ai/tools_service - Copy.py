from __future__ import annotations

import json
import mimetypes
import socket
import threading
import time
import urllib.parse
from dataclasses import dataclass, asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import requests

from .telegram_settings import normalize_telegram_username
from .utils import utc_now, sha256_text


DOCUMENT_EXTENSIONS = {".pdf", ".epub", ".docx", ".doc", ".txt", ".md", ".rtf", ".csv", ".json", ".xlsx", ".xls"}


@dataclass(slots=True)
class URLCheckResult:
    url: str
    ok: bool
    status_code: int | None = None
    final_url: str | None = None
    content_type: str | None = None
    content_length: str | None = None
    is_document: bool = False
    message: str = ""

    def to_text(self) -> str:
        lines = [
            f"URL: {self.url}",
            f"OK: {self.ok}",
            f"HTTP status: {self.status_code if self.status_code is not None else '-'}",
            f"Final URL: {self.final_url or '-'}",
            f"Content-Type: {self.content_type or '-'}",
            f"Content-Length: {self.content_length or '-'}",
            f"Document/e-book: {'yes' if self.is_document else 'no'}",
        ]
        if self.message:
            lines.append(f"Message: {self.message}")
        return "\n".join(lines)


def normalize_username_list(raw: str) -> list[str]:
    parts = str(raw or "").replace(";", ",").replace("\n", ",").split(",")
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        u = normalize_telegram_username(part)
        if u and u not in seen:
            seen.add(u)
            out.append("@" + u)
    return out


def validate_url(url: str, *, timeout: int = 12) -> URLCheckResult:
    url = (url or "").strip()
    if not url:
        return URLCheckResult(url=url, ok=False, message="Geen URL ingevuld.")
    if not re_url_has_scheme(url):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return URLCheckResult(url=url, ok=False, message="Ongeldige URL. Gebruik http(s)://...")
    headers = {"User-Agent": "M0N4C0-AI Tools/1.0 (+local diagnostic)"}
    try:
        try:
            response = requests.head(url, allow_redirects=True, timeout=timeout, headers=headers)
            if response.status_code in {405, 403} or response.status_code >= 500:
                raise requests.RequestException(f"HEAD not useful: {response.status_code}")
        except Exception:
            response = requests.get(url, allow_redirects=True, timeout=timeout, headers=headers, stream=True)
        ctype = response.headers.get("Content-Type", "")
        clen = response.headers.get("Content-Length", "")
        path = urllib.parse.urlparse(response.url).path
        ext = Path(path).suffix.lower()
        guessed = mimetypes.guess_type(path)[0] or ""
        is_doc = ext in DOCUMENT_EXTENSIONS or any(token in ctype.lower() for token in ["pdf", "epub", "msword", "officedocument", "text/plain", "application/json"]) or any(token in guessed.lower() for token in ["pdf", "epub", "word", "json", "text"])
        return URLCheckResult(
            url=url,
            ok=bool(response.ok),
            status_code=response.status_code,
            final_url=response.url,
            content_type=ctype,
            content_length=clen,
            is_document=is_doc,
            message="Bereikbaar." if response.ok else f"Server gaf HTTP {response.status_code}.",
        )
    except Exception as exc:
        return URLCheckResult(url=url, ok=False, message=f"{type(exc).__name__}: {exc}")


def re_url_has_scheme(url: str) -> bool:
    return "://" in url[:12]


def test_telegram_token(token: str, *, timeout: int = 12) -> str:
    token = str(token or "").strip()
    if not token:
        return "Geen bot token ingevuld."
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=timeout)
        if not r.ok:
            return f"Telegram API HTTP {r.status_code}: {r.text[:500]}"
        data = r.json()
        if not data.get("ok"):
            return f"Telegram API ok=false: {data}"
        bot = data.get("result", {})
        return "\n".join([
            "Telegram token OK ✅",
            f"id: {bot.get('id')}",
            f"username: @{bot.get('username')}",
            f"name: {bot.get('first_name')}",
            f"can_join_groups: {bot.get('can_join_groups')}",
            f"can_read_all_group_messages: {bot.get('can_read_all_group_messages')}",
            f"supports_inline_queries: {bot.get('supports_inline_queries')}",
        ])
    except Exception as exc:
        return f"Telegram token test mislukt: {type(exc).__name__}: {exc}"


def get_public_ip(timeout: int = 10) -> str:
    endpoints = [
        "https://api.ipify.org?format=json",
        "https://ifconfig.me/ip",
    ]
    errors: list[str] = []
    for endpoint in endpoints:
        try:
            r = requests.get(endpoint, timeout=timeout, headers={"User-Agent": "M0N4C0-AI Tools/1.0"})
            if r.ok:
                if "json" in r.headers.get("Content-Type", "").lower():
                    data = r.json()
                    return str(data.get("ip") or data)
                return r.text.strip()[:120]
            errors.append(f"{endpoint}: HTTP {r.status_code}")
        except Exception as exc:
            errors.append(f"{endpoint}: {type(exc).__name__}: {exc}")
    return "Public IP check niet gelukt. " + " | ".join(errors[:3])


class ConsentDiagnosticServer:
    """Tiny transparent consent page for network diagnostics.

    This does not attempt to identify a person from a Telegram username. It only
    records a request after someone opens a clearly labelled diagnostic page.
    """

    def __init__(self, output_dir: Path, port: int = 8787):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.port = int(port or 8787)
        self.token = sha256_text(f"{time.time()}|{socket.gethostname()}")[:16]
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.records_path = self.output_dir / "consent_diagnostics.jsonl"

    def start(self) -> str:
        if self.server is not None:
            return self.url()
        handler = self._make_handler()
        self.server = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.url()

    def stop(self) -> None:
        if self.server is not None:
            try:
                self.server.shutdown()
                self.server.server_close()
            finally:
                self.server = None
                self.thread = None

    def url(self) -> str:
        ip = local_lan_ip()
        return f"http://{ip}:{self.port}/diagnostic/{self.token}"

    def _make_handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != f"/diagnostic/{owner.token}":
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Not found")
                    return
                record = {
                    "created_at": utc_now(),
                    "remote_ip": self.client_address[0] if self.client_address else "",
                    "user_agent": self.headers.get("User-Agent", ""),
                    "accept_language": self.headers.get("Accept-Language", ""),
                    "path": self.path,
                }
                with owner.records_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                body = """
<!doctype html><html><head><meta charset="utf-8"><title>M0N4C0 Network Diagnostic</title>
<style>body{font-family:Segoe UI,Arial;background:#05070d;color:#f4f1ff;padding:40px;max-width:760px;margin:auto} .card{border:1px solid #222838;background:#101522;padding:24px;border-radius:14px} b{color:#f4d27a}</style></head>
<body><div class="card"><h1>M0N4C0 Network Diagnostic</h1>
<p>Je hebt vrijwillig een diagnostic link geopend. Voor troubleshooting wordt alleen beperkte technische info opgeslagen:</p>
<ul><li>IP-adres waarmee deze pagina is geopend</li><li>browser/user-agent</li><li>tijdstip</li></ul>
<p>Dit wordt transparant gebruikt voor netwerkdiagnose/support. Sluit deze pagina als je dit niet wilt.</p>
<p><b>Diagnostic ontvangen.</b></p></div></body></html>
""".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


def local_lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        finally:
            sock.close()
    except Exception:
        return "127.0.0.1"


def read_diagnostic_records(path: Path, limit: int = 50) -> str:
    path = Path(path)
    if not path.exists():
        return "Nog geen consent diagnostics ontvangen."
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    if not lines:
        return "Nog geen consent diagnostics ontvangen."
    out = ["CONSENT DIAGNOSTIC RECORDS"]
    for line in lines:
        try:
            data = json.loads(line)
            out.append(f"- {data.get('created_at')} | ip={data.get('remote_ip')} | ua={str(data.get('user_agent') or '')[:90]}")
        except Exception:
            out.append(f"- {line[:160]}")
    return "\n".join(out)
