"""Store a validated scene calibration in the configured database."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db.database import AsyncSessionLocal
from backend.db.init_db import init_tables
from backend.service.scene_calibration_service import upsert_scene_calibration
from contracts.v1.forewarning import SceneCalibration


async def seed(source: Path, make_active: bool) -> str:
    calibration = SceneCalibration.model_validate_json(source.read_text(encoding="utf-8"))
    await init_tables()
    async with AsyncSessionLocal() as db:
        await upsert_scene_calibration(db, calibration, make_active=make_active)
    return calibration.scene_config_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a scene calibration to the configured database")
    parser.add_argument("source", type=Path)
    parser.add_argument("--active", action="store_true", help="make this the current calibration")
    args = parser.parse_args()
    scene_config_id = asyncio.run(seed(args.source, args.active))
    print(f"stored scene calibration: {scene_config_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
