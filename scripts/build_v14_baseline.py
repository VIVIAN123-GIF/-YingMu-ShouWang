"""Build and extract the three-date v1.4 supplemental personal baseline."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.v1.algorithm import AlgorithmJob, AlgorithmModule, MediaType  # noqa: E402
from contracts.v1.gait_adapter_v14 import run as run_gait  # noqa: E402
from scripts.supplemental_validation_v14 import safe_output  # noqa: E402


DAY_DATES = {"D1": "2026-08-17", "D2": "2026-08-18", "D3": "2026-08-19"}
EXCLUDED = {"D3_WALK_03_left_to_right.mp4": "VALID_FRAME_RATIO_0.693_BELOW_0.70"}
METRICS = {
    "rise_duration_s": ("rise_duration", "rise_duration_baseline_sample", "second"),
    "trunk_sway_angle_deg": ("trunk_sway", "trunk_sway_baseline_sample", "degree"),
    "step_speed_norm_s": ("relative_gait_speed", "gait_stability_baseline_sample", "norm_per_second"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new(path: Path, payload: object) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def container_creation_time(path: Path) -> str | None:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    value = completed.stdout.strip()
    return value or None


def create_manifest(
    media_root: Path, output: Path, *, participant_id: str,
    authorization_record_id: str, retention_until: str,
) -> dict[str, Any]:
    output = safe_output(output)
    files = sorted(media_root.glob("D*.mp4"))
    if len(files) != 18:
        raise ValueError(f"expected 18 D1-D3 videos, found {len(files)}")
    records = []
    for path in files:
        day = path.name.split("_", 1)[0]
        if day not in DAY_DATES:
            raise ValueError(f"unexpected baseline filename: {path.name}")
        embedded = container_creation_time(path)
        watermark_date = DAY_DATES[day]
        embedded_date = embedded[:10] if embedded else None
        records.append({
            "clip_id": path.stem,
            "participant_id": participant_id,
            "record_role": "BASELINE",
            "ground_truth": "NORMAL_CONTROL",
            "capture_date": watermark_date,
            "capture_date_source": "VISIBLE_WATERMARK_MANUALLY_VERIFIED",
            "container_creation_time": embedded,
            "container_timestamp_conflict": embedded_date != watermark_date,
            "media_relpath": path.name,
            "sha256": sha256_file(path),
            "byte_size": path.stat().st_size,
            "validity": "EXCLUDED" if path.name in EXCLUDED else "VALID",
            "exclusion_reason": EXCLUDED.get(path.name),
            "device_model": "EZVIZ_C6C",
            "device_ref": "supplemental-device-01",
            "camera_position_id": "supplemental-fixed-position-01",
            "authorization_record_id": authorization_record_id,
            "retention_until": retention_until,
            "source_mode": "RECORDED_REPLAY",
            "simulated": True,
        })
    payload = {
        "schema_version": "supplemental-baseline-manifest/1.0",
        "status": "LOCKABLE",
        "ruleset_version": "ruleset-v1.4",
        "participant_id": participant_id,
        "calendar_dates": list(DAY_DATES.values()),
        "record_count": 18,
        "valid_record_count": 17,
        "excluded_record_count": 1,
        "records": records,
        "claim_boundary": "Three visible-watermark dates support PROVISIONAL, never STABLE, baseline status.",
    }
    write_new(output, payload)
    return payload


def _metric_allowed(filename: str, feature_name: str) -> bool:
    if feature_name == "rise_duration_s":
        return "_RISE_" in filename
    if feature_name == "step_speed_norm_s":
        return "_WALK_" in filename
    return True


async def _extract_record(media_root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = (media_root / record["media_relpath"]).resolve()
    path.relative_to(media_root.resolve())
    if sha256_file(path) != record["sha256"]:
        raise ValueError(f"media hash mismatch: {record['clip_id']}")
    job = AlgorithmJob(
        schema_version="algorithm-job/1.0", job_id=f"baseline-v14-{record['clip_id']}",
        correlation_id=f"baseline-v14-{record['clip_id']}",
        resident_id=f"resident-{record['participant_id'].lower()}", asset_id=f"asset-{record['clip_id']}",
        media_type=MediaType.VIDEO, media_locator=str(path),
        captured_at=f"{record['capture_date']}T12:00:00+08:00",
        source_mode="RECORDED_REPLAY", simulated=True, location="living_room",
        camera_position_id=record["camera_position_id"],
        scene_config_id="supplemental-v14-fixed-scene", requested_modules=[AlgorithmModule.GAIT],
        deadline_ms=120000,
    )
    batch = await run_gait(job)
    features = {item.feature_name: item.feature_value for item in batch.observations}
    quality_pass = (
        record["validity"] == "VALID"
        and batch.status.value not in {"FAILED", "LOW_QUALITY"}
        and float(features.get("valid_frame_ratio", 0.0)) >= 0.70
    )
    samples = []
    for feature_name, (metric, evidence_type, unit) in METRICS.items():
        value = features.get(feature_name)
        if quality_pass and _metric_allowed(record["media_relpath"], feature_name) and isinstance(value, (int, float)):
            observation_id = f"obs-baseline-v14-{record['clip_id']}-{metric}"
            samples.append({
                "metric": metric, "value": float(value), "feature_name": feature_name,
                "observation": {
                    "schema_version": "1.0", "observation_id": observation_id,
                    "resident_id": job.resident_id, "timestamp": job.captured_at.isoformat(),
                    "source": "gait_adapter_v14", "feature_name": feature_name,
                    "feature_value": float(value), "unit": unit, "location": "living_room",
                    "confidence": 0.9, "data_quality": float(features["valid_frame_ratio"]),
                    "source_mode": "RECORDED_REPLAY", "asset_id": job.asset_id, "simulated": True,
                    "metadata": {"baseline_admission": "HUMAN_CONFIRMED_NORMAL_CONTROL"},
                },
                "evidence": {
                    "schema_version": "1.0", "evidence_id": f"evi-baseline-v14-{record['clip_id']}-{metric}",
                    "observation_ids": [observation_id], "resident_id": job.resident_id,
                    "timestamp": job.captured_at.isoformat(), "risk_domain": "FALL",
                    "evidence_type": evidence_type, "severity": 0.0, "confidence": 0.9,
                    "data_quality": float(features["valid_frame_ratio"]), "baseline_value": None,
                    "current_value": float(value), "baseline_deviation": None, "time_scale": "LONG",
                    "location": "living_room", "explanation": "Human-confirmed normal-control sample admitted to the v1.4 baseline.",
                    "adapter_version": "baseline-importer-v1.4", "source_mode": "RECORDED_REPLAY", "simulated": True,
                },
            })
    return {
        "clip_id": record["clip_id"], "capture_date": record["capture_date"],
        "validity": record["validity"], "adapter_status": batch.status.value,
        "quality_gate_status": batch.diagnostics.get("quality_gate_status"),
        "valid_frame_ratio": features.get("valid_frame_ratio"), "admitted": quality_pass,
        "quality_metrics": {
            name: features.get(name)
            for name in (
                "feet_visibility_mean", "feet_low_visibility_ratio",
                "core_low_visibility_ratio", "core_low_visibility_max_consecutive_s",
                "illumination_norm", "multi_person_frame_ratio",
                "multi_person_max_consecutive_s", "locomotion_duration_s",
            )
        },
        "samples": samples, "diagnostics": batch.diagnostics,
    }


def extract(manifest_path: Path, media_root: Path, output_dir: Path) -> dict[str, Any]:
    output_dir = safe_output(output_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "supplemental-baseline-manifest/1.0":
        raise ValueError("invalid supplemental baseline manifest")
    records = [asyncio.run(_extract_record(media_root, record)) for record in manifest["records"]]
    values: dict[str, list[tuple[str, float]]] = {metric: [] for metric, *_ in METRICS.values()}
    for record in records:
        for sample in record["samples"]:
            values[sample["metric"]].append((record["capture_date"], sample["value"]))
    baselines = {}
    for metric, samples in values.items():
        raw = [value for _, value in samples]
        days = sorted({day for day, _ in samples})
        center = statistics.median(raw) if raw else None
        mad = statistics.median(abs(value - center) for value in raw) if raw else None
        status = "PROVISIONAL" if len(days) >= 3 else "INSUFFICIENT"
        baselines[metric] = {
            "median": center, "mad": mad, "sample_count": len(raw),
            "distinct_days": len(days), "dates": days, "status": status,
        }
    overall = "PROVISIONAL" if all(item["status"] == "PROVISIONAL" for item in baselines.values()) else "INSUFFICIENT"
    payload = {
        "schema_version": "supplemental-baseline-results/1.0",
        "status": "COMPLETE", "ruleset_version": "ruleset-v1.4",
        "participant_id": manifest["participant_id"], "baseline_status": overall,
        "lookback_days": 30, "provisional_target_days": 3, "stable_target_days": 7,
        "manifest_sha256": sha256_file(manifest_path), "records": records,
        "baselines": baselines,
        "claim_boundary": "PROVISIONAL three-date controlled baseline; not a stable longitudinal or clinical baseline.",
    }
    output_dir.mkdir(parents=True)
    (output_dir / "baseline-results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['media_relpath']}" for record in manifest["records"]) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    manifest = sub.add_parser("manifest")
    manifest.add_argument("--media-root", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--participant-id", default="SV01")
    manifest.add_argument("--authorization-record-id", default="SV14-AUTH-PRIVATE-001")
    manifest.add_argument("--retention-until", default="2027-08-31T23:59:59+08:00")
    extraction = sub.add_parser("extract")
    extraction.add_argument("--manifest", type=Path, required=True)
    extraction.add_argument("--media-root", type=Path, required=True)
    extraction.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "manifest":
        result = create_manifest(args.media_root.resolve(), args.output.resolve(), participant_id=args.participant_id, authorization_record_id=args.authorization_record_id, retention_until=args.retention_until)
    else:
        result = extract(args.manifest.resolve(), args.media_root.resolve(), args.output_dir.resolve())
    print(json.dumps({key: result[key] for key in result if key not in {"records", "baselines"}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
