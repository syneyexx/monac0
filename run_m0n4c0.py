from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
PYTHON = str(VENV_PY) if VENV_PY.exists() else sys.executable


def main() -> None:
    parser = argparse.ArgumentParser(description="M0N4C0 launcher")
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--idle", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--safe-mode", action="store_true")
    parser.add_argument("--agents", type=int, default=3)
    args = parser.parse_args()

    procs: list[subprocess.Popen] = []
    flags = []
    if args.all:
        flags = ["main.py", "--both"]
        procs.append(subprocess.Popen([PYTHON, "learning_worker.py", "--agents", str(args.agents)], cwd=str(ROOT)))
        procs.append(subprocess.Popen([PYTHON, "idle_worker.py"], cwd=str(ROOT)))
    elif args.worker:
        flags = ["learning_worker.py", "--agents", str(args.agents)]
        os.execv(PYTHON, [PYTHON] + flags)
    elif args.idle:
        os.execv(PYTHON, [PYTHON, "idle_worker.py"])
    elif args.telegram:
        flags = ["main.py", "--telegram"]
        os.execv(PYTHON, [PYTHON] + flags)
    else:
        flags = ["main.py", "--gui"]
        if args.safe_mode:
            flags.append("--safe-mode")
    try:
        subprocess.run([PYTHON] + flags, cwd=str(ROOT), check=False)
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
