"""Enqueue an authorized local MP4 without exposing its private path."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _captured_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("captured-at must be an ISO 8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("captured-at must include a timezone")
    return parsed


async def _run(args: argparse.Namespace) -> dict[str, object]:
    from backend.db.database import AsyncSessionLocal
    from backend.db.init_db import init_tables
    from backend.service.recorded_replay_ingest_service import enqueue_recorded_replay

    await init_tables()
    async with AsyncSessionLocal() as db:
        return await enqueue_recorded_replay(
            db,
            input_path=args.input,
            resident_id=args.resident_id,
            captured_at=args.captured_at,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Privately ingest and enqueue one authorized MP4 replay.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--resident-id", required=True)
    parser.add_argument("--captured-at", type=_captured_at, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        from backend.service.errors import ServiceError
        from backend.service.recorded_replay_ingest_service import RecordedReplayIngestError

        if isinstance(exc, (RecordedReplayIngestError, ServiceError)):
            print(f"error={exc.code}", file=sys.stderr)
            return 1
        print(f"error=REPLAY_ENQUEUE_FAILED type={type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
