"""Prepare and audit the three-participant final experiment.

This command never invents measurements. It creates protocol templates and only
produces final metrics after the capture manifest, P03 lock, rule freeze, and
prediction records pass their respective gates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


PARTICIPANT_SPLITS = {
    "P01": "CALIBRATION",
    "P02": "VALIDATION",
    "P03": "TEST",
}
LABELS = {"RISK_PRECURSOR", "NORMAL_CONTROL"}
VALIDITIES = {"VALID", "ABORTED", "EXCLUDED"}
CONFIGS = {
    "A": "full_system",
    "B": "without_personal_baseline",
    "C": "short_term_only",
    "D": "without_quality_and_context_gate",
}


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    record_role: str
    ground_truth: str
    count: int
    planned_duration_seconds: int
    golden_first: bool = False


SCENARIOS = (
    Scenario("BASE_NORMAL_WALK_L2R", "BASELINE", "NORMAL_CONTROL", 2, 15),
    Scenario("BASE_NORMAL_WALK_R2L", "BASELINE", "NORMAL_CONTROL", 2, 15),
    Scenario("BASE_SIT_RISE_STABLE", "BASELINE", "NORMAL_CONTROL", 2, 20),
    Scenario("BASE_WALK_STOP_TURN", "BASELINE", "NORMAL_CONTROL", 2, 16),
    Scenario("POS_RAPID_RISE_SWAY", "EVALUATION", "RISK_PRECURSOR", 4, 25, True),
    Scenario("POS_SLOW_SMALL_STEP_SWAY", "EVALUATION", "RISK_PRECURSOR", 4, 15),
    Scenario("POS_ASYMMETRIC_STEP", "EVALUATION", "RISK_PRECURSOR", 4, 15),
    Scenario("NEG_NORMAL_RISE_WALK", "EVALUATION", "NORMAL_CONTROL", 4, 20),
    Scenario("NEG_RAPID_RISE_STABLE", "EVALUATION", "NORMAL_CONTROL", 4, 22),
    Scenario("NEG_BOUNDARY_NORMAL", "EVALUATION", "NORMAL_CONTROL", 4, 16),
)

MANIFEST_FIELDS = (
    "planned_slot_id",
    "clip_id",
    "participant_id",
    "capture_date",
    "scenario_id",
    "record_role",
    "repeat_index",
    "protocol_variant",
    "ground_truth",
    "event_start_ms",
    "event_end_ms",
    "lighting",
    "camera_position_id",
    "source_mode",
    "simulated",
    "authorization_record_id",
    "dataset_split",
    "validity",
    "exclusion_reason",
    "video_relpath",
    "sha256",
    "planned_duration_seconds",
    "notes",
)

PREDICTION_FIELDS = (
    "clip_id",
    "participant_id",
    "dataset_split",
    "config_id",
    "predicted_label",
    "detected_event_start_ms",
    "evidence_created_at_ms",
    "intervention_requested_at_ms",
    "notes",
)

STABILITY_FIELDS = (
    "run_id",
    "participant_id",
    "started_at",
    "ended_at",
    "source_mode",
    "total_risk_events",
    "false_alarms",
    "system_exceptions",
    "restarts",
    "unhandled_exceptions",
    "ruleset_version",
    "notes",
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, fields: Sequence[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def planned_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for participant, split in PARTICIPANT_SPLITS.items():
        for scenario in SCENARIOS:
            for repeat_index in range(1, scenario.count + 1):
                slot = f"{participant}-{scenario.scenario_id}-{repeat_index:02d}"
                golden = scenario.golden_first and repeat_index == 1
                rows.append({
                    "planned_slot_id": slot,
                    "clip_id": slot,
                    "participant_id": participant,
                    "capture_date": "",
                    "scenario_id": scenario.scenario_id,
                    "record_role": scenario.record_role,
                    "repeat_index": repeat_index,
                    "protocol_variant": "GOLDEN_115S" if golden else "STANDARD",
                    "ground_truth": scenario.ground_truth,
                    "event_start_ms": "",
                    "event_end_ms": "",
                    "lighting": "",
                    "camera_position_id": "C6c-pos01",
                    "source_mode": "RECORDED_REPLAY",
                    "simulated": "true",
                    "authorization_record_id": "",
                    "dataset_split": split,
                    "validity": "",
                    "exclusion_reason": "",
                    "video_relpath": "",
                    "sha256": "",
                    "planned_duration_seconds": 115 if golden else scenario.planned_duration_seconds,
                    "notes": "",
                })
    return rows


def expected_slots() -> dict[str, dict[str, object]]:
    return {str(row["planned_slot_id"]): row for row in planned_rows()}


def generate_manifest(output: Path) -> None:
    if output.exists():
        raise ValueError(f"refusing to overwrite existing manifest: {output}")
    write_csv(output, MANIFEST_FIELDS, planned_rows())


def _parse_date(value: str, field: str, clip_id: str, errors: list[str]) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{clip_id}: {field} must use YYYY-MM-DD")
        return None


def _parse_nonnegative_int(value: str, field: str, clip_id: str, errors: list[str]) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        errors.append(f"{clip_id}: {field} must be an integer")
        return None
    if parsed < 0:
        errors.append(f"{clip_id}: {field} must be non-negative")
    return parsed


def validate_manifest(
    manifest: Path,
    *,
    stage: str,
    media_root: Path | None = None,
) -> dict[str, object]:
    rows = read_csv(manifest)
    errors: list[str] = []
    warnings: list[str] = []
    slots = expected_slots()
    seen_clip_ids: set[str] = set()
    valid_by_slot: dict[str, list[dict[str, str]]] = {slot: [] for slot in slots}

    if not rows:
        errors.append("manifest is empty")
    missing_columns = set(MANIFEST_FIELDS) - (set(rows[0]) if rows else set())
    if missing_columns:
        errors.append(f"missing columns: {', '.join(sorted(missing_columns))}")

    for row_number, row in enumerate(rows, 2):
        clip_id = row.get("clip_id", "").strip() or f"row-{row_number}"
        if clip_id in seen_clip_ids:
            errors.append(f"duplicate clip_id: {clip_id}")
        seen_clip_ids.add(clip_id)
        slot_id = row.get("planned_slot_id", "").strip()
        expected = slots.get(slot_id)
        if expected is None:
            errors.append(f"{clip_id}: unknown planned_slot_id {slot_id!r}")
            continue
        for field in (
            "participant_id",
            "scenario_id",
            "record_role",
            "ground_truth",
            "dataset_split",
            "protocol_variant",
        ):
            if row.get(field, "").strip() != str(expected[field]):
                errors.append(f"{clip_id}: {field} does not match protocol slot {slot_id}")
        if row.get("source_mode", "").strip() != "RECORDED_REPLAY":
            errors.append(f"{clip_id}: source_mode must be RECORDED_REPLAY")
        if row.get("simulated", "").strip().lower() != "true":
            errors.append(f"{clip_id}: simulated must be true")

        validity = row.get("validity", "").strip()
        if stage == "template":
            if validity and validity not in VALIDITIES:
                errors.append(f"{clip_id}: invalid validity {validity!r}")
            continue
        if validity not in VALIDITIES:
            errors.append(f"{clip_id}: validity must be one of {sorted(VALIDITIES)}")
            continue
        if validity in {"ABORTED", "EXCLUDED"}:
            if not row.get("exclusion_reason", "").strip():
                errors.append(f"{clip_id}: {validity} rows require exclusion_reason")
            continue

        valid_by_slot[slot_id].append(row)
        required = (
            "capture_date",
            "event_start_ms",
            "event_end_ms",
            "lighting",
            "camera_position_id",
            "authorization_record_id",
            "video_relpath",
        )
        for field in required:
            if not row.get(field, "").strip():
                errors.append(f"{clip_id}: missing required field {field}")
        start = _parse_nonnegative_int(row.get("event_start_ms", ""), "event_start_ms", clip_id, errors)
        end = _parse_nonnegative_int(row.get("event_end_ms", ""), "event_end_ms", clip_id, errors)
        if start is not None and end is not None and end <= start:
            errors.append(f"{clip_id}: event_end_ms must be greater than event_start_ms")
        _parse_date(row.get("capture_date", ""), "capture_date", clip_id, errors)
        relpath = row.get("video_relpath", "").strip()
        if relpath and Path(relpath).is_absolute():
            errors.append(f"{clip_id}: video_relpath must be relative")
        if media_root is not None and relpath:
            video = (media_root / relpath).resolve()
            try:
                video.relative_to(media_root.resolve())
            except ValueError:
                errors.append(f"{clip_id}: video_relpath escapes media_root")
            else:
                if not video.is_file():
                    errors.append(f"{clip_id}: video file not found: {relpath}")
                elif row.get("sha256", "").strip() and sha256_file(video) != row["sha256"].strip().lower():
                    errors.append(f"{clip_id}: sha256 does not match video")

    if stage != "template":
        for slot_id, valid_rows in valid_by_slot.items():
            if len(valid_rows) != 1:
                errors.append(f"{slot_id}: expected exactly one VALID recording, found {len(valid_rows)}")
        for participant in PARTICIPANT_SPLITS:
            participant_rows = [
                row for row in rows
                if row.get("participant_id") == participant and row.get("validity") == "VALID"
            ]
            baseline_dates = {
                row.get("capture_date", "") for row in participant_rows if row.get("record_role") == "BASELINE"
            }
            evaluation_dates = {
                row.get("capture_date", "") for row in participant_rows if row.get("record_role") == "EVALUATION"
            }
            if not baseline_dates or not evaluation_dates:
                errors.append(f"{participant}: missing baseline or evaluation capture dates")
            if baseline_dates & evaluation_dates:
                errors.append(f"{participant}: baseline and evaluation must be captured on different dates")
            parsed_baseline = [date.fromisoformat(value) for value in baseline_dates if value]
            parsed_evaluation = [date.fromisoformat(value) for value in evaluation_dates if value]
            if parsed_baseline and parsed_evaluation and min(parsed_evaluation) <= min(parsed_baseline):
                errors.append(f"{participant}: evaluation capture must occur after baseline capture")
            golden = [
                row for row in participant_rows
                if row.get("protocol_variant") == "GOLDEN_115S"
            ]
            if len(golden) != 1:
                errors.append(f"{participant}: exactly one VALID GOLDEN_115S recording is required")

    valid_rows = [row for row in rows if row.get("validity") == "VALID"]
    summary = {
        "schema_version": "three-participant-protocol/1.0",
        "stage": stage,
        "status": "PASS" if not errors else "FAIL",
        "manifest": str(manifest),
        "row_count": len(rows),
        "valid_recording_count": len(valid_rows),
        "planned_slot_count": len(slots),
        "participant_counts": {
            participant: sum(1 for row in valid_rows if row.get("participant_id") == participant)
            for participant in PARTICIPANT_SPLITS
        },
        "errors": errors,
        "warnings": warnings,
    }
    return summary


def _require_pass(report: dict[str, object]) -> None:
    if report["status"] != "PASS":
        details = "\n".join(f"- {item}" for item in report["errors"])
        raise ValueError(f"validation failed:\n{details}")


def lock_test_set(manifest: Path, media_root: Path, output_dir: Path) -> dict[str, object]:
    report = validate_manifest(manifest, stage="captured", media_root=media_root)
    _require_pass(report)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"refusing to overwrite non-empty lock directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    media_output = output_dir / "media"
    locked_rows: list[dict[str, str]] = []
    files: list[dict[str, object]] = []
    for row in read_csv(manifest):
        if row["participant_id"] != "P03" or row["validity"] != "VALID":
            continue
        source = (media_root / row["video_relpath"]).resolve()
        suffix = source.suffix.lower() or ".mp4"
        relative = Path("media") / row["record_role"].lower() / f"{row['clip_id']}{suffix}"
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        digest = sha256_file(destination)
        locked = dict(row)
        locked["video_relpath"] = relative.as_posix()
        locked["sha256"] = digest
        locked_rows.append(locked)
        files.append({"clip_id": row["clip_id"], "path": relative.as_posix(), "sha256": digest, "bytes": destination.stat().st_size})
    locked_manifest = output_dir / "locked-manifest.csv"
    write_csv(locked_manifest, MANIFEST_FIELDS, locked_rows)
    lock_payload = {
        "schema_version": "three-participant-test-lock/1.0",
        "status": "LOCKED",
        "participant_id": "P03",
        "locked_at": now_iso(),
        "record_count": len(locked_rows),
        "baseline_count": sum(row["record_role"] == "BASELINE" for row in locked_rows),
        "evaluation_count": sum(row["record_role"] == "EVALUATION" for row in locked_rows),
        "locked_manifest": locked_manifest.name,
        "locked_manifest_sha256": sha256_file(locked_manifest),
        "files": files,
        "notice": "P03 media must not be processed before the final rule freeze is recorded.",
    }
    write_json(output_dir / "test-lock.json", lock_payload)
    (output_dir / "SHA256SUMS.txt").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in files),
        encoding="ascii",
    )
    return lock_payload


def verify_test_lock(lock_file: Path) -> dict[str, object]:
    payload = json.loads(lock_file.read_text(encoding="utf-8"))
    base = lock_file.parent
    errors: list[str] = []
    manifest = base / str(payload.get("locked_manifest", ""))
    if not manifest.is_file() or sha256_file(manifest) != payload.get("locked_manifest_sha256"):
        errors.append("locked manifest is missing or changed")
    for item in payload.get("files", []):
        path = base / item["path"]
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            errors.append(f"locked media is missing or changed: {item['path']}")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "payload": payload}


def freeze_rules(lock_file: Path, ruleset: Path, model: Path, output: Path, *, allow_dirty: bool) -> dict[str, object]:
    lock_report = verify_test_lock(lock_file)
    _require_pass(lock_report)
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain"], check=True, capture_output=True, text=True
    ).stdout.strip())
    if dirty and not allow_dirty:
        raise ValueError("git worktree is dirty; commit the final rules or pass --allow-dirty for a rehearsal")
    payload = {
        "schema_version": "three-participant-rule-freeze/1.0",
        "status": "FROZEN" if not dirty else "REHEARSAL_ONLY",
        "frozen_at": now_iso(),
        "git_commit": git_commit,
        "git_dirty": dirty,
        "test_lock_sha256": sha256_file(lock_file),
        "ruleset": {"path": str(ruleset), "sha256": sha256_file(ruleset)},
        "model": {"path": str(model), "sha256": sha256_file(model)},
        "test_execution_allowed": not dirty,
    }
    write_json(output, payload)
    return payload


def verify_freeze(freeze_file: Path, lock_file: Path) -> dict[str, object]:
    payload = json.loads(freeze_file.read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload.get("status") != "FROZEN" or not payload.get("test_execution_allowed"):
        errors.append("rule freeze is not a clean final freeze")
    if payload.get("test_lock_sha256") != sha256_file(lock_file):
        errors.append("rule freeze references a different test lock")
    for key in ("ruleset", "model"):
        item = payload.get(key, {})
        path = Path(str(item.get("path", "")))
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            errors.append(f"frozen {key} is missing or changed")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "payload": payload}


def generate_predictions(manifest: Path, output: Path) -> None:
    if output.exists():
        raise ValueError(f"refusing to overwrite existing prediction template: {output}")
    report = validate_manifest(manifest, stage="captured")
    _require_pass(report)
    rows: list[dict[str, object]] = []
    for row in read_csv(manifest):
        if row["validity"] != "VALID" or row["record_role"] != "EVALUATION":
            continue
        config_ids = CONFIGS if row["participant_id"] == "P03" else {"A": CONFIGS["A"]}
        for config_id in config_ids:
            rows.append({
                "clip_id": row["clip_id"],
                "participant_id": row["participant_id"],
                "dataset_split": row["dataset_split"],
                "config_id": config_id,
                "predicted_label": "",
                "detected_event_start_ms": "",
                "evidence_created_at_ms": "",
                "intervention_requested_at_ms": "",
                "notes": "",
            })
    write_csv(output, PREDICTION_FIELDS, rows)


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total == 0:
        return None
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def percentile(values: Sequence[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(float(ordered[lower]), 3)
    result = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(float(result), 3)


def calculate_metrics(records: Sequence[dict[str, object]]) -> dict[str, object]:
    tp = sum(row["ground_truth"] == "RISK_PRECURSOR" and row["predicted_label"] == "RISK_PRECURSOR" for row in records)
    tn = sum(row["ground_truth"] == "NORMAL_CONTROL" and row["predicted_label"] == "NORMAL_CONTROL" for row in records)
    fp = sum(row["ground_truth"] == "NORMAL_CONTROL" and row["predicted_label"] == "RISK_PRECURSOR" for row in records)
    fn = sum(row["ground_truth"] == "RISK_PRECURSOR" and row["predicted_label"] == "NORMAL_CONTROL" for row in records)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    window_hits = sum(bool(row["window_hit"]) for row in records if row["ground_truth"] == "RISK_PRECURSOR")
    positive_count = tp + fn
    latencies = [float(row["latency_ms"]) for row in records if row["latency_ms"] is not None]
    return {
        "sample_count": len(records),
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "precision": round(precision, 6),
        "precision_wilson_95": wilson_interval(tp, tp + fp),
        "recall": round(recall, 6),
        "recall_wilson_95": wilson_interval(tp, positive_count),
        "f1": round(f1, 6),
        "accuracy": round((tp + tn) / len(records), 6) if records else 0.0,
        "high_risk_window_recall": round(window_hits / positive_count, 6) if positive_count else 0.0,
        "latency_ms": {
            "count": len(latencies),
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "maximum": round(max(latencies), 3) if latencies else None,
        },
    }


def _int_or_none(value: str, field: str, key: str, errors: list[str]) -> int | None:
    if not value.strip():
        return None
    return _parse_nonnegative_int(value, field, key, errors)


def analyze_predictions(
    manifest: Path,
    predictions: Path,
    lock_file: Path,
    freeze_file: Path,
    output_dir: Path,
) -> dict[str, object]:
    manifest_report = validate_manifest(manifest, stage="captured")
    _require_pass(manifest_report)
    lock_report = verify_test_lock(lock_file)
    _require_pass(lock_report)
    freeze_report = verify_freeze(freeze_file, lock_file)
    _require_pass(freeze_report)
    manifest_rows = {
        row["clip_id"]: row for row in read_csv(manifest)
        if row["validity"] == "VALID" and row["record_role"] == "EVALUATION"
    }
    prediction_rows = read_csv(predictions)
    errors: list[str] = []
    joined: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for row in prediction_rows:
        clip_id = row.get("clip_id", "")
        config_id = row.get("config_id", "")
        key = (clip_id, config_id)
        if key in seen:
            errors.append(f"duplicate prediction: {clip_id}/{config_id}")
            continue
        seen.add(key)
        source = manifest_rows.get(clip_id)
        if source is None:
            errors.append(f"prediction references unknown evaluation clip: {clip_id}")
            continue
        expected_configs = set(CONFIGS) if source["participant_id"] == "P03" else {"A"}
        if config_id not in expected_configs:
            errors.append(f"{clip_id}: unexpected config_id {config_id}")
            continue
        predicted = row.get("predicted_label", "")
        if predicted not in LABELS:
            errors.append(f"{clip_id}/{config_id}: predicted_label must be one of {sorted(LABELS)}")
            continue
        detected = _int_or_none(row.get("detected_event_start_ms", ""), "detected_event_start_ms", clip_id, errors)
        evidence = _int_or_none(row.get("evidence_created_at_ms", ""), "evidence_created_at_ms", clip_id, errors)
        intervention = _int_or_none(row.get("intervention_requested_at_ms", ""), "intervention_requested_at_ms", clip_id, errors)
        if (evidence is None) != (intervention is None):
            errors.append(f"{clip_id}/{config_id}: evidence and intervention timestamps must be provided together")
        latency = None
        if evidence is not None and intervention is not None:
            if intervention < evidence:
                errors.append(f"{clip_id}/{config_id}: intervention timestamp precedes evidence")
            else:
                latency = intervention - evidence
        start = int(source["event_start_ms"])
        end = int(source["event_end_ms"])
        joined.append({
            "clip_id": clip_id,
            "participant_id": source["participant_id"],
            "dataset_split": source["dataset_split"],
            "config_id": config_id,
            "ground_truth": source["ground_truth"],
            "predicted_label": predicted,
            "window_hit": detected is not None and start <= detected <= end,
            "latency_ms": latency,
        })
    for clip_id, source in manifest_rows.items():
        required_configs = set(CONFIGS) if source["participant_id"] == "P03" else {"A"}
        for config_id in required_configs:
            if (clip_id, config_id) not in seen:
                errors.append(f"missing prediction: {clip_id}/{config_id}")
    if errors:
        raise ValueError("prediction validation failed:\n" + "\n".join(f"- {item}" for item in errors))

    results: dict[str, object] = {}
    for participant in PARTICIPANT_SPLITS:
        participant_records = [row for row in joined if row["participant_id"] == participant and row["config_id"] == "A"]
        results[participant] = calculate_metrics(participant_records)
    ablations = {
        config_id: calculate_metrics([row for row in joined if row["participant_id"] == "P03" and row["config_id"] == config_id])
        for config_id in CONFIGS
    }
    payload = {
        "schema_version": "three-participant-results/1.0",
        "status": "COMPLETE",
        "generated_at": now_iso(),
        "test_lock_sha256": sha256_file(lock_file),
        "rule_freeze_sha256": sha256_file(freeze_file),
        "primary_result": {"participant_id": "P03", "config_id": "A", **results["P03"]},
        "participant_results": results,
        "ablation_results": ablations,
        "claim_boundary": (
            "Three healthy adult participants in controlled, cross-date scenarios; "
            "engineering feasibility only, not clinical or population-level validation."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "experiment-results.json", payload)
    write_csv(
        output_dir / "confusion-matrices.csv",
        ("participant_id", "config_id", "tp", "tn", "fp", "fn"),
        (
            {
                "participant_id": "P03" if config_id != "A" else participant,
                "config_id": config_id,
                **metrics["confusion_matrix"],
            }
            for participant, config_id, metrics in (
                [(p, "A", results[p]) for p in PARTICIPANT_SPLITS]
                + [("P03", c, ablations[c]) for c in ("B", "C", "D")]
            )
        ),
    )
    primary = payload["primary_result"]
    markdown = f"""# 三参与者实验结果\n\n状态：`COMPLETE`\n\n## 最终独立测试\n\n- 参与者：P03\n- 有效测试片段：{primary['sample_count']}\n- Precision：{primary['precision']:.3f}\n- Recall：{primary['recall']:.3f}\n- F1：{primary['f1']:.3f}\n- 高风险窗口召回率：{primary['high_risk_window_recall']:.3f}\n- P95延迟：{primary['latency_ms']['p95']} ms\n\n## 结论边界\n\n本实验为3名健康成年参与者、跨日期、固定机位的受控场景工程验证，不代表老年人群临床表现或大规模泛化能力。\n"""
    (output_dir / "experiment-results.md").write_text(markdown, encoding="utf-8")
    return payload


def generate_stability_template(output: Path) -> None:
    if output.exists():
        raise ValueError(f"refusing to overwrite existing stability template: {output}")
    rows = [
        {
            "run_id": f"STABILITY-{participant}",
            "participant_id": participant,
            "started_at": "",
            "ended_at": "",
            "source_mode": "LIVE_DEVICE",
            "total_risk_events": "",
            "false_alarms": "",
            "system_exceptions": "",
            "restarts": "",
            "unhandled_exceptions": "",
            "ruleset_version": "",
            "notes": "",
        }
        for participant in PARTICIPANT_SPLITS
    ]
    write_csv(output, STABILITY_FIELDS, rows)


def _parse_datetime(value: str, field: str, run_id: str, errors: list[str]) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        errors.append(f"{run_id}: {field} must be ISO 8601")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{run_id}: {field} must include a timezone")
    return parsed


def analyze_stability(input_path: Path, output: Path) -> dict[str, object]:
    rows = read_csv(input_path)
    errors: list[str] = []
    runs: list[dict[str, object]] = []
    participants = {row.get("participant_id") for row in rows}
    if participants != set(PARTICIPANT_SPLITS):
        errors.append("stability records must contain exactly P01, P02, and P03")
    for row in rows:
        run_id = row.get("run_id", "")
        start = _parse_datetime(row.get("started_at", ""), "started_at", run_id, errors)
        end = _parse_datetime(row.get("ended_at", ""), "ended_at", run_id, errors)
        if row.get("source_mode") == "MOCK":
            errors.append(f"{run_id}: MOCK time cannot count toward the 12-hour test")
        numbers: dict[str, int] = {}
        for field in ("total_risk_events", "false_alarms", "system_exceptions", "restarts", "unhandled_exceptions"):
            parsed = _parse_nonnegative_int(row.get(field, ""), field, run_id, errors)
            if parsed is not None:
                numbers[field] = parsed
        hours = 0.0
        if start is not None and end is not None:
            hours = (end - start).total_seconds() / 3600
            if hours < 4:
                errors.append(f"{run_id}: duration must be at least 4 hours")
        if numbers.get("false_alarms", 0) > numbers.get("total_risk_events", 0):
            errors.append(f"{run_id}: false_alarms cannot exceed total_risk_events")
        runs.append({"run_id": run_id, "participant_id": row.get("participant_id"), "duration_hours": round(hours, 4), **numbers})
    total_hours = sum(float(run["duration_hours"]) for run in runs)
    if total_hours < 12:
        errors.append("total stability duration must be at least 12 hours")
    total_false = sum(int(run.get("false_alarms", 0)) for run in runs)
    payload = {
        "schema_version": "three-participant-stability/1.0",
        "status": "COMPLETE" if not errors else "INCOMPLETE",
        "generated_at": now_iso(),
        "runs": runs,
        "totals": {
            "duration_hours": round(total_hours, 4),
            "risk_events": sum(int(run.get("total_risk_events", 0)) for run in runs),
            "false_alarms": total_false,
            "false_alarms_per_hour": round(total_false / total_hours, 6) if total_hours else None,
            "system_exceptions": sum(int(run.get("system_exceptions", 0)) for run in runs),
            "restarts": sum(int(run.get("restarts", 0)) for run in runs),
            "unhandled_exceptions": sum(int(run.get("unhandled_exceptions", 0)) for run in runs),
        },
        "errors": errors,
    }
    write_json(output, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and audit the three-participant experiment.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate-manifest")
    generate.add_argument("--output", type=Path, required=True)

    validate = subparsers.add_parser("validate-manifest")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--stage", choices=("template", "captured"), required=True)
    validate.add_argument("--media-root", type=Path)
    validate.add_argument("--report", type=Path)

    lock = subparsers.add_parser("lock-test")
    lock.add_argument("--manifest", type=Path, required=True)
    lock.add_argument("--media-root", type=Path, required=True)
    lock.add_argument("--output-dir", type=Path, required=True)

    verify_lock = subparsers.add_parser("verify-lock")
    verify_lock.add_argument("--lock-file", type=Path, required=True)

    freeze = subparsers.add_parser("freeze-rules")
    freeze.add_argument("--lock-file", type=Path, required=True)
    freeze.add_argument("--ruleset", type=Path, required=True)
    freeze.add_argument("--model", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--allow-dirty", action="store_true")

    prediction_template = subparsers.add_parser("generate-predictions")
    prediction_template.add_argument("--manifest", type=Path, required=True)
    prediction_template.add_argument("--output", type=Path, required=True)

    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--manifest", type=Path, required=True)
    analyze.add_argument("--predictions", type=Path, required=True)
    analyze.add_argument("--lock-file", type=Path, required=True)
    analyze.add_argument("--freeze-file", type=Path, required=True)
    analyze.add_argument("--output-dir", type=Path, required=True)

    stability_template = subparsers.add_parser("generate-stability")
    stability_template.add_argument("--output", type=Path, required=True)

    stability = subparsers.add_parser("analyze-stability")
    stability.add_argument("--input", type=Path, required=True)
    stability.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "generate-manifest":
            generate_manifest(args.output)
            payload = {"status": "PASS", "output": str(args.output), "planned_slots": 96}
        elif args.command == "validate-manifest":
            payload = validate_manifest(args.manifest, stage=args.stage, media_root=args.media_root)
            if args.report:
                write_json(args.report, payload)
        elif args.command == "lock-test":
            payload = lock_test_set(args.manifest, args.media_root, args.output_dir)
        elif args.command == "verify-lock":
            payload = verify_test_lock(args.lock_file)
        elif args.command == "freeze-rules":
            payload = freeze_rules(args.lock_file, args.ruleset, args.model, args.output, allow_dirty=args.allow_dirty)
        elif args.command == "generate-predictions":
            generate_predictions(args.manifest, args.output)
            payload = {"status": "PASS", "output": str(args.output)}
        elif args.command == "analyze":
            payload = analyze_predictions(args.manifest, args.predictions, args.lock_file, args.freeze_file, args.output_dir)
        elif args.command == "generate-stability":
            generate_stability_template(args.output)
            payload = {"status": "PASS", "output": str(args.output)}
        else:
            payload = analyze_stability(args.input, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") not in {"FAIL", "INCOMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
