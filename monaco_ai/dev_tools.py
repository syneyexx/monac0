from __future__ import annotations

import ast
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_PACKAGES = {
    "requests": "requests",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "telegram": "python-telegram-bot",
    "httpx": "httpx",
    "ddgs": "ddgs",
    "playwright": "playwright",
    "lxml": "lxml",
    "pypdf": "pypdf",
    "docx": "python-docx",
    "numpy": "numpy",
}

PROTECTED_NAMES = {".env", "monaco_memory.db", "monaco_memory.db-wal", "monaco_memory.db-shm"}


def dependency_doctor(root: Path) -> str:
    root = Path(root)
    lines = [
        "M0N4C0 Dependency Doctor",
        f"Python: {sys.version.split()[0]} ({sys.executable})",
        f"Platform: {platform.platform()}",
        f"Project root: {root}",
        "",
        "Packages:",
    ]
    missing: list[str] = []
    for module, pip_name in REQUIRED_PACKAGES.items():
        ok = importlib.util.find_spec(module) is not None
        lines.append(f"{'OK' if ok else 'MISSING'} {module} ({pip_name})")
        if not ok:
            missing.append(pip_name)
    lines.append("")
    if missing:
        unique = sorted(set(missing))
        lines.append("Install command:")
        lines.append("py -3.11 -m pip install " + " ".join(unique))
    else:
        lines.append("All required Python packages appear installed in this interpreter.")
    try:
        import requests
        base = "http://127.0.0.1:1234/v1"
        r = requests.get(base + "/models", timeout=2)
        lines.append(f"LM Studio: HTTP {r.status_code} at {base}")
    except Exception as exc:
        lines.append(f"LM Studio: not reachable on default URL ({type(exc).__name__}: {exc})")
    try:
        import shutil as _shutil
        if _shutil.which("node"):
            lines.append("Node.js: found")
        else:
            lines.append("Node.js: not found (only needed for some future JS/tooling features)")
    except Exception:
        pass
    return "\n".join(lines)


def source_cleaner_preview(root: Path) -> tuple[str, list[Path]]:
    root = Path(root)
    candidates: list[Path] = []
    for pattern in ["**/__pycache__", "**/*.pyc", "**/.pytest_cache", "**/.mypy_cache", "**/.ruff_cache"]:
        candidates.extend(root.glob(pattern))
    build_dir = root / "data" / "build_agent_workspaces"
    if build_dir.exists():
        for item in build_dir.iterdir():
            try:
                if item.is_dir() and (time.time() - item.stat().st_mtime) > 7 * 24 * 3600:
                    candidates.append(item)
            except Exception:
                pass
    for z in root.glob("M0N4C0_*.zip"):
        try:
            if (time.time() - z.stat().st_mtime) > 3 * 24 * 3600:
                candidates.append(z)
        except Exception:
            pass
    # Never touch protected names.
    clean = []
    seen = set()
    for p in candidates:
        if p.name in PROTECTED_NAMES or any(part in PROTECTED_NAMES for part in p.parts):
            continue
        s = str(p.resolve())
        if s not in seen and p.exists():
            seen.add(s)
            clean.append(p)
    lines = ["Source Cleaner Preview", f"Root: {root}", f"Candidates: {len(clean)}", ""]
    for p in clean[:200]:
        typ = "DIR" if p.is_dir() else "FILE"
        lines.append(f"{typ} {p}")
    if len(clean) > 200:
        lines.append(f"... and {len(clean)-200} more")
    return "\n".join(lines), clean


def source_cleaner_run(root: Path) -> str:
    preview, candidates = source_cleaner_preview(root)
    removed = 0
    errors: list[str] = []
    for p in candidates:
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            removed += 1
        except Exception as exc:
            errors.append(f"{p}: {type(exc).__name__}: {exc}")
    lines = [preview, "", f"Removed: {removed}"]
    if errors:
        lines.extend(["Errors:", *errors[:50]])
    return "\n".join(lines)


def load_plugins(root: Path) -> dict[str, bool]:
    path = Path(root) / "data" / "plugin_settings.json"
    defaults = {
        "Telegram": True,
        "Research": True,
        "Idle Learning": True,
        "Build Agent": True,
        "Tools": True,
        "Worldclass Lab": True,
        "Trading Dashboard": False,
        "Image Generation": False,
        "ComfyUI": False,
        "Voice": False,
    }
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            defaults.update({str(k): bool(v) for k, v in data.items()})
    except Exception:
        pass
    return defaults


def save_plugins(root: Path, plugins: dict[str, bool]) -> None:
    path = Path(root) / "data" / "plugin_settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plugins, indent=2, ensure_ascii=False), encoding="utf-8")


def smart_error_explain(error_text: str) -> str:
    text = (error_text or "").strip()
    if not text:
        return "Plak eerst een error/traceback."
    lower = text.lower()
    lines = ["Smart Error Explainer", ""]
    if "modulenotfounderror" in lower or "no module named" in lower:
        lines.append("Waarschijnlijk mist er een Python package.")
        lines.append("Fix: draai Dependency Doctor en installeer het missende package met pip.")
    elif "syntaxerror" in lower:
        lines.append("Dit is waarschijnlijk een syntaxfout in een Python-bestand.")
        lines.append("Fix: kijk naar file/regelnummer in de traceback en draai compile-checks.")
    elif "sqlite" in lower or "database" in lower:
        lines.append("Dit lijkt database/SQLite-gerelateerd.")
        lines.append("Fix: maak eerst backup, draai integrity_check en voorkom dubbele writers.")
    elif "tkinter" in lower or "tclerror" in lower:
        lines.append("Dit lijkt GUI/Tkinter-gerelateerd.")
        lines.append("Fix: check widget lifecycle, thread access en of Tk alleen vanuit main thread wordt aangeraakt.")
    elif "connection" in lower or "timeout" in lower:
        lines.append("Dit lijkt een netwerk/API-timeout of connectiefout.")
        lines.append("Fix: check URL, service status, firewall en timeouts.")
    else:
        lines.append("Algemene fout. Kijk naar de onderste regels van de traceback; daar staat meestal file + regelnummer.")
    lines.extend(["", "Build Agent instructie-suggestie:", build_agent_instruction_from_error(text)])
    return "\n".join(lines)


def build_agent_instruction_from_error(error_text: str) -> str:
    clean = error_text.strip()
    if len(clean) > 5000:
        clean = clean[-5000:]
    return (
        "Fix deze fout in de source. Analyseer de traceback, pas de juiste bestanden aan, "
        "draai compile-checks en exporteer alleen als er echte wijzigingen zijn.\n\nERROR:\n" + clean
    )


def basic_model_benchmark(llm: Any) -> str:
    prompts = [
        ("chat", "Leg kort uit wat M0N4C0 is in 2 zinnen."),
        ("code", "Schrijf een kleine Python functie add(a,b) met type hints."),
    ]
    lines = ["M0N4C0 Model Benchmark", ""]
    old_role = getattr(llm.settings, "llm_forced_model_role", "auto")
    try:
        for role, prompt in prompts:
            start = time.time()
            llm.settings.llm_forced_model_role = role
            res = llm.safe_chat("Antwoord kort en concreet.", prompt, "", attempts=1)
            elapsed = time.time() - start
            status = "OK" if res.text and not res.error else "FAIL"
            used = res.used_model or getattr(llm.settings, "lmstudio_model", "")
            lines.append(f"{status} role={role} model={used} time={elapsed:.2f}s")
            lines.append((res.text or res.error or "geen output")[:500])
            lines.append("")
    finally:
        llm.settings.llm_forced_model_role = old_role
    return "\n".join(lines)


def create_safe_mode_files(root: Path) -> str:
    root = Path(root)
    safe_bat = root / "START_SAFE_MODE.bat"
    safe_bat.write_text(
        "@echo off\r\n"
        "cd /d %~dp0\r\n"
        "py -3.11 run_m0n4c0.py --gui --safe-mode\r\n"
        "pause\r\n",
        encoding="utf-8",
    )
    return f"Safe mode starter ready: {safe_bat}"
