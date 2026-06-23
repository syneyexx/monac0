from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PYEXE = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(cmd: list[str], *, check: bool = True) -> int:
    print("\n$", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, cwd=str(ROOT), check=check).returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="Install/update M0N4C0 dependencies safely")
    parser.add_argument("--no-venv", action="store_true", help="Install in current Python instead of .venv")
    parser.add_argument("--playwright", action="store_true", help="Also install Playwright Chromium")
    args = parser.parse_args()

    python = sys.executable
    if not args.no_venv:
        if not VENV.exists():
            run([python, "-m", "venv", str(VENV)])
        python = str(PYEXE)
    run([python, "-m", "pip", "install", "-U", "pip", "wheel", "setuptools"])
    run([python, "-m", "pip", "install", "-r", "requirements.txt"])
    if args.playwright:
        run([python, "-m", "playwright", "install", "chromium"])
    if not (ROOT / ".env").exists() and (ROOT / ".env.example").exists():
        (ROOT / ".env").write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
        print(".env aangemaakt vanuit .env.example")
    run([python, "main.py", "--init-db"], check=False)
    print("\n✅ Install klaar. Start met: python run_m0n4c0.py --gui")


if __name__ == "__main__":
    main()
