from __future__ import annotations

import argparse
from pathlib import Path

from monaco_ai.config import ensure_dirs, load_settings
from monaco_ai.db import MonacoDB
from monaco_ai.external_learning import ExternalLearningWorker
from monaco_ai.general_knowledge_seed import ensure_general_business_knowledge


def main() -> None:
    parser = argparse.ArgumentParser(description="M0N4C0 external learning worker")
    parser.add_argument("--agents", type=int, default=2, help="Aantal parallelle research agents")
    parser.add_argument("--poll", type=float, default=2.0, help="Seconden tussen queue checks")
    parser.add_argument("--low-llm", action="store_true", help="Minder LLM-samenvattingen om LM Studio/GPU rustiger te houden")
    args = parser.parse_args()

    settings = load_settings(Path(__file__).resolve().parent)
    ensure_dirs(settings)
    db = MonacoDB(settings.db_path)
    ensure_general_business_knowledge(db)
    worker = ExternalLearningWorker(settings, db, agent_count=args.agents, poll_interval=args.poll, low_llm_mode=args.low_llm)
    worker.run_forever()


if __name__ == "__main__":
    main()
