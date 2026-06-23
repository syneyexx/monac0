from __future__ import annotations

import sqlite3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "monaco_memory.db"


def main() -> None:
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DB
    print(f"DB: {db}")
    if not db.exists():
        print("Bestaat niet. Start: py -3.11 main.py --init-db")
        return
    con = sqlite3.connect(db)
    try:
        print("quick_check:", con.execute("PRAGMA quick_check").fetchone()[0])
        rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        print("tables:", len(rows))
        for (name,) in rows:
            try:
                c = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                print(f"- {name}: {c}")
            except Exception as e:
                print(f"- {name}: error {e}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
