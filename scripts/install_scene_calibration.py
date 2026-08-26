"""Validate and install a sanitized fixed-camera scene calibration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from contracts.v1.forewarning import SceneCalibration


def install(source: Path, destination_root: Path) -> Path:
    calibration = SceneCalibration.model_validate_json(source.read_text(encoding="utf-8"))
    root = destination_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / f"{calibration.scene_config_id}.json").resolve()
    if root not in target.parents:
        raise ValueError("scene_config_id resolves outside destination root")
    temporary = root / f".{target.name}.tmp"
    payload = json.dumps(calibration.model_dump(mode="json"), ensure_ascii=False, indent=2)
    temporary.write_text(payload + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and install SceneCalibration JSON")
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, default=Path("scene-calibrations"))
    args = parser.parse_args()
    target = install(args.source, args.destination)
    print(json.dumps({"status": "INSTALLED", "scene_config_id": target.stem}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
