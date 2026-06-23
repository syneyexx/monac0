from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .utils import utc_now


def parse_owner_ids(value: str | list[int] | list[str] | set[int] | tuple[Any, ...] | None) -> set[int]:
    """Parse Telegram owner ids from env/json/gui text safely."""
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        out: set[int] = set()
        for item in value:
            try:
                text = str(item).strip()
                if text:
                    out.add(int(text))
            except Exception:
                continue
        return out
    out: set[int] = set()
    raw = str(value).replace(";", ",").replace("\n", ",")
    for item in raw.split(","):
        text = item.strip()
        if not text:
            continue
        try:
            out.add(int(text))
        except Exception:
            continue
    return out




def normalize_telegram_username(value: Any) -> str:
    """Normalize a Telegram username for permission checks.

    Accepts @Name, Name, mixed case and extra spacing. Returns lowercase
    username without the @ prefix. Empty/invalid-ish values return "".
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("@"):
        text = text[1:]
    text = text.strip().lower()
    # Telegram usernames are normally letters/numbers/underscores, but keep the
    # parser forgiving and only remove obvious separators/noise.
    text = text.replace(" ", "").replace(",", "").replace(";", "")
    return text


def parse_owner_usernames(value: str | list[str] | set[str] | tuple[Any, ...] | None) -> set[str]:
    """Parse Telegram owner usernames from env/json/gui text safely."""
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {u for u in (normalize_telegram_username(item) for item in value) if u}
    raw = str(value).replace(";", ",").replace("\n", ",")
    return {u for u in (normalize_telegram_username(item) for item in raw.split(",")) if u}

def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "aan"}


@dataclass(slots=True)
class TelegramRuntimeConfig:
    """Live Telegram settings saved outside .env so the GUI can update them."""

    enabled: bool = False
    token: str = ""
    owner_ids: list[int] | None = None
    owner_usernames: list[str] | None = None
    allow_all: bool = True
    auto_start: bool = False
    status_message: str = ""
    updated_at: str = ""

    @classmethod
    def from_env(cls) -> "TelegramRuntimeConfig":
        return cls(
            enabled=_bool(os.getenv("TELEGRAM_ENABLED"), False),
            token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            owner_ids=sorted(parse_owner_ids(os.getenv("TELEGRAM_OWNER_IDS", ""))),
            owner_usernames=sorted(parse_owner_usernames(os.getenv("TELEGRAM_OWNER_USERNAMES", ""))),
            allow_all=_bool(os.getenv("TELEGRAM_ALLOW_ALL"), True),
            auto_start=_bool(os.getenv("TELEGRAM_AUTO_START"), False),
            status_message="loaded from .env",
            updated_at=utc_now(),
        )

    @classmethod
    def from_settings(cls, settings: Any) -> "TelegramRuntimeConfig":
        return cls(
            enabled=bool(getattr(settings, "telegram_enabled", False)),
            token=str(getattr(settings, "telegram_bot_token", "") or ""),
            owner_ids=sorted(parse_owner_ids(getattr(settings, "telegram_owner_ids", set()))),
            owner_usernames=sorted(parse_owner_usernames(getattr(settings, "telegram_owner_usernames", set()))),
            allow_all=bool(getattr(settings, "telegram_allow_all", True)),
            auto_start=bool(getattr(settings, "telegram_auto_start", False)),
            status_message="loaded from runtime settings",
            updated_at=utc_now(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any], fallback: "TelegramRuntimeConfig") -> "TelegramRuntimeConfig":
        token = str(data.get("token") or data.get("bot_token") or fallback.token or "")
        owner_ids = sorted(parse_owner_ids(data.get("owner_ids", fallback.owner_ids or [])))
        owner_usernames = sorted(parse_owner_usernames(data.get("owner_usernames", data.get("owners", fallback.owner_usernames or []))))
        return cls(
            enabled=_bool(data.get("enabled"), fallback.enabled),
            token=token.strip(),
            owner_ids=owner_ids,
            owner_usernames=owner_usernames,
            allow_all=_bool(data.get("allow_all"), fallback.allow_all),
            auto_start=_bool(data.get("auto_start"), fallback.auto_start),
            status_message=str(data.get("status_message") or "loaded from data/telegram_settings.json"),
            updated_at=str(data.get("updated_at") or utc_now()),
        )

    def to_dict(self, redact_token: bool = False) -> dict[str, Any]:
        payload = asdict(self)
        payload["owner_ids"] = sorted(parse_owner_ids(payload.get("owner_ids")))
        payload["owner_usernames"] = sorted(parse_owner_usernames(payload.get("owner_usernames")))
        payload["updated_at"] = utc_now()
        if redact_token and payload.get("token"):
            payload["token"] = mask_token(str(payload["token"]))
        return payload

    @property
    def owner_ids_set(self) -> set[int]:
        return parse_owner_ids(self.owner_ids)

    @property
    def owner_usernames_set(self) -> set[str]:
        return parse_owner_usernames(self.owner_usernames)


def mask_token(token: str) -> str:
    token = str(token or "").strip()
    if not token:
        return ""
    if len(token) <= 12:
        return "•" * len(token)
    return f"{token[:6]}…{token[-5:]}"


def config_path(root_or_settings: Any) -> Path:
    root = getattr(root_or_settings, "root", root_or_settings)
    return Path(root) / "data" / "telegram_settings.json"


def load_telegram_runtime_config(root_or_settings: Any | None = None) -> TelegramRuntimeConfig:
    fallback = TelegramRuntimeConfig.from_env()
    if root_or_settings is not None and not isinstance(root_or_settings, (str, Path)):
        # If a Settings object is passed, runtime values are a better fallback
        # than .env, because they may already include GUI overrides.
        if hasattr(root_or_settings, "telegram_bot_token"):
            fallback = TelegramRuntimeConfig.from_settings(root_or_settings)
    if root_or_settings is None:
        root_or_settings = Path.cwd()
    path = config_path(root_or_settings)
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return TelegramRuntimeConfig.from_dict(data, fallback)
    except Exception:
        return fallback
    return fallback


def save_telegram_runtime_config(root_or_settings: Any, cfg: TelegramRuntimeConfig) -> None:
    path = config_path(root_or_settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg.to_dict(redact_token=False), indent=2, ensure_ascii=False), encoding="utf-8")


def apply_telegram_runtime_config(settings: Any, cfg: TelegramRuntimeConfig) -> None:
    settings.telegram_enabled = bool(cfg.enabled)
    settings.telegram_bot_token = str(cfg.token or "").strip()
    settings.telegram_owner_ids = cfg.owner_ids_set
    settings.telegram_owner_usernames = cfg.owner_usernames_set
    settings.telegram_allow_all = bool(cfg.allow_all)
    if hasattr(settings, "telegram_auto_start"):
        settings.telegram_auto_start = bool(cfg.auto_start)
