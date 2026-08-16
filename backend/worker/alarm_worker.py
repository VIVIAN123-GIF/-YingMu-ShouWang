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
from backend.service.algorithm_task_service import (
    claim_next_algorithm_task,
    process_algorithm_task,
)
from backend.service.recovery_scheduler_service import advance_one_due_event


logger = logging.getLogger("backend.alarm_worker")


async def run_once() -> bool:
    processed = False
    async with AsyncSessionLocal() as db:
        task = await claim_next_task(db)
        if task is not None:
            result = await process_claimed_task(db, task)
            logger.info(
                "alarm_capture_processed task_id=%s status=%s attempt_count=%s",
                result.task_id,
                result.status,
                result.attempt_count,
            )
            processed = True
        else:
            task = await claim_next_algorithm_task(db)
            if task is not None:
                result = await process_algorithm_task(db, task)
                logger.info(
                    "alarm_algorithm_processed task_id=%s status=%s attempt_count=%s",
                    result.task_id,
                    result.status,
                    result.algorithm_attempt_count,
                )
                processed = True
    async with AsyncSessionLocal() as db:
        transition = await advance_one_due_event(db)
        if transition is not None:
            logger.info(
                "risk_state_advanced event_id=%s next_status=%s matched_rule=%s",
                transition["event"]["event_id"] if transition.get("event") else None,
                transition.get("next_status"),
                transition.get("matched_rule"),
            )
            processed = True
    return processed


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
