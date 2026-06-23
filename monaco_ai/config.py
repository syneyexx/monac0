from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

from .telegram_settings import load_telegram_runtime_config


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on", "aan"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass(slots=True)
class Settings:
    root: Path
    db_path: Path
    lmstudio_base_url: str
    lmstudio_model: str
    lmstudio_timeout: int
    lmstudio_coding_base_url: str
    lmstudio_coding_model: str
    lmstudio_research_base_url: str
    lmstudio_research_model: str
    lmstudio_telegram_base_url: str
    lmstudio_telegram_model: str
    lmstudio_image_base_url: str
    lmstudio_image_model: str
    lmstudio_trading_base_url: str
    lmstudio_trading_model: str
    llm_model_mode: str
    llm_forced_model_role: str
    llm_programming_router_enabled: bool
    llm_max_context_chars: int
    llm_max_output_tokens: int
    llm_temperature: float
    llm_top_p: float
    llm_repeat_penalty: float
    llm_top_k: int
    llm_min_p: float
    llm_system_prompt: str
    telegram_enabled: bool
    telegram_bot_token: str
    telegram_owner_ids: set[int]
    telegram_owner_usernames: set[str]
    telegram_allow_all: bool
    telegram_auto_start: bool
    internet_enabled: bool
    web_user_agent: str
    default_learn_rounds: int
    max_learn_rounds: int
    max_pages_per_round: int
    playwright_user_data_dir: Path
    tech_status: str

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def logs_dir(self) -> Path:
        return self.root / "data" / "logs"


def _load_llm_gui_overrides(root: Path) -> dict[str, object]:
    path = root / "data" / "llm_model_settings.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _cfg_str(overrides: dict[str, object], key: str, env_name: str, default: str) -> str:
    value = overrides.get(key)
    if value not in (None, ""):
        return str(value)
    return os.getenv(env_name, default)


def _cfg_int(overrides: dict[str, object], key: str, env_name: str, default: int) -> int:
    value = overrides.get(key)
    if value not in (None, ""):
        try:
            return int(float(value))
        except Exception:
            pass
    return _int(os.getenv(env_name), default)



def _cfg_bool(overrides: dict[str, object], key: str, env_name: str, default: bool) -> bool:
    value = overrides.get(key)
    if value not in (None, ""):
        return _bool(str(value), default)
    return _bool(os.getenv(env_name), default)

def _cfg_float(overrides: dict[str, object], key: str, env_name: str, default: float) -> float:
    value = overrides.get(key)
    if value not in (None, ""):
        try:
            return float(value)
        except Exception:
            pass
    return _float(os.getenv(env_name), default)


def load_settings(root: Path | None = None) -> Settings:
    if root is None:
        root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    llm_overrides = _load_llm_gui_overrides(root)
    telegram_overrides = load_telegram_runtime_config(root)
    db_path = Path(os.getenv("MONACO_DB_PATH", "data/monaco_memory.db"))
    if not db_path.is_absolute():
        db_path = root / db_path
    session_dir = Path(os.getenv("PLAYWRIGHT_USER_DATA_DIR", "data/website_sessions"))
    if not session_dir.is_absolute():
        session_dir = root / session_dir
    return Settings(
        root=root,
        db_path=db_path,
        lmstudio_base_url=_cfg_str(llm_overrides, "base_url", "LMSTUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/"),
        lmstudio_model=_cfg_str(llm_overrides, "model_id", "LMSTUDIO_MODEL", "dolphin-3.0-llama-3.1-8b"),
        lmstudio_timeout=_int(os.getenv("LMSTUDIO_TIMEOUT"), 120),
        lmstudio_coding_base_url=_cfg_str(llm_overrides, "coding_base_url", "LMSTUDIO_CODING_BASE_URL", _cfg_str(llm_overrides, "base_url", "LMSTUDIO_BASE_URL", "http://localhost:1234/v1")).rstrip("/"),
        lmstudio_coding_model=_cfg_str(llm_overrides, "coding_model_id", "LMSTUDIO_CODING_MODEL", _cfg_str(llm_overrides, "model_id", "LMSTUDIO_MODEL", "dolphin-3.0-llama-3.1-8b")),
        lmstudio_research_base_url=_cfg_str(llm_overrides, "research_base_url", "LMSTUDIO_RESEARCH_BASE_URL", _cfg_str(llm_overrides, "base_url", "LMSTUDIO_BASE_URL", "http://localhost:1234/v1")).rstrip("/"),
        lmstudio_research_model=_cfg_str(llm_overrides, "research_model_id", "LMSTUDIO_RESEARCH_MODEL", _cfg_str(llm_overrides, "model_id", "LMSTUDIO_MODEL", "dolphin-3.0-llama-3.1-8b")),
        lmstudio_telegram_base_url=_cfg_str(llm_overrides, "telegram_base_url", "LMSTUDIO_TELEGRAM_BASE_URL", _cfg_str(llm_overrides, "base_url", "LMSTUDIO_BASE_URL", "http://localhost:1234/v1")).rstrip("/"),
        lmstudio_telegram_model=_cfg_str(llm_overrides, "telegram_model_id", "LMSTUDIO_TELEGRAM_MODEL", _cfg_str(llm_overrides, "model_id", "LMSTUDIO_MODEL", "dolphin-3.0-llama-3.1-8b")),
        lmstudio_image_base_url=_cfg_str(llm_overrides, "image_base_url", "LMSTUDIO_IMAGE_BASE_URL", _cfg_str(llm_overrides, "base_url", "LMSTUDIO_BASE_URL", "http://localhost:1234/v1")).rstrip("/"),
        lmstudio_image_model=_cfg_str(llm_overrides, "image_model_id", "LMSTUDIO_IMAGE_MODEL", _cfg_str(llm_overrides, "model_id", "LMSTUDIO_MODEL", "dolphin-3.0-llama-3.1-8b")),
        lmstudio_trading_base_url=_cfg_str(llm_overrides, "trading_base_url", "LMSTUDIO_TRADING_BASE_URL", _cfg_str(llm_overrides, "base_url", "LMSTUDIO_BASE_URL", "http://localhost:1234/v1")).rstrip("/"),
        lmstudio_trading_model=_cfg_str(llm_overrides, "trading_model_id", "LMSTUDIO_TRADING_MODEL", _cfg_str(llm_overrides, "model_id", "LMSTUDIO_MODEL", "dolphin-3.0-llama-3.1-8b")),
        llm_model_mode=_cfg_str(llm_overrides, "model_mode", "LLM_MODEL_MODE", "split"),
        llm_forced_model_role="auto",
        llm_programming_router_enabled=_cfg_bool(llm_overrides, "programming_router_enabled", "LLM_PROGRAMMING_ROUTER_ENABLED", True),
        llm_max_context_chars=_cfg_int(llm_overrides, "context_chars", "LLM_MAX_CONTEXT_CHARS", 18000),
        llm_max_output_tokens=_cfg_int(llm_overrides, "max_tokens", "LLM_MAX_OUTPUT_TOKENS", 900),
        llm_temperature=_cfg_float(llm_overrides, "temperature", "LLM_TEMPERATURE", 0.45),
        llm_top_p=_cfg_float(llm_overrides, "top_p", "LLM_TOP_P", 0.90),
        llm_repeat_penalty=_cfg_float(llm_overrides, "repeat_penalty", "LLM_REPEAT_PENALTY", 1.10),
        llm_top_k=_cfg_int(llm_overrides, "top_k", "LLM_TOP_K", 40),
        llm_min_p=_cfg_float(llm_overrides, "min_p", "LLM_MIN_P", 0.05),
        llm_system_prompt=_cfg_str(llm_overrides, "system_prompt", "LLM_SYSTEM_PROMPT", ""),
        telegram_enabled=telegram_overrides.enabled,
        telegram_bot_token=telegram_overrides.token,
        telegram_owner_ids=telegram_overrides.owner_ids_set,
        telegram_owner_usernames=telegram_overrides.owner_usernames_set,
        telegram_allow_all=telegram_overrides.allow_all,
        telegram_auto_start=telegram_overrides.auto_start,
        internet_enabled=_bool(os.getenv("INTERNET_ENABLED"), True),
        web_user_agent=os.getenv("WEB_USER_AGENT", "M0N4C0-AI/1.0 local research bot"),
        default_learn_rounds=max(1, _int(os.getenv("DEFAULT_LEARN_ROUNDS"), 3)),
        max_learn_rounds=max(1, _int(os.getenv("MAX_LEARN_ROUNDS"), 10)),
        max_pages_per_round=max(1, _int(os.getenv("MAX_PAGES_PER_ROUND"), 8)),
        playwright_user_data_dir=session_dir,
        tech_status=os.getenv("TECH_STATUS", "normal").strip().lower(),
    )


def ensure_dirs(settings: Settings) -> None:
    for p in [settings.data_dir, settings.logs_dir, settings.playwright_user_data_dir, settings.root / "data" / "exports", settings.root / "data" / "downloads"]:
        p.mkdir(parents=True, exist_ok=True)
