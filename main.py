from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

from monaco_ai.commands import CommandContext, CommandRouter
from monaco_ai.config import ensure_dirs, load_settings
from monaco_ai.db import MonacoDB
from monaco_ai.general_knowledge_seed import ensure_general_business_knowledge


def terminal_loop(router: CommandRouter) -> None:
    print("M0N4C0-AI terminal gestart. Typ /help voor commands. Ctrl+C om te stoppen.")
    ctx = CommandContext(platform="terminal", chat_id="terminal", user_key="terminal:owner", username="owner", display_name="Owner")
    while True:
        try:
            text = input("M0N4C0> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nM0N4C0-AI gestopt.")
            return
        if text.lower() in {"exit", "quit", "/exit", "/quit"}:
            print("M0N4C0-AI gestopt.")
            return
        if not text:
            continue
        print(router.handle(text, ctx))


def main() -> None:
    parser = argparse.ArgumentParser(description="M0N4C0-AI")
    parser.add_argument("--gui", action="store_true", help="Start desktop GUI (default)")
    parser.add_argument("--terminal", action="store_true", help="Start terminal interface")
    parser.add_argument("--telegram", action="store_true", help="Start Telegram bot")
    parser.add_argument("--both", action="store_true", help="Start Telegram + GUI")
    parser.add_argument("--worker", action="store_true", help="Start externe learning worker")
    parser.add_argument("--all", action="store_true", help="Start GUI + Telegram + externe worker + idle watcher in deze sessie")
    parser.add_argument("--idle", action="store_true", help="Start idle learning watcher")
    parser.add_argument("--agents", type=int, default=2, help="Aantal learning agents voor --worker/--all")
    parser.add_argument("--init-db", action="store_true", help="Alleen database initialiseren")
    parser.add_argument("--safe-mode", action="store_true", help="Start GUI in repair/safe mode")
    args = parser.parse_args()

    settings = load_settings(Path(__file__).resolve().parent)
    ensure_dirs(settings)
    db = MonacoDB(settings.db_path)
    ensure_general_business_knowledge(db)
    router = CommandRouter(settings, db)

    if args.init_db:
        print(f"Database klaar: {settings.db_path}")
        stats = db.stats()
        print("SQLite / knowledge stats")
        for key, value in stats.items():
            print(f"- {key}: {value}")
        return

    if not any([args.gui, args.terminal, args.telegram, args.both, args.worker, args.all, args.idle]):
        args.gui = True

    if args.idle:
        from idle_worker import main as idle_main
        idle_main()
        return

    if args.worker:
        from monaco_ai.external_learning import ExternalLearningWorker
        ExternalLearningWorker(settings, db, agent_count=args.agents).run_forever()
        return

    if args.all:
        from monaco_ai.external_learning import ExternalLearningWorker
        worker = ExternalLearningWorker(settings, db, agent_count=args.agents)
        worker_thread = threading.Thread(target=worker.run_forever, daemon=True)
        worker_thread.start()
        try:
            import subprocess
            subprocess.Popen([sys.executable, str(settings.root / "idle_worker.py")], cwd=str(settings.root))
        except Exception as exc:
            print("Idle watcher start warning:", exc)
        args.both = True

    telegram_controller = None
    if args.telegram or args.both:
        from monaco_ai.telegram_bot import MonacoTelegramBot, TelegramRuntimeController
        if args.both:
            telegram_controller = TelegramRuntimeController(settings, router)
            ok, msg = telegram_controller.start()
            print(msg)
            if not ok:
                print("Telegram start warning:", msg)
        else:
            MonacoTelegramBot(settings, router).run()
            return

    if args.terminal:
        terminal_loop(router)
        return

    if args.gui or args.both:
        from monaco_ai.gui import run_gui
        run_gui(settings, router, telegram_controller=telegram_controller, safe_mode=args.safe_mode)


if __name__ == "__main__":
    main()
