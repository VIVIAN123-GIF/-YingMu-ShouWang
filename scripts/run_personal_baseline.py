"""Run the real GAIT adapter over the three-participant baseline package.

The baseline package is private input.  This command verifies the package and
each media hash before extraction, keeps participants isolated, and writes only
redacted feature records and aggregate summaries.  It never runs P03 risk
evaluation and never upgrades provisional labels to human-confirmed truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EXPECTED_COUNTS = {"P01": 8, "P02": 8, "P03": 8}
EXPECTED_SCENARIOS = {
    "BASE_NORMAL_WALK_L2R",
    "BASE_NORMAL_WALK_R2L",
    "BASE_SIT_RISE_STABLE",
    "BASE_WALK_STOP_TURN",
}
NUMERIC_FEATURES = {
    "com_offset_norm",
    "step_speed_norm_s",
    "step_asymmetry_ratio",
    "turn_angular_velocity_deg_s",
    "support_distance_norm",
    "stable_posture_duration",
    "stable_trunk_angle_deg",
    "valid_frame_ratio",
    "post_rise_sway_reversal_count",
    "trunk_sway_angle_deg",
    "rise_duration_s",
    "post_rise_pelvis_lateral_excursion_norm",
    "post_rise_support_width_change_norm",
    "post_rise_compensatory_step_count",
    "post_rise_tracking_ratio",
    "post_rise_orientation_quality",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_package(package_root: Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = package_root / "baseline-manifest.json"
    if not manifest_path.is_file():
        manifest_path = package_root / "capture-manifest.json"
    if not manifest_path.is_file():
        candidates = list(package_root.rglob("baseline-manifest.json")) + list(package_root.rglob("capture-manifest.json"))
        if len(candidates) != 1:
            raise ValueError("baseline/capture manifest was not found uniquely")
        manifest_path = candidates[0]
        package_root = manifest_path.parent
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("BASELINE_MANIFEST_INVALID") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") not in {
        "three-participant-personal-baseline-package/1.0",
        "three-participant-final-package/1.0",
    }:
        raise ValueError("BASELINE_MANIFEST_INVALID")
    records = payload.get("records")
    if payload.get("schema_version") == "three-participant-final-package/1.0":
        records = [record for record in records or [] if isinstance(record, dict) and record.get("record_role") == "BASELINE"]
        # The final package manifest counts all 96 clips; baseline extraction
        # operates on the filtered 24 baseline records only.
        participant_counts = {
            participant: sum(1 for record in records if record.get("participant_id") == participant)
            for participant in EXPECTED_COUNTS
        }
        payload = {**payload, "records": records, "participant_counts": participant_counts}
    if not isinstance(records, list) or len(records) != 24:
        raise ValueError("BASELINE_MANIFEST_RECORD_COUNT_INVALID")
    if payload.get("participant_counts") != EXPECTED_COUNTS:
        raise ValueError("BASELINE_MANIFEST_PARTICIPANT_COUNTS_INVALID")
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("BASELINE_RECORD_INVALID")
        required = {"slot_id", "participant_id", "scenario_id", "package_relpath", "sha256", "capture_date", "dataset_split"}
        if not required.issubset(record):
            raise ValueError("BASELINE_RECORD_FIELDS_INVALID")
        slot = str(record["slot_id"])
        if slot in seen:
            raise ValueError("BASELINE_DUPLICATE_SLOT")
        seen.add(slot)
        if record["participant_id"] not in EXPECTED_COUNTS or record["scenario_id"] not in EXPECTED_SCENARIOS:
            raise ValueError("BASELINE_RECORD_PROTOCOL_INVALID")
    return manifest_path, payload


def process_record(package_root: Path, record: dict[str, Any], model_sha256: str) -> dict[str, Any]:
    from contracts.v1.gait_video import GaitVideoError, extract_gait_features

    relative = Path(str(record["package_relpath"]))
    path = (package_root / relative).resolve()
    try:
        path.relative_to(package_root.resolve())
    except ValueError:
        return {"clip_id": record["slot_id"], "participant_id": record["participant_id"], "scenario_id": record["scenario_id"], "status": "FAILED", "error_code": "MEDIA_PATH_OUTSIDE_PACKAGE"}
    if not path.is_file():
        return {"clip_id": record["slot_id"], "participant_id": record["participant_id"], "scenario_id": record["scenario_id"], "status": "FAILED", "error_code": "MEDIA_MISSING"}
    actual_hash = sha256_file(path)
    if actual_hash.lower() != str(record["sha256"]).lower():
        return {"clip_id": record["slot_id"], "participant_id": record["participant_id"], "scenario_id": record["scenario_id"], "status": "FAILED", "error_code": "MEDIA_HASH_MISMATCH", "asset_sha256": actual_hash}
    try:
        features, diagnostics = extract_gait_features(path)
    except (GaitVideoError, OSError, ValueError) as exc:
        return {"clip_id": record["slot_id"], "participant_id": record["participant_id"], "scenario_id": record["scenario_id"], "status": "FAILED", "error_code": str(exc)[:64], "asset_sha256": actual_hash}
    selected = {key: value for key, value in features.items() if key in NUMERIC_FEATURES or key in {"assessment_status", "assessment_reason_code", "sit_to_stand_transition_confirmed", "post_rise_locomotion_detected"}}
    return {
        "clip_id": record["slot_id"],
        "participant_id": record["participant_id"],
        "scenario_id": record["scenario_id"],
        "dataset_split": record["dataset_split"],
        "capture_date": record["capture_date"],
        "asset_sha256": actual_hash,
        "status": "SUCCESS",
        "features": selected,
        "diagnostics": {key: value for key, value in diagnostics.items() if key not in {"pose_model_path", "media_path", "source_path"}},
        "model_sha256": model_sha256,
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_group: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_group.setdefault(f"{record['participant_id']}::{record['scenario_id']}", []).append(record)
    groups: dict[str, Any] = {}
    for key, items in sorted(by_group.items()):
        successes = [item for item in items if item["status"] == "SUCCESS"]
        feature_summary: dict[str, Any] = {}
        for feature in sorted(NUMERIC_FEATURES):
            values = [item["features"].get(feature) for item in successes if isinstance(item.get("features", {}).get(feature), (int, float))]
            if values:
                feature_summary[feature] = {"n": len(values), "median": round(float(median(values)), 6), "min": round(float(min(values)), 6), "max": round(float(max(values)), 6)}
        assessment_status_counts: dict[str, int] = {}
        for item in successes:
            status = str(item.get("features", {}).get("assessment_status", "UNSPECIFIED"))
            assessment_status_counts[status] = assessment_status_counts.get(status, 0) + 1
        groups[key] = {
            "record_count": len(items),
            "success_count": len(successes),
            "failed_count": len(items) - len(successes),
            "assessment_status_counts": assessment_status_counts,
            "features": feature_summary,
        }
    return groups


def run(args: argparse.Namespace) -> dict[str, Any]:
    package_root = Path(args.package_root).resolve()
    manifest_path, manifest = load_package(package_root)
    model = Path(args.model).resolve()
    if not model.is_file():
        raise ValueError("POSE_MODEL_NOT_FOUND")
    os.environ["YINGMU_GAIT_POSE_MODEL"] = str(model)
    model_hash = sha256_file(model)
    manifest_hash = sha256_file(manifest_path)
    records = list(manifest["records"])
    workers = max(1, min(int(args.workers), 4))
    processed: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(process_record, package_root, record, model_hash) for record in records]
        for future in as_completed(futures):
            try:
                processed.append(future.result())
            except Exception as exc:  # keep one bad clip from hiding the batch result
                processed.append({
                    "clip_id": "UNKNOWN",
                    "participant_id": "UNKNOWN",
                    "scenario_id": "UNKNOWN",
                    "status": "FAILED",
                    "error_code": str(exc)[:64],
                })
    processed.sort(key=lambda item: str(item["clip_id"]))
    success_count = sum(item["status"] == "SUCCESS" for item in processed)
    label_statuses = sorted({str(record.get("label_status", "UNSPECIFIED")) for record in records})
    readiness: dict[str, str] = {}
    for participant in EXPECTED_COUNTS:
        participant_records = [item for item in processed if item.get("participant_id") == participant]
        statuses = [str(item.get("features", {}).get("assessment_status", "FAILED")) for item in participant_records if item.get("status") == "SUCCESS"]
        readiness[participant] = "READY" if len(participant_records) == EXPECTED_COUNTS[participant] and all(status in {"VALID", "NO_TRANSITION"} for status in statuses) else "PARTIAL"
    payload = {
        "schema_version": "three-participant-personal-baseline-results/1.0",
        "status": "COMPLETE" if success_count == 24 else "INCOMPLETE",
        "label_status": "PROVISIONAL" if any("PROVISIONAL" in item for item in label_statuses) else "CONFIRMED_OR_UNSPECIFIED",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "package_manifest_sha256": manifest_hash,
        "model_sha256": model_hash,
        "participant_counts": EXPECTED_COUNTS,
        "record_count": len(processed),
        "success_count": success_count,
        "failure_count": len(processed) - success_count,
        "baseline_readiness": readiness,
        "label_statuses": label_statuses,
        "records_sha256": sha256_json(processed),
        "records": processed,
        "summaries": summarize(processed),
        "claim_boundary": "Personal baseline feature extraction on three controlled adult-participant replay sets; not clinical validation and not P03 test accuracy.",
    }
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "baseline-results.json", payload)
    lines = ["# 三参与者个人基线提取结果", "", f"状态：`{payload['status']}`", f"标签状态：`{payload['label_status']}`", "", f"- 记录：{len(processed)}", f"- 成功：{success_count}", f"- 失败：{len(processed) - success_count}", f"- 参与者基线就绪度：P01 `{readiness['P01']}`，P02 `{readiness['P02']}`，P03 `{readiness['P03']}`", f"- manifest SHA-256：`{manifest_hash}`", f"- 模型 SHA-256：`{model_hash}`", "", "本结果只用于建立 P01/P02/P03 分离的个人特征基线，不用于直接宣称临床有效性或 P03 测试集 Precision/Recall/F1。详细数值和失败原因见同目录 `baseline-results.json`。P02 存在坐起评估质量降级，需在正式建模前复核机位/动作真值。", ""]
    (output_dir / "baseline-results.md").write_text("\n".join(lines), encoding="utf-8")
    return {key: payload[key] for key in ("status", "label_status", "record_count", "success_count", "failure_count", "records_sha256", "output_dir")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract GAIT features for the private P01/P02/P03 personal baseline package.")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model", default=str(ROOT / "models" / "pose_landmarker_heavy.task"))
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    try:
        result = run(args)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
