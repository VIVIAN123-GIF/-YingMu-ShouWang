"""Prepare and audit the three-participant final experiment.

This command never invents measurements. It creates protocol templates and only
produces final metrics after the capture manifest, P03 lock, rule freeze, and
machine-generated inference records pass their respective gates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, Sequence


PARTICIPANT_SPLITS = {
    "P01": "CALIBRATION",
    "P02": "VALIDATION",
    "P03": "TEST",
}
VALIDITIES = {"VALID", "ABORTED", "EXCLUDED"}
CONFIGS = {"A": "full_system"}
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVALUATION_SPEC = ROOT / "experiments" / "three-participant" / "p03-evaluation-spec.v1.json"
DEFAULT_EVALUATION_PROTOCOL = ROOT / "experiments" / "three-participant" / "P03-评价口径-v1.0.md"
DEFAULT_INFERENCE_SCHEMA = ROOT / "experiments" / "three-participant" / "p03-inference-results.schema.json"
DEFAULT_REHEARSAL_SCHEMA = ROOT / "experiments" / "three-participant" / "p03-executor-rehearsal.schema.json"
MODULE_STATUSES = {"SUCCESS", "NO_EVIDENCE", "LOW_QUALITY", "FAILED"}
ASSESSMENT_STATUSES = {"VALID", "PARTIAL", "INSUFFICIENT"}
BASELINE_STATUSES = {"INSUFFICIENT", "PROVISIONAL", "STABLE"}
INDEX_FIELDS = ("human_risk", "personal_deviation", "instant_index", "short_30s_index", "trend_3min_index")
ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
INFERENCE_ROOT_FIELDS = {
    "schema_version", "participant_id", "config_id", "source_mode", "simulated",
    "execution_id", "generated_at", "database_isolation_id", "baseline_seed_sha256",
    "test_lock_sha256", "rule_freeze_sha256", "records_sha256", "records",
}
INFERENCE_RECORD_FIELDS = {
    "clip_id", "participant_id", "scenario_id", "record_role", "config_id",
    "asset_sha256", "source_mode", "simulated", "ruleset_version",
    "forewarning_ruleset_version", "model_sha256", "executor_sha256",
    "evaluation_spec_sha256", "modules", "evidences", "rule_traces",
    "risk_event_count", "forewarning", "record_error_code", "attempts",
}
RUNTIME_CODE_ROOTS = ("adapters", "backend", "contracts", "scripts")


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


def sha256_json(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def load_evaluation_spec(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("P03_EVALUATION_SPEC_INVALID") from exc
    if not isinstance(payload, dict):
        raise ValueError("P03_EVALUATION_SPEC_INVALID")
    if payload.get("schema_version") != "p03-evaluation-spec/1.0" or payload.get("status") != "FROZEN":
        raise ValueError("P03_EVALUATION_SPEC_INVALID")
    if payload.get("evaluation_config") != "A" or payload.get("effect_thresholds") is not None:
        raise ValueError("P03_EVALUATION_SPEC_INVALID")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, dict) or set(scenarios) != {item.scenario_id for item in SCENARIOS}:
        raise ValueError("P03_EVALUATION_SPEC_SCENARIOS_INVALID")
    return payload


def validate_rehearsal_report(
    path: Path, *, executor_sha256: str, evaluation_spec_sha256: str
) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("P03_REHEARSAL_REPORT_INVALID") from exc
    expected = {
        "schema_version": "p03-executor-rehearsal/1.0",
        "status": "PASS",
        "config_id": "A",
        "executor_sha256": executor_sha256,
        "evaluation_spec_sha256": evaluation_spec_sha256,
        "deterministic_rerun": True,
        "non_overwrite_verified": True,
    }
    if not isinstance(payload, dict) or any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("P03_REHEARSAL_REPORT_INVALID")
    participants = payload.get("participants")
    if participants != {
        "P01": {"baseline_records": 8, "evaluation_records": 24},
        "P02": {"baseline_records": 8, "evaluation_records": 24},
    }:
        raise ValueError("P03_REHEARSAL_REPORT_INCOMPLETE")
    return payload


def _ruleset_version(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return str(payload.get("ruleset_version")) if isinstance(payload, dict) else None


def _git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()


def _tracked_repository_path(path: Path) -> str | None:
    try:
        relative = path.expanduser().resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return None
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return relative if result.returncode == 0 else None


def _repository_state_errors(expected_commit: str) -> list[str]:
    errors: list[str] = []
    try:
        if _git_output("rev-parse", "HEAD") != expected_commit:
            errors.append("current HEAD differs from the frozen commit")
        tracked_changes = _git_output("status", "--porcelain", "--untracked-files=no")
        if tracked_changes:
            errors.append("tracked files changed after the rule freeze")
        untracked = _git_output(
            "ls-files", "--others", "--exclude-standard", "--", *RUNTIME_CODE_ROOTS
        ).splitlines()
        if any(path.lower().endswith(".py") for path in untracked):
            errors.append("untracked runtime Python code is present after the rule freeze")
    except subprocess.CalledProcessError:
        errors.append("repository state could not be verified")
    return errors


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


def freeze_rules(
    lock_file: Path,
    ruleset: Path,
    forewarning_ruleset: Path,
    model: Path,
    evaluation_spec: Path,
    evaluation_protocol: Path,
    inference_schema: Path,
    rehearsal_schema: Path,
    executor: Path,
    rehearsal_report: Path,
    output: Path,
    *,
    allow_dirty: bool,
) -> dict[str, object]:
    lock_report = verify_test_lock(lock_file)
    _require_pass(lock_report)
    load_evaluation_spec(evaluation_spec)
    if _ruleset_version(ruleset) != "ruleset-v1.2":
        raise ValueError("P03_RULESET_VERSION_INVALID")
    if _ruleset_version(forewarning_ruleset) != "ruleset-v1.3-min":
        raise ValueError("P03_FOREWARNING_RULESET_VERSION_INVALID")
    executor_repo_path = _tracked_repository_path(executor)
    if executor_repo_path is None:
        raise ValueError("P03_EXECUTOR_NOT_TRACKED")
    frozen_paths = {
        "ruleset": ruleset,
        "forewarning_ruleset": forewarning_ruleset,
        "model": model,
        "evaluation_spec": evaluation_spec,
        "evaluation_protocol": evaluation_protocol,
        "inference_schema": inference_schema,
        "rehearsal_schema": rehearsal_schema,
        "executor": executor,
        "rehearsal_report": rehearsal_report,
    }
    missing = [name for name, path in frozen_paths.items() if not path.is_file()]
    if missing:
        raise ValueError(f"freeze artifacts are missing: {', '.join(missing)}")
    validate_rehearsal_report(
        rehearsal_report,
        executor_sha256=sha256_file(executor),
        evaluation_spec_sha256=sha256_file(evaluation_spec),
    )
    git_commit = _git_output("rev-parse", "HEAD")
    dirty = bool(_repository_state_errors(git_commit))
    if dirty and not allow_dirty:
        raise ValueError("git worktree is dirty; commit the final rules or pass --allow-dirty for a rehearsal")
    payload = {
        "schema_version": "three-participant-rule-freeze/2.0",
        "status": "FROZEN" if not dirty else "REHEARSAL_ONLY",
        "frozen_at": now_iso(),
        "git_commit": git_commit,
        "git_dirty": dirty,
        "executor_repository_path": executor_repo_path,
        "test_lock_sha256": sha256_file(lock_file),
        **{
            name: {"path": str(path), "sha256": sha256_file(path)}
            for name, path in frozen_paths.items()
        },
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
    if payload.get("schema_version") != "three-participant-rule-freeze/2.0":
        errors.append("rule freeze schema is not the P03 dual-track freeze")
    git_commit = payload.get("git_commit")
    if not isinstance(git_commit, str) or not re.fullmatch(r"[a-f0-9]{40}", git_commit):
        errors.append("rule freeze has no valid git commit")
    else:
        errors.extend(_repository_state_errors(git_commit))
    for key in (
        "ruleset",
        "forewarning_ruleset",
        "model",
        "evaluation_spec",
        "evaluation_protocol",
        "inference_schema",
        "rehearsal_schema",
        "executor",
        "rehearsal_report",
    ):
        item = payload.get(key, {})
        path = Path(str(item.get("path", "")))
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            errors.append(f"frozen {key} is missing or changed")
    evaluation_item = payload.get("evaluation_spec", {})
    evaluation_path = Path(str(evaluation_item.get("path", "")))
    if evaluation_path.is_file():
        try:
            load_evaluation_spec(evaluation_path)
        except ValueError:
            errors.append("frozen evaluation_spec is invalid")
    ruleset_path = Path(str(payload.get("ruleset", {}).get("path", "")))
    if ruleset_path.is_file() and _ruleset_version(ruleset_path) != "ruleset-v1.2":
        errors.append("frozen ruleset is not ruleset-v1.2")
    forewarning_path = Path(str(payload.get("forewarning_ruleset", {}).get("path", "")))
    if forewarning_path.is_file() and _ruleset_version(forewarning_path) != "ruleset-v1.3-min":
        errors.append("frozen forewarning_ruleset is not ruleset-v1.3-min")
    executor_path = Path(str(payload.get("executor", {}).get("path", "")))
    executor_repo_path = _tracked_repository_path(executor_path) if executor_path.is_file() else None
    if executor_repo_path is None or executor_repo_path != payload.get("executor_repository_path"):
        errors.append("frozen executor is not tracked by the frozen repository")
    rehearsal_item = payload.get("rehearsal_report", {})
    rehearsal_path = Path(str(rehearsal_item.get("path", "")))
    if rehearsal_path.is_file():
        try:
            validate_rehearsal_report(
                rehearsal_path,
                executor_sha256=str(payload.get("executor", {}).get("sha256", "")),
                evaluation_spec_sha256=str(payload.get("evaluation_spec", {}).get("sha256", "")),
            )
        except ValueError:
            errors.append("frozen rehearsal_report is invalid")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "payload": payload}


def generate_predictions(manifest: Path, output: Path) -> None:
    del manifest, output
    raise ValueError(
        "LEGACY_PREDICTIONS_PROHIBITED: predictions.csv cannot be used for formal P03 results"
    )


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


def rate_metric(numerator: int, denominator: int) -> dict[str, object]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else None,
        "wilson_95": wilson_interval(numerator, denominator),
    }


def _number_or_none(value: object, field: str, key: str, errors: list[str]) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(f"{key}: {field} must be a number or null")
        return None
    result = float(value)
    if not 0.0 <= result <= 1.0:
        errors.append(f"{key}: {field} must be within [0, 1]")
        return None
    return result


def _usable_evidences(record: dict[str, object], spec: dict[str, object]) -> list[dict[str, object]]:
    thresholds = spec["quality_thresholds"]
    return [
        item for item in record.get("evidences", [])
        if isinstance(item, dict)
        and isinstance(item.get("confidence"), (int, float))
        and not isinstance(item.get("confidence"), bool)
        and isinstance(item.get("data_quality"), (int, float))
        and not isinstance(item.get("data_quality"), bool)
        and float(item["confidence"]) >= float(thresholds["confidence"])
        and float(item["data_quality"]) >= float(thresholds["data_quality"])
    ]


def _transition_bound_signals(
    record: dict[str, object], spec: dict[str, object]
) -> tuple[set[str], list[dict[str, object]]]:
    evidences = _usable_evidences(record, spec)
    family_by_type = {
        evidence_type: family
        for family, evidence_types in spec["signal_families"].items()
        for evidence_type in evidence_types
    }
    transitions = [
        item for item in evidences if item.get("evidence_type") == "sit_to_stand_transition"
    ]
    best_families: set[str] = set()
    best_signals: list[dict[str, object]] = []
    short_window_ms = int(spec.get("rule_window_seconds", 30)) * 1000
    for transition in transitions:
        transition_observations = set(transition.get("observation_ids", []))
        transition_at = transition.get("timestamp_ms")
        if not isinstance(transition_at, int):
            continue
        selected: list[dict[str, object]] = []
        selected_families: set[str] = set()
        for signal in evidences:
            family = family_by_type.get(signal.get("evidence_type"))
            signal_at = signal.get("timestamp_ms")
            if not family or not isinstance(signal_at, int):
                continue
            same_assessment = bool(
                transition_observations & set(signal.get("observation_ids", []))
            )
            if same_assessment and 0 <= signal_at - transition_at <= short_window_ms:
                selected.append(signal)
                selected_families.add(family)
        if len(selected_families) > len(best_families):
            best_families = selected_families
            best_signals = selected
    return best_families, best_signals


def _expected_rule_traces(
    record: dict[str, object], ruleset_path: Path
) -> list[dict[str, object]]:
    from contracts.v1.decision import FallDecisionPolicy
    from contracts.v1.ruleset import Ruleset

    policy = FallDecisionPolicy(Ruleset.load(ruleset_path))
    anchor = datetime(2000, 1, 1, tzinfo=timezone.utc)
    recent: list[SimpleNamespace] = []
    expected: list[dict[str, object]] = []
    previous_state = "GREEN"
    active_status: str | None = None
    active_created_at: datetime | None = None
    recovery_started_at: datetime | None = None
    evidence_rows = sorted(
        (item for item in record.get("evidences", []) if isinstance(item, dict)),
        key=lambda item: int(item.get("ingestion_order", 0)),
    )
    for item in evidence_rows:
        timestamp = anchor + timedelta(milliseconds=int(item["timestamp_ms"]))
        evidence = SimpleNamespace(
            evidence_id=item["evidence_id"],
            evidence_type=item["evidence_type"],
            timestamp=timestamp,
            confidence=item["confidence"],
            data_quality=item["data_quality"],
            severity=item["severity"],
            observation_ids=tuple(item["observation_ids"]),
            source_mode=record.get("source_mode"),
            simulated=record.get("simulated"),
            risk_domain="FALL",
            current_value=item.get("current_value"),
        )
        recent.append(evidence)
        decision = policy.evaluate(
            now=timestamp,
            previous_state=previous_state,
            active_status=active_status,
            active_created_at=active_created_at,
            recovery_started_at=recovery_started_at,
            recent=recent,
            trigger=evidence,
        )
        event_created = decision.action == "CREATE_EVENT"
        expected.append({
            "trigger_evidence_id": evidence.evidence_id,
            "evaluated_at_ms": int(item["timestamp_ms"]),
            "previous_state": previous_state,
            "next_state": decision.risk_level,
            "previous_status": active_status,
            "next_status": decision.next_status,
            "matched_rule": decision.matched_rule,
            "event_created": event_created,
        })
        if event_created:
            active_status = decision.next_status
            active_created_at = timestamp
        elif decision.next_status is not None:
            active_status = decision.next_status
        if decision.matched_rule == "R-FALL-04":
            recovery_started_at = timestamp
        previous_state = decision.risk_level
    return expected


def _trace_sequence_conforms(record: dict[str, object], ruleset_path: Path) -> bool:
    expected = _expected_rule_traces(record, ruleset_path)
    actual = record.get("rule_traces", [])
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    comparison_fields = (
        "trigger_evidence_id", "evaluated_at_ms", "previous_state", "next_state",
        "previous_status", "next_status", "matched_rule", "event_created",
    )
    return all(
        tuple(trace.get(field) for field in comparison_fields)
        == tuple(rebuilt.get(field) for field in comparison_fields)
        for trace, rebuilt in zip(actual, expected)
        if isinstance(trace, dict)
    ) and all(isinstance(trace, dict) for trace in actual)


def _validate_inference_record(
    record: object,
    manifest_row: dict[str, str],
    spec: dict[str, object],
    freeze: dict[str, object],
    errors: list[str],
) -> dict[str, object] | None:
    if not isinstance(record, dict):
        errors.append("inference record must be an object")
        return None
    clip_id = str(record.get("clip_id", ""))
    key = clip_id or "record-without-clip-id"
    if set(record) != INFERENCE_RECORD_FIELDS:
        errors.append(f"{key}: record fields do not match p03-inference-results/1.0")
    attempts = record.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        errors.append(f"{key}: attempts must preserve at least one execution attempt")
    else:
        attempt_ids: set[str] = set()
        for index, attempt in enumerate(attempts):
            attempt_key = f"{key}/attempt-{index}"
            if not isinstance(attempt, dict) or set(attempt) != {
                "attempt_id", "started_at", "completed_at", "status", "error_code"
            }:
                errors.append(f"{attempt_key}: attempt fields do not match the frozen schema")
                continue
            attempt_id = attempt.get("attempt_id")
            if not isinstance(attempt_id, str) or not attempt_id or attempt_id in attempt_ids:
                errors.append(f"{attempt_key}: attempt_id must be a unique non-empty string")
            else:
                attempt_ids.add(attempt_id)
            started = _parse_datetime(str(attempt.get("started_at", "")), "started_at", attempt_key, errors)
            completed = _parse_datetime(str(attempt.get("completed_at", "")), "completed_at", attempt_key, errors)
            if started is not None and completed is not None and completed < started:
                errors.append(f"{attempt_key}: completed_at precedes started_at")
            if attempt.get("status") not in {"SUCCESS", "FAILED"}:
                errors.append(f"{attempt_key}: status must be SUCCESS or FAILED")
            error_code = attempt.get("error_code")
            if attempt.get("status") == "FAILED":
                if not isinstance(error_code, str) or not ERROR_CODE_PATTERN.fullmatch(error_code):
                    errors.append(f"{attempt_key}: failed attempt requires a sanitized error_code")
            elif error_code is not None:
                errors.append(f"{attempt_key}: successful attempt must not carry an error_code")
    expected = {
        "participant_id": "P03",
        "scenario_id": manifest_row["scenario_id"],
        "record_role": manifest_row["record_role"],
        "config_id": "A",
        "asset_sha256": manifest_row["sha256"],
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "ruleset_version": "ruleset-v1.2",
        "forewarning_ruleset_version": "ruleset-v1.3-min",
        "model_sha256": freeze["model"]["sha256"],
        "executor_sha256": freeze["executor"]["sha256"],
        "evaluation_spec_sha256": freeze["evaluation_spec"]["sha256"],
    }
    for field, value in expected.items():
        if record.get(field) != value:
            errors.append(f"{key}: {field} does not match the frozen P03 input")

    modules = record.get("modules")
    if not isinstance(modules, dict) or set(modules) != {"GAIT", "TRAJECTORY"}:
        errors.append(f"{key}: modules must contain exactly GAIT and TRAJECTORY")
        modules = {}
    for module_name in ("GAIT", "TRAJECTORY"):
        module = modules.get(module_name)
        if not isinstance(module, dict) or set(module) != {"status", "error_code"} or module.get("status") not in MODULE_STATUSES:
            errors.append(f"{key}: invalid {module_name} module status")
            continue
        code = module.get("error_code")
        if module["status"] == "FAILED":
            if not isinstance(code, str) or not ERROR_CODE_PATTERN.fullmatch(code):
                errors.append(f"{key}: failed {module_name} requires a sanitized error_code")
        elif code not in (None, ""):
            errors.append(f"{key}: successful {module_name} must not carry an error_code")

    evidences = record.get("evidences")
    if not isinstance(evidences, list):
        errors.append(f"{key}: evidences must be an array")
        evidences = []
        record["evidences"] = evidences
    family_by_type = {
        evidence_type: family
        for family, evidence_types in spec["signal_families"].items()
        for evidence_type in evidence_types
    }
    evidence_ids: set[str] = set()
    ingestion_orders: list[int] = []
    for index, evidence in enumerate(evidences):
        evidence_key = f"{key}/evidence-{index}"
        if not isinstance(evidence, dict) or not isinstance(evidence.get("evidence_type"), str):
            errors.append(f"{evidence_key}: invalid evidence")
            continue
        if set(evidence) != {
            "evidence_id", "ingestion_order", "evidence_type", "signal_family",
            "confidence", "data_quality", "severity", "current_value", "observation_ids",
            "timestamp_ms", "first_detected_at_ms",
        }:
            errors.append(f"{evidence_key}: evidence fields do not match the frozen schema")
        evidence_id = evidence.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id or evidence_id in evidence_ids:
            errors.append(f"{evidence_key}: evidence_id must be a unique non-empty string")
        else:
            evidence_ids.add(evidence_id)
        ingestion_order = evidence.get("ingestion_order")
        if not isinstance(ingestion_order, int) or isinstance(ingestion_order, bool) or ingestion_order < 0:
            errors.append(f"{evidence_key}: ingestion_order must be a non-negative integer")
        else:
            ingestion_orders.append(ingestion_order)
        for field in ("confidence", "data_quality", "severity"):
            value = _number_or_none(evidence.get(field), field, evidence_key, errors)
            if value is None:
                errors.append(f"{evidence_key}: {field} is required")
        observations = evidence.get("observation_ids")
        if (
            not isinstance(observations, list)
            or not observations
            or len(set(observations)) != len(observations)
            or not all(isinstance(item, str) and item for item in observations)
        ):
            errors.append(f"{evidence_key}: observation_ids must contain non-empty strings")
        timestamp_ms = evidence.get("timestamp_ms")
        if not isinstance(timestamp_ms, int) or isinstance(timestamp_ms, bool) or timestamp_ms < 0:
            errors.append(f"{evidence_key}: timestamp_ms must be a non-negative integer")
        detected_at = evidence.get("first_detected_at_ms")
        if detected_at is not None and (
            not isinstance(detected_at, int) or isinstance(detected_at, bool) or detected_at < 0
        ):
            errors.append(f"{evidence_key}: first_detected_at_ms must be a non-negative integer or null")
        supplied_family = evidence.get("signal_family")
        expected_family = family_by_type.get(evidence["evidence_type"])
        if supplied_family != expected_family:
            errors.append(f"{evidence_key}: signal_family does not match the frozen specification")
    if ingestion_orders and ingestion_orders != list(range(len(evidences))):
        errors.append(f"{key}: evidences must use contiguous ingestion_order starting at zero")

    traces = record.get("rule_traces")
    if not isinstance(traces, list):
        errors.append(f"{key}: rule_traces must be an array")
        traces = []
    trace_ids: set[str] = set()
    for index, trace in enumerate(traces):
        trace_key = f"{key}/trace-{index}"
        if not isinstance(trace, dict) or set(trace) != {
            "trace_id", "trigger_evidence_id", "evaluated_at_ms", "previous_state",
            "next_state", "previous_status", "next_status", "matched_rule",
            "event_created",
        }:
            errors.append(f"{trace_key}: rule trace fields do not match the frozen schema")
            continue
        trace_id = trace.get("trace_id")
        if not isinstance(trace_id, str) or not trace_id or trace_id in trace_ids:
            errors.append(f"{trace_key}: trace_id must be a unique non-empty string")
        else:
            trace_ids.add(trace_id)
        if trace.get("trigger_evidence_id") not in evidence_ids:
            errors.append(f"{trace_key}: trigger_evidence_id does not reference this clip")
        evaluated_at = trace.get("evaluated_at_ms")
        if not isinstance(evaluated_at, int) or isinstance(evaluated_at, bool) or evaluated_at < 0:
            errors.append(f"{trace_key}: evaluated_at_ms must be a non-negative integer")
        for field in ("previous_state", "next_state", "matched_rule"):
            if not isinstance(trace.get(field), str) or not trace[field]:
                errors.append(f"{trace_key}: {field} must be a non-empty string")
        for field in ("previous_status", "next_status"):
            if trace.get(field) is not None and (
                not isinstance(trace[field], str) or not trace[field]
            ):
                errors.append(f"{trace_key}: {field} must be a string or null")
        if not isinstance(trace.get("event_created"), bool):
            errors.append(f"{trace_key}: event_created must be boolean")
    if [item.get("trigger_evidence_id") for item in traces if isinstance(item, dict)] != [
        item.get("evidence_id") for item in evidences if isinstance(item, dict)
    ]:
        errors.append(f"{key}: rule traces must follow the Evidence ingestion sequence")
    risk_event_count = record.get("risk_event_count")
    if not isinstance(risk_event_count, int) or isinstance(risk_event_count, bool) or risk_event_count < 0:
        errors.append(f"{key}: risk_event_count must be a non-negative integer")
    elif risk_event_count != sum(
        bool(item.get("event_created")) for item in traces if isinstance(item, dict)
    ):
        errors.append(f"{key}: risk_event_count does not match event-creating rule traces")

    snapshot = record.get("forewarning")
    module_failed = any(
        isinstance(modules.get(name), dict) and modules[name].get("status") == "FAILED"
        for name in ("GAIT", "TRAJECTORY")
    )
    if snapshot is None and not module_failed:
        errors.append(f"{key}: forewarning is required when both modules completed")
    elif snapshot is not None:
        if not isinstance(snapshot, dict):
            errors.append(f"{key}: forewarning must be an object or null")
        else:
            if set(snapshot) != {
                "assessment_status", "baseline_status", "human_risk", "personal_deviation",
                "instant_index", "short_30s_index", "trend_3min_index", "degradation_reasons",
            }:
                errors.append(f"{key}: forewarning fields do not match the frozen schema")
            if snapshot.get("assessment_status") not in ASSESSMENT_STATUSES:
                errors.append(f"{key}: invalid assessment_status")
            if snapshot.get("baseline_status") not in BASELINE_STATUSES:
                errors.append(f"{key}: invalid baseline_status")
            for field in INDEX_FIELDS:
                _number_or_none(snapshot.get(field), field, key, errors)
            reasons = snapshot.get("degradation_reasons")
            if not isinstance(reasons, list) or not all(isinstance(item, str) and item for item in reasons):
                errors.append(f"{key}: degradation_reasons must contain non-empty strings")
    record_error = record.get("record_error_code")
    if record_error is not None and (
        not isinstance(record_error, str) or not ERROR_CODE_PATTERN.fullmatch(record_error)
    ):
        errors.append(f"{key}: record_error_code must be sanitized or null")
    return record


def _evidence_hit(
    record: dict[str, object], evidence_types: set[str], spec: dict[str, object]
) -> bool:
    return any(item["evidence_type"] in evidence_types for item in _usable_evidences(record, spec))


def _index_distribution(records: Sequence[dict[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in INDEX_FIELDS:
        raw = []
        assessable = []
        for record in records:
            snapshot = record.get("forewarning")
            value = snapshot.get(field) if isinstance(snapshot, dict) else None
            status = snapshot.get("assessment_status") if isinstance(snapshot, dict) else None
            raw.append({"clip_id": record["clip_id"], "assessment_status": status, "value": value})
            if status in {"VALID", "PARTIAL"} and isinstance(value, (int, float)):
                assessable.append(float(value))
        result[field] = {
            "raw": raw,
            "assessable_count": len(assessable),
            "median": percentile(assessable, 50),
            "iqr": [percentile(assessable, 25), percentile(assessable, 75)] if assessable else None,
        }
    return result


def _comparison(
    comparison: dict[str, object], records: Sequence[dict[str, object]], minimum: int
) -> dict[str, object]:
    target_scenarios = set(comparison.get("target_scenarios", [comparison.get("target_scenario")]))
    target_repeats = set(comparison.get("target_repeat_indices", []))
    reference_scenarios = set(comparison["reference_scenarios"])
    targets = [
        item for item in records
        if item["scenario_id"] in target_scenarios
        and (not target_repeats or int(item["repeat_index"]) in target_repeats)
    ]
    references = [item for item in records if item["scenario_id"] in reference_scenarios]
    fields: dict[str, object] = {}
    for field in INDEX_FIELDS:
        def values(items: Sequence[dict[str, object]]) -> list[float]:
            return [
                float(snapshot[field])
                for item in items
                if isinstance((snapshot := item.get("forewarning")), dict)
                and snapshot.get("assessment_status") in {"VALID", "PARTIAL"}
                and isinstance(snapshot.get(field), (int, float))
            ]
        target_values = values(targets)
        reference_values = values(references)
        if len(target_values) < minimum or len(reference_values) < minimum:
            fields[field] = {
                "status": "NOT_ESTIMABLE",
                "target_count": len(target_values),
                "reference_count": len(reference_values),
                "median_difference": None,
            }
        else:
            target_median = percentile(target_values, 50)
            reference_median = percentile(reference_values, 50)
            fields[field] = {
                "status": "ESTIMATED",
                "target_count": len(target_values),
                "reference_count": len(reference_values),
                "median_difference": round(float(target_median) - float(reference_median), 6),
            }
    return {"comparison_id": comparison["comparison_id"], "indices": fields}


def _calculate_dual_track_metrics(
    records: Sequence[dict[str, object]], spec: dict[str, object], ruleset_path: Path
) -> dict[str, object]:
    by_scenario = {
        scenario_id: [item for item in records if item["scenario_id"] == scenario_id]
        for scenario_id in spec["scenarios"]
    }
    positives = by_scenario["POS_RAPID_RISE_SWAY"]
    transition_targets = [
        item for item in records
        if item["scenario_id"] in {
            "POS_RAPID_RISE_SWAY", "NEG_RAPID_RISE_STABLE", "NEG_NORMAL_RISE_WALK"
        }
    ]
    def families(record: dict[str, object]) -> set[str]:
        bound, _signals = _transition_bound_signals(record, spec)
        return bound

    orange_positive = sum(
        int(item.get("risk_event_count", 0))
        for item in positives
    )
    forbidden = [
        item for item in records
        if item["record_role"] == "EVALUATION"
        and item["scenario_id"] != "POS_RAPID_RISE_SWAY"
    ]
    forbidden_events = sum(
        int(item.get("risk_event_count", 0))
        for item in forbidden
    )
    adjudicated = [
        item for item in records if item["record_role"] == "EVALUATION"
        and isinstance(item.get("rule_traces"), list) and bool(item["rule_traces"])
    ]
    conformant = sum(_trace_sequence_conforms(item, ruleset_path) for item in adjudicated)

    window_status = "AVAILABLE"
    window_hits = 0
    for item in positives:
        _bound_families, candidates = _transition_bound_signals(item, spec)
        if candidates and any(evidence.get("first_detected_at_ms") is None for evidence in candidates):
            window_status = "NOT_AVAILABLE"
        detected = [
            int(evidence["first_detected_at_ms"])
            for evidence in candidates if evidence.get("first_detected_at_ms") is not None
        ]
        if detected and int(item["event_start_ms"]) <= min(detected) <= int(item["event_end_ms"]):
            window_hits += 1

    instant = {
        "transition_detection_rate": rate_metric(
            sum(_evidence_hit(item, {"sit_to_stand_transition"}, spec) for item in transition_targets),
            int(spec["denominators"]["transition_truth_clips"]),
        ),
        "instability_family_detection_rate": rate_metric(
            sum(bool(families(item)) for item in positives),
            int(spec["denominators"]["instant_positive_clips"]),
        ),
        "multi_family_formation_rate": rate_metric(
            sum(len(families(item)) >= 2 for item in positives),
            int(spec["denominators"]["instant_positive_clips"]),
        ),
        "orange_production": {
            **rate_metric(
                sum(
                    int(item.get("risk_event_count", 0)) > 0
                    for item in positives
                ),
                int(spec["denominators"]["instant_positive_clips"]),
            ),
            "orange_event_count": orange_positive,
            "semantics": "ENGINEERING_YIELD_NOT_CLINICAL_SENSITIVITY",
        },
        "forbidden_orange_events": {
            "event_count": forbidden_events,
            "denominator_clips": int(spec["denominators"]["orange_forbidden_evaluation_clips"]),
            "events_per_clip": round(
                forbidden_events / int(spec["denominators"]["orange_forbidden_evaluation_clips"]), 6
            ),
        },
        "adjudication_coverage": rate_metric(len(adjudicated), 24),
        "adjudication_conformance": rate_metric(conformant, len(adjudicated)),
        "event_window_hit_rate": (
            {"status": "NOT_AVAILABLE", "numerator": None, "denominator": 4, "rate": None}
            if window_status == "NOT_AVAILABLE"
            else {"status": "AVAILABLE", **rate_metric(window_hits, 4)}
        ),
    }

    evidence_metrics: dict[str, object] = {}
    for scenario_id in ("POS_SLOW_SMALL_STEP_SWAY", "POS_ASYMMETRIC_STEP"):
        targets = set(spec["scenarios"][scenario_id]["trend_target_evidence_any"])
        scenario_records = by_scenario[scenario_id]
        evidence_metrics[scenario_id] = {
            "any_target": rate_metric(sum(_evidence_hit(item, targets, spec) for item in scenario_records), 4),
            "by_type": {
                evidence_type: rate_metric(
                    sum(_evidence_hit(item, {evidence_type}, spec) for item in scenario_records), 4
                )
                for evidence_type in sorted(targets)
            },
        }
    abnormal_types = {"relative_speed_change", "gait_instability"}
    normal_references = by_scenario["BASE_NORMAL_WALK_L2R"] + by_scenario["BASE_NORMAL_WALK_R2L"]
    normal_rise_walk = by_scenario["NEG_NORMAL_RISE_WALK"]

    module_counts = {
        module: {status: 0 for status in (*sorted(MODULE_STATUSES), "MISSING_RESULT")}
        for module in ("GAIT", "TRAJECTORY")
    }
    for item in records:
        for module in module_counts:
            module_payload = item.get("modules", {}).get(module)
            status = module_payload.get("status") if isinstance(module_payload, dict) else None
            if status not in MODULE_STATUSES:
                status = "MISSING_RESULT"
            module_counts[module][status] += 1
    assessment_counts = {status: 0 for status in (*sorted(ASSESSMENT_STATUSES), "MISSING")}
    baseline_counts = {status: 0 for status in (*sorted(BASELINE_STATUSES), "MISSING")}
    degradation_counts: dict[str, int] = {}
    for item in records:
        snapshot = item.get("forewarning")
        if not isinstance(snapshot, dict):
            assessment_counts["MISSING"] += 1
            baseline_counts["MISSING"] += 1
            reason = "MISSING_RESULT" if item.get("missing_result") else "MISSING_FOREWARNING"
            degradation_counts[reason] = degradation_counts.get(reason, 0) + 1
            continue
        assessment_counts[snapshot["assessment_status"]] += 1
        baseline_counts[snapshot["baseline_status"]] += 1
        for reason in snapshot["degradation_reasons"]:
            degradation_counts[reason] = degradation_counts.get(reason, 0) + 1
    trend = {
        "target_evidence_detection_by_scenario": evidence_metrics,
        "normal_reference_false_detection": {
            "baseline_normal_walk": rate_metric(
                sum(_evidence_hit(item, abnormal_types, spec) for item in normal_references), 4
            ),
            "evaluation_normal_rise_walk": rate_metric(
                sum(_evidence_hit(item, abnormal_types, spec) for item in normal_rise_walk), 4
            ),
        },
        "engineering_indices_by_scenario": {
            scenario_id: _index_distribution(items) for scenario_id, items in by_scenario.items()
        },
        "predeclared_median_differences": [
            _comparison(item, records, int(spec["reporting_policy"]["minimum_assessable_per_comparison_group"]))
            for item in spec["predeclared_comparisons"]
        ],
        "module_status_counts": module_counts,
        "assessment_status_counts": assessment_counts,
        "baseline_status_counts": baseline_counts,
        "degradation_reason_counts": dict(sorted(degradation_counts.items())),
    }
    return {"instant_event": instant, "gait_trend": trend}


def analyze_inference_results(
    manifest: Path,
    inference_results: Path,
    lock_file: Path,
    freeze_file: Path,
    evaluation_spec: Path,
    output_dir: Path,
) -> dict[str, object]:
    manifest_report = validate_manifest(manifest, stage="captured")
    _require_pass(manifest_report)
    lock_report = verify_test_lock(lock_file)
    _require_pass(lock_report)
    freeze_report = verify_freeze(freeze_file, lock_file)
    _require_pass(freeze_report)
    spec = load_evaluation_spec(evaluation_spec)
    freeze = freeze_report["payload"]
    if sha256_file(evaluation_spec) != freeze["evaluation_spec"]["sha256"]:
        raise ValueError("evaluation specification does not match the final freeze")
    locked_manifest = lock_file.parent / str(lock_report["payload"].get("locked_manifest", ""))
    manifest_rows = {
        row["clip_id"]: row for row in read_csv(locked_manifest)
        if row["participant_id"] == "P03" and row["validity"] == "VALID"
    }
    try:
        source_payload = json.loads(inference_results.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("P03_INFERENCE_RESULTS_INVALID") from exc
    errors: list[str] = []
    if not isinstance(source_payload, dict) or source_payload.get("schema_version") != "p03-inference-results/1.0":
        raise ValueError("P03_INFERENCE_RESULTS_SCHEMA_INVALID")
    if set(source_payload) != INFERENCE_ROOT_FIELDS:
        errors.append("inference result fields do not match p03-inference-results/1.0")
    if not isinstance(source_payload.get("execution_id"), str) or not source_payload["execution_id"]:
        errors.append("inference result execution_id must be a non-empty string")
    if not isinstance(source_payload.get("database_isolation_id"), str) or not source_payload["database_isolation_id"]:
        errors.append("inference result database_isolation_id must be a non-empty string")
    baseline_seed_sha256 = source_payload.get("baseline_seed_sha256")
    if not isinstance(baseline_seed_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", baseline_seed_sha256):
        errors.append("inference result baseline_seed_sha256 must identify one frozen baseline state")
    _parse_datetime(str(source_payload.get("generated_at", "")), "generated_at", "inference-result", errors)
    expected_root = {
        "participant_id": "P03",
        "config_id": "A",
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "test_lock_sha256": sha256_file(lock_file),
        "rule_freeze_sha256": sha256_file(freeze_file),
    }
    for field, expected in expected_root.items():
        if source_payload.get(field) != expected:
            errors.append(f"inference result {field} does not match the frozen P03 run")
    source_records = source_payload.get("records")
    if not isinstance(source_records, list):
        source_records = []
        errors.append("inference result records must be an array")
    if source_payload.get("records_sha256") != sha256_json(source_records):
        errors.append("inference result records_sha256 does not match the records payload")
    joined: list[dict[str, object]] = []
    seen: set[str] = set()
    for source_record in source_records:
        if not isinstance(source_record, dict):
            errors.append("inference record must be an object")
            continue
        clip_id = str(source_record.get("clip_id", ""))
        if clip_id in seen:
            errors.append(f"duplicate inference result: {clip_id}")
            continue
        seen.add(clip_id)
        source = manifest_rows.get(clip_id)
        if source is None:
            errors.append(f"inference result references unknown P03 clip: {clip_id}")
            continue
        error_count = len(errors)
        validated = _validate_inference_record(source_record, source, spec, freeze, errors)
        if validated is not None and len(errors) == error_count:
            validated.update({
                "event_start_ms": int(source["event_start_ms"]),
                "event_end_ms": int(source["event_end_ms"]),
                "repeat_index": int(source["repeat_index"]),
            })
            joined.append(validated)
    for clip_id in manifest_rows:
        if clip_id not in seen:
            errors.append(f"missing inference result: {clip_id}")

    joined_by_id = {str(item["clip_id"]): item for item in joined}
    metric_records: list[dict[str, object]] = []
    for clip_id, source in manifest_rows.items():
        record = joined_by_id.get(clip_id)
        if record is not None:
            metric_records.append(record)
            continue
        metric_records.append({
            "clip_id": clip_id,
            "scenario_id": source["scenario_id"],
            "record_role": source["record_role"],
            "repeat_index": int(source["repeat_index"]),
            "modules": {},
            "evidences": [],
            "rule_traces": [],
            "risk_event_count": 0,
            "forewarning": None,
            "missing_result": True,
        })

    ruleset_path = Path(str(freeze["ruleset"]["path"]))
    metrics = _calculate_dual_track_metrics(metric_records, spec, ruleset_path)
    payload = {
        "schema_version": "three-participant-results/2.0",
        "status": "COMPLETE" if not errors else "INCOMPLETE",
        "generated_at": now_iso(),
        "test_lock_sha256": sha256_file(lock_file),
        "rule_freeze_sha256": sha256_file(freeze_file),
        "evaluation_spec_sha256": sha256_file(evaluation_spec),
        "source_inference_sha256": sha256_file(inference_results),
        "source_records_sha256": source_payload.get("records_sha256"),
        "primary_result": {
            "participant_id": "P03",
            "config_id": "A",
            "sample_count": 24,
            "baseline_reference_count": 8,
            "result_record_count": len(joined),
            "effect_thresholds": None,
        },
        "metrics": metrics,
        "errors": errors,
        "claim_boundary": (
            "Three healthy adult participants in controlled, cross-date scenarios; "
            "engineering feasibility only, not clinical or population-level validation."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "experiment-results.json", payload)
    markdown = f"""# P03 双轨工程评价结果\n\n状态：`{payload['status']}`\n\n- 主配置：A（完整系统）\n- 评测片段固定分母：24\n- 基线参考片段：8\n- 已接收结构化记录：{len(joined)}\n- 全局二分类 Accuracy：不适用\n- 个体化基线声明：不允许（当前协议仅一个基线日期）\n\n即时事件与步态/趋势指标见 `experiment-results.json`。本报告只描述受控健康成年参与者素材上的工程行为，不代表临床或人群级有效性。\n"""
    (output_dir / "experiment-results.md").write_text(markdown, encoding="utf-8")
    return payload


def validate_final_experiment_result(payload: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["experiment result must be an object"]
    if payload.get("schema_version") != "three-participant-results/2.0":
        errors.append("experiment result must use the frozen P03 dual-track schema")
    if payload.get("status") != "COMPLETE" or payload.get("errors") != []:
        errors.append("experiment result must be COMPLETE without analysis errors")
    primary = payload.get("primary_result")
    expected_primary = {
        "participant_id": "P03",
        "config_id": "A",
        "sample_count": 24,
        "baseline_reference_count": 8,
        "result_record_count": 32,
        "effect_thresholds": None,
    }
    if primary != expected_primary:
        errors.append("primary result does not match the frozen P03 A-only population")
    for field in (
        "test_lock_sha256", "rule_freeze_sha256", "evaluation_spec_sha256",
        "source_inference_sha256", "source_records_sha256",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            errors.append(f"experiment result has invalid {field}")

    metrics = payload.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != {"instant_event", "gait_trend"}:
        return errors + ["experiment result must contain both frozen metric tracks"]
    instant = metrics.get("instant_event")
    expected_instant_keys = {
        "transition_detection_rate", "instability_family_detection_rate",
        "multi_family_formation_rate", "orange_production",
        "forbidden_orange_events", "adjudication_coverage",
        "adjudication_conformance", "event_window_hit_rate",
    }
    if not isinstance(instant, dict) or set(instant) != expected_instant_keys:
        errors.append("instant-event metrics are incomplete")
    else:
        fixed_denominators = {
            "transition_detection_rate": 12,
            "instability_family_detection_rate": 4,
            "multi_family_formation_rate": 4,
            "orange_production": 4,
            "adjudication_coverage": 24,
        }
        for field, denominator in fixed_denominators.items():
            metric = instant.get(field)
            if not isinstance(metric, dict) or metric.get("denominator") != denominator:
                errors.append(f"instant-event metric {field} has an invalid denominator")
        forbidden = instant.get("forbidden_orange_events")
        if not isinstance(forbidden, dict) or forbidden.get("denominator_clips") != 20:
            errors.append("forbidden ORANGE metric has an invalid denominator")
        conformance = instant.get("adjudication_conformance")
        if not isinstance(conformance, dict) or not isinstance(conformance.get("denominator"), int):
            errors.append("adjudication conformance metric is invalid")

    trend = metrics.get("gait_trend")
    expected_trend_keys = {
        "target_evidence_detection_by_scenario", "normal_reference_false_detection",
        "engineering_indices_by_scenario", "predeclared_median_differences",
        "module_status_counts", "assessment_status_counts", "baseline_status_counts",
        "degradation_reason_counts",
    }
    if not isinstance(trend, dict) or set(trend) != expected_trend_keys:
        errors.append("gait-trend metrics are incomplete")
    else:
        module_counts = trend.get("module_status_counts")
        for module in ("GAIT", "TRAJECTORY"):
            counts = module_counts.get(module) if isinstance(module_counts, dict) else None
            if not isinstance(counts, dict) or sum(
                value for value in counts.values() if isinstance(value, int)
            ) != 32:
                errors.append(f"{module} status counts do not preserve the fixed denominator")
        distributions = trend.get("engineering_indices_by_scenario")
        if not isinstance(distributions, dict) or set(distributions) != set(load_evaluation_spec(DEFAULT_EVALUATION_SPEC)["scenarios"]):
            errors.append("engineering-index scenario coverage is incomplete")
        else:
            expected_counts = {item.scenario_id: item.count for item in SCENARIOS}
            for scenario_id, fields in distributions.items():
                if not isinstance(fields, dict) or set(fields) != set(INDEX_FIELDS):
                    errors.append(f"{scenario_id} engineering-index fields are incomplete")
                    continue
                if any(
                    not isinstance(metric, dict)
                    or len(metric.get("raw", [])) != expected_counts[scenario_id]
                    for metric in fields.values()
                ):
                    errors.append(f"{scenario_id} engineering-index raw denominator is incomplete")
    if "ablation_results" in payload or "participant_results" in payload:
        errors.append("legacy binary or unfrozen ablation results are not allowed")
    return errors


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
    freeze.add_argument(
        "--forewarning-ruleset",
        type=Path,
        default=ROOT / "contracts" / "v1" / "rulesets" / "ruleset-v1.3-min.json",
    )
    freeze.add_argument("--model", type=Path, required=True)
    freeze.add_argument("--evaluation-spec", type=Path, default=DEFAULT_EVALUATION_SPEC)
    freeze.add_argument("--evaluation-protocol", type=Path, default=DEFAULT_EVALUATION_PROTOCOL)
    freeze.add_argument("--inference-schema", type=Path, default=DEFAULT_INFERENCE_SCHEMA)
    freeze.add_argument("--rehearsal-schema", type=Path, default=DEFAULT_REHEARSAL_SCHEMA)
    freeze.add_argument("--executor", type=Path, required=True)
    freeze.add_argument("--rehearsal-report", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--allow-dirty", action="store_true")

    prediction_template = subparsers.add_parser("generate-predictions")
    prediction_template.add_argument("--manifest", type=Path, required=True)
    prediction_template.add_argument("--output", type=Path, required=True)

    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--manifest", type=Path, required=True)
    analyze.add_argument("--inference-results", type=Path, required=True)
    analyze.add_argument("--lock-file", type=Path, required=True)
    analyze.add_argument("--freeze-file", type=Path, required=True)
    analyze.add_argument("--evaluation-spec", type=Path, default=DEFAULT_EVALUATION_SPEC)
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
            payload = freeze_rules(
                args.lock_file,
                args.ruleset,
                args.forewarning_ruleset,
                args.model,
                args.evaluation_spec,
                args.evaluation_protocol,
                args.inference_schema,
                args.rehearsal_schema,
                args.executor,
                args.rehearsal_report,
                args.output,
                allow_dirty=args.allow_dirty,
            )
        elif args.command == "generate-predictions":
            generate_predictions(args.manifest, args.output)
            payload = {"status": "PASS", "output": str(args.output)}
        elif args.command == "analyze":
            payload = analyze_inference_results(
                args.manifest,
                args.inference_results,
                args.lock_file,
                args.freeze_file,
                args.evaluation_spec,
                args.output_dir,
            )
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
