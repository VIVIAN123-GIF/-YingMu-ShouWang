"""Reanalyze legacy P01/P02 media with v1.4 without touching frozen results."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.v1.algorithm import AlgorithmJob, AlgorithmModule, MediaType  # noqa: E402
from contracts.v1.gait_adapter_v14 import run as run_gait  # noqa: E402
from scripts.supplemental_validation_v14 import safe_output, sha256_file  # noqa: E402


FEATURES = (
    "rise_duration_s", "trunk_sway_angle_deg", "step_speed_norm_s",
    "step_asymmetry_ratio", "valid_frame_ratio", "locomotion_duration_s",
    "feet_visibility_mean", "illumination_norm",
)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return round(ordered[low] * (1 - weight) + ordered[high] * weight, 6)


def _distribution(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "min": round(min(values), 6) if values else None,
        "p25": _percentile(values, 0.25),
        "median": round(statistics.median(values), 6) if values else None,
        "p75": _percentile(values, 0.75),
        "max": round(max(values), 6) if values else None,
    }


def _load_rows(manifest: Path, media_root: Path) -> list[dict[str, str]]:
    with manifest.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = [
            row for row in csv.DictReader(stream)
            if row.get("participant_id") in {"P01", "P02"}
            and row.get("validity") == "VALID"
        ]
    if len(rows) != 64:
        raise ValueError(f"expected 64 valid P01/P02 records, found {len(rows)}")
    for row in rows:
        path = (media_root / row["video_relpath"]).resolve()
        path.relative_to(media_root.resolve())
        if not path.is_file():
            raise ValueError(f"missing media: {row['clip_id']}")
        if sha256_file(path) != row["sha256"]:
            raise ValueError(f"media hash mismatch: {row['clip_id']}")
    return rows


async def _run_one(row: dict[str, str], media_root: Path) -> dict[str, Any]:
    path = (media_root / row["video_relpath"]).resolve()
    job = AlgorithmJob(
        schema_version="algorithm-job/1.0",
        job_id=f"v14-reanalysis-{row['clip_id']}",
        correlation_id=f"v14-reanalysis-{row['clip_id']}",
        resident_id=f"resident-{row['participant_id'].lower()}",
        asset_id=f"asset-{row['clip_id']}",
        media_type=MediaType.VIDEO,
        media_locator=str(path),
        captured_at=f"{row['capture_date']}T12:00:00+08:00",
        source_mode="RECORDED_REPLAY",
        simulated=True,
        location="living_room",
        camera_position_id=row["camera_position_id"],
        scene_config_id="legacy-three-participant-fixed-scene",
        requested_modules=[AlgorithmModule.GAIT],
        deadline_ms=120000,
    )
    batch = await run_gait(job)
    features = {
        item.feature_name: item.feature_value
        for item in batch.observations
        if item.feature_name in FEATURES
    }
    legacy = batch.diagnostics.get("legacy_full_clip_metrics", {})
    return {
        "clip_id": row["clip_id"],
        "participant_id": row["participant_id"],
        "dataset_split": row["dataset_split"],
        "record_role": row["record_role"],
        "scenario_id": row["scenario_id"],
        "status": batch.status.value,
        "features": features,
        "legacy_full_clip_metrics": legacy,
        "evidence_types": [item.evidence_type for item in batch.evidences],
        "evidence_severity": {
            item.evidence_type: item.severity for item in batch.evidences
        },
        "quality_gate_status": batch.diagnostics.get("quality_gate_status"),
        "quality_gate_reasons": batch.diagnostics.get("quality_gate_reasons", []),
    }


async def _run_all(
    rows: list[dict[str, str]], media_root: Path, workers: int,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(workers)

    async def guarded(index: int, row: dict[str, str]) -> tuple[int, dict[str, Any]]:
        async with semaphore:
            record = await _run_one(row, media_root)
        print(json.dumps({
            "manifest_index": index + 1,
            "total": len(rows),
            "clip_id": row["clip_id"],
            "status": record["status"],
        }, ensure_ascii=False), flush=True)
        return index, record

    completed = await asyncio.gather(*(
        guarded(index, row) for index, row in enumerate(rows)
    ))
    return [record for _, record in sorted(completed)]


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[f"{record['participant_id']}:{record['record_role']}"].append(record)
    distributions = {}
    for name, items in groups.items():
        feature_stats = {}
        for feature in FEATURES:
            values = [
                float(item["features"][feature])
                for item in items
                if isinstance(item["features"].get(feature), (int, float))
            ]
            feature_stats[feature] = _distribution(values)
        legacy_speed = [
            float(item["legacy_full_clip_metrics"]["step_speed_norm_s"])
            for item in items
            if isinstance(item["legacy_full_clip_metrics"].get("step_speed_norm_s"), (int, float))
        ]
        active_speed = [
            float(item["features"]["step_speed_norm_s"])
            for item in items
            if isinstance(item["features"].get("step_speed_norm_s"), (int, float))
        ]
        distributions[name] = {
            "record_count": len(items),
            "adapter_status_counts": dict(Counter(item["status"] for item in items)),
            "quality_gate_failure_count": sum(
                item["quality_gate_status"] == "FAILED" for item in items
            ),
            "evidence_type_counts": dict(Counter(
                evidence_type
                for item in items
                for evidence_type in item["evidence_types"]
            )),
            "features": feature_stats,
            "speed_semantics_comparison": {
                "legacy_whole_clip": _distribution(legacy_speed),
                "v14_active_locomotion": _distribution(active_speed),
            },
        }
    return distributions


def run(
    manifest: Path, media_root: Path, output_dir: Path, *, workers: int = 2,
) -> dict[str, Any]:
    output_dir = safe_output(output_dir)
    if workers < 1 or workers > 8:
        raise ValueError("workers must be between 1 and 8")
    rows = _load_rows(manifest, media_root)
    records = asyncio.run(_run_all(rows, media_root, workers))
    payload = {
        "schema_version": "p01-p02-v14-reanalysis/1.0",
        "status": "COMPLETE",
        "ruleset_version": "ruleset-v1.4",
        "participants": ["P01", "P02"],
        "record_count": len(records),
        "purpose": "Calibration/validation feature-distribution audit only.",
        "not_formal_test": True,
        "p03_modified": False,
        "new_supplemental_media_inspected": False,
        "execution": {
            "workers": workers,
            "per_clip_model_and_parameters_identical": True,
            "result_order": "manifest_order",
        },
        "bindings": {
            "manifest_sha256": sha256_file(manifest),
            "ruleset_sha256": sha256_file(
                ROOT / "contracts/v1/rulesets/ruleset-v1.4.json"
            ),
            "model_sha256": sha256_file(ROOT / "models/pose_landmarker_heavy.task"),
            "executor_sha256": sha256_file(Path(__file__)),
        },
        "distributions": _summarize(records),
        "records": records,
        "claim_boundary": "Legacy P01/P02 controlled healthy-adult media; not P03, not supplemental TEST, and not clinical validation.",
    }
    output_dir.mkdir(parents=True)
    result = output_dir / "p01-p02-v14-reanalysis.json"
    result.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        f"{sha256_file(result)}  {result.name}\n", encoding="utf-8"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    payload = run(
        args.manifest.resolve(), args.media_root.resolve(), args.output_dir.resolve(),
        workers=args.workers,
    )
    print(json.dumps({
        "status": payload["status"],
        "record_count": payload["record_count"],
        "ruleset_version": payload["ruleset_version"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
