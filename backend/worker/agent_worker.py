"""Run durable agent explanation jobs in a process separate from risk decisions."""

from __future__ import annotations

import argparse
import asyncio
import logging

from backend.db.database import AsyncSessionLocal
from backend.db.init_db import init_tables
from backend.service.agent_explanation_job_service import (
    claim_next_explanation_job,
    process_explanation_job,
)


logger = logging.getLogger("backend.agent_worker")


async def run_once() -> bool:
    async with AsyncSessionLocal() as db:
        job = await claim_next_explanation_job(db)
        if job is None:
            return False
        result = await process_explanation_job(db, job)
        logger.info(
            "agent_explanation_processed request_id=%s event_id=%s status=%s attempts=%s",
            result.request_id,
            result.event_id,
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
    parser = argparse.ArgumentParser(description="Process queued agent explanation jobs.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(run(once=args.once, poll_seconds=args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
