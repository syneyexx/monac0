from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from monaco_ai.config import ensure_dirs, load_settings
from monaco_ai.db import MonacoDB
from monaco_ai.utils import utc_now


def parse_iso(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        if value.endswith('Z'):
            value = value[:-1] + '+00:00'
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="M0N4C0 idle learning watcher")
    parser.add_argument("--idle-seconds", type=int, default=300, help="Seconds zonder command/chat voordat idle learning mag queueën")
    parser.add_argument("--poll", type=float, default=15.0, help="Seconds tussen checks")
    parser.add_argument("--cooldown", type=int, default=1800, help="Seconds voordat hetzelfde idle-topic opnieuw mag queueën")
    parser.add_argument("--max-queued", type=int, default=2, help="Max queued/running idle jobs tegelijk")
    args = parser.parse_args()

    settings = load_settings(Path(__file__).resolve().parent)
    ensure_dirs(settings)
    db = MonacoDB(settings.db_path)
    db.log_learning_event(None, "idle-watcher", "OK", f"Idle watcher gestart: idle={args.idle_seconds}s cooldown={args.cooldown}s")
    print(f"[{utc_now()}] [OK] [idle-watcher] gestart", flush=True)

    while True:
        try:
            enabled = db.get_app_setting("idle_learning_enabled", True)
            if not enabled:
                time.sleep(args.poll)
                continue
            last = parse_iso(db.last_activity_at())
            now = time.time()
            if last and now - last < args.idle_seconds:
                time.sleep(args.poll)
                continue
            with db.connect() as conn:
                active = int(conn.execute("SELECT count(*) c FROM learning_jobs WHERE source='idle_learning' AND status IN ('queued','pending','running')").fetchone()["c"])
            if active >= args.max_queued:
                time.sleep(args.poll)
                continue
            topics = db.list_idle_topics(enabled_only=True, limit=25)
            queued_any = False
            for row in topics:
                last_q = parse_iso(row["last_queued_at"])
                if last_q and now - last_q < args.cooldown:
                    continue
                try:
                    source_urls = json.loads(row["source_urls_json"] or "[]")
                    if not isinstance(source_urls, list):
                        source_urls = []
                except Exception:
                    source_urls = []
                job_id = db.enqueue_learning_job(
                    str(row["topic"]),
                    int(row["rounds"] or 2),
                    mode=str(row["mode"] or "topic"),
                    priority=int(row["priority"] or 5),
                    agent="idle_learning",
                    source="idle_learning",
                    metadata={"idle_topic_id": int(row["id"]), "queued_by": "idle_worker"},
                    source_urls=[str(u) for u in source_urls],
                )
                db.mark_idle_topic_queued(int(row["id"]))
                msg = f"Idle topic queued job #{job_id}: {row['topic']}"
                db.log_learning_event(job_id, "idle-watcher", "OK", msg)
                print(f"[{utc_now()}] [OK] [idle-watcher] {msg}", flush=True)
                queued_any = True
                break
            if not queued_any and db.get_app_setting("idle_wikipedia_enabled", False):
                job_id = db.enqueue_learning_job(
                    "random wikipedia",
                    2,
                    mode="wikipedia",
                    priority=4,
                    agent="idle_learning",
                    source="idle_learning",
                    metadata={"queued_by": "idle_worker", "source": "wikipedia_random", "no_topic_fallback": True},
                )
                msg = f"Idle Wikipedia random learning queued job #{job_id}"
                db.log_learning_event(job_id, "idle-watcher", "OK", msg)
                print(f"[{utc_now()}] [OK] [idle-watcher] {msg}", flush=True)
        except KeyboardInterrupt:
            db.log_learning_event(None, "idle-watcher", "WARN", "Idle watcher gestopt met Ctrl+C")
            print(f"[{utc_now()}] [WARN] [idle-watcher] gestopt", flush=True)
            return
        except Exception as exc:
            db.log_error("IDLE_WORKER", f"{type(exc).__name__}: {exc}")
            print(f"[{utc_now()}] [ERR] [idle-watcher] {type(exc).__name__}: {exc}", flush=True)
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
