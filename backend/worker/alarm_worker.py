"""Run durable Ezviz alarm processing.

Usage:
    python -m backend.worker.alarm_worker
    python -m backend.worker.alarm_worker --once
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from backend.db.database import AsyncSessionLocal
from backend.db.init_db import init_tables
from backend.service.alarm_task_service import claim_next_task, process_claimed_task


logger = logging.getLogger("backend.alarm_worker")


async def run_once() -> bool:
    async with AsyncSessionLocal() as db:
        task = await claim_next_task(db)
        if task is None:
            return False
        result = await process_claimed_task(db, task)
        logger.info(
            "alarm_task_processed task_id=%s status=%s attempt_count=%s",
            result.task_id,
            result.status,
            result.attempt_count,
        )
        return True


async def run(*, once: bool, poll_seconds: float) -> int:
    await init_tables()
    while True:
        processed = await run_once()
        if once:
            return 0
        if not processed:
            await asyncio.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Process queued Ezviz alarm tasks.")
    parser.add_argument("--once", action="store_true", help="Process at most one due task and exit.")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(run(once=args.once, poll_seconds=args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
