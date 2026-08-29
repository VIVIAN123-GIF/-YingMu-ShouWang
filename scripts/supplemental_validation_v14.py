"""Lock, execute and analyze the independent v1.4 supplemental validation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.v1.algorithm import AlgorithmJob, AlgorithmModule, MediaType  # noqa: E402
from contracts.v1.decision import FallDecisionPolicy  # noqa: E402
from contracts.v1.gait_adapter_v14 import run_with_config  # noqa: E402
from contracts.v1.memory import assess_relative_gait_speed  # noqa: E402
from contracts.v1.ruleset import Ruleset, load_ruleset_version  # noqa: E402
from backend.service.intervention_tools import MockVoiceTool  # noqa: E402


EXPERIMENT_ROOT = ROOT / "experiments" / "supplemental-validation-v1.4"
DEFAULT_SPEC = EXPERIMENT_ROOT / "evaluation-spec.v1.json"
DEFAULT_BASELINE_MANIFEST = EXPERIMENT_ROOT / "baseline-manifest.json"
DEFAULT_BASELINE_RESULTS = (
    EXPERIMENT_ROOT / "results" / "baseline-d1-d3-v14-r3" / "baseline-results.json"
)
DEFAULT_RULESET = ROOT / "contracts" / "v1" / "rulesets" / "ruleset-v1.4.json"
DEFAULT_MODEL = ROOT / "models" / "pose_landmarker_heavy.task"
DEFAULT_VISUAL_REVIEW = EXPERIMENT_ROOT / "team-confirmed-visual-review.json"
P03_PROTECTED = (ROOT / "experiments" / "three-participant").resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_new(path: Path, payload: object) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_output(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == P03_PROTECTED or P03_PROTECTED in resolved.parents:
        raise ValueError("P03_FROZEN_OUTPUT_PROTECTED")
    if resolved.exists():
        raise ValueError(f"refusing to overwrite output: {resolved}")
    return resolved


def expected_records() -> list[dict[str, Any]]:
    groups = (
        ("POS_RAPID_RISE_SWAY", 4, "TEST", "IMMEDIATE_ORANGE", "ORANGE"),
        ("POS_SLOW_SMALL_STEP_SWAY", 4, "TEST", "GAIT_TREND", "YELLOW_NO_ORANGE"),
        ("POS_ASYMMETRIC_STEP", 4, "TEST", "GAIT_TREND", "YELLOW_NO_ORANGE"),
        ("NEG_NORMAL_RISE_WALK", 4, "TEST", "NEGATIVE_CONTROL", "NO_ORANGE"),
        ("NEG_FAST_RISE_STABLE", 4, "TEST", "NEGATIVE_CONTROL", "NO_ORANGE"),
        ("NEG_NEAR_THRESHOLD_NORMAL", 4, "TEST", "NEGATIVE_CONTROL", "NO_ORANGE"),
        ("QUALITY_OCCLUSION", 1, "QUALITY", "QUALITY_GATE", "PARTIAL_OR_INSUFFICIENT_NO_ORANGE"),
        ("QUALITY_FEET_OUT", 1, "QUALITY", "QUALITY_GATE", "PARTIAL_OR_INSUFFICIENT_NO_ORANGE"),
        ("QUALITY_LOW_LIGHT", 1, "QUALITY", "QUALITY_GATE", "PARTIAL_OR_INSUFFICIENT_NO_ORANGE"),
        ("QUALITY_MULTI_PERSON", 1, "QUALITY", "QUALITY_GATE", "PARTIAL_OR_INSUFFICIENT_NO_ORANGE"),
        ("GOLDEN_CONTINUOUS_LOOP", 1, "GOLDEN", "CLOSED_LOOP", "ORANGE_TO_RESOLVED"),
    )
    rows = []
    for scenario, count, role, target, expected in groups:
        for index in range(1, count + 1):
            rows.append({
                "clip_id": f"SV01-{scenario}-{index:02d}", "participant_id": "SV01",
                "scenario_id": scenario, "record_role": role, "target": target,
                "expected_assessment": expected, "label_status": "PREDECLARED",
                "capture_date": "", "media_relpath": "", "sha256": "", "byte_size": None,
                "source_mode": "RECORDED_REPLAY", "simulated": True,
                "authorization_record_id": "SV14-AUTH-PRIVATE-001",
                "camera_position_id": "supplemental-fixed-position-01",
                "device_model": "EZVIZ_C6C",
            })
    return rows


def template(output: Path) -> dict[str, Any]:
    output = safe_output(output)
    payload = {
        "schema_version": "supplemental-validation-manifest/1.0",
        "status": "AWAITING_CAPTURE_FILES", "experiment_id": "supplemental-validation-v1.4",
        "ruleset_version": "ruleset-v1.4", "participant_id": "SV01",
        "labels_locked_before_inference": True, "records": expected_records(),
        "claim_boundary": "Controlled healthy-adult supplemental engineering validation, separate from frozen P03.",
    }
    write_new(output, payload)
    return payload


def validate_manifest(path: Path, media_root: Path | None = None) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload.get("schema_version") != "supplemental-validation-manifest/1.0":
        errors.append("invalid schema_version")
    if payload.get("ruleset_version") != "ruleset-v1.4":
        errors.append("manifest must use ruleset-v1.4")
    if payload.get("labels_locked_before_inference") is not True:
        errors.append("labels must be locked before inference")
    rows = payload.get("records") if isinstance(payload.get("records"), list) else []
    expected = {item["clip_id"]: item for item in expected_records()}
    actual = {item.get("clip_id"): item for item in rows if isinstance(item, dict)}
    if set(actual) != set(expected):
        errors.append("manifest must contain the fixed 29 supplemental records")
    for clip_id, specification in expected.items():
        row = actual.get(clip_id, {})
        for field in ("scenario_id", "record_role", "target", "expected_assessment", "label_status"):
            if row.get(field) != specification[field]:
                errors.append(f"{clip_id}: locked field changed: {field}")
        if media_root is not None:
            relative = row.get("media_relpath")
            if not isinstance(relative, str) or not relative:
                errors.append(f"{clip_id}: media_relpath is required")
                continue
            target = (media_root / relative).resolve()
            try:
                target.relative_to(media_root.resolve())
            except ValueError:
                errors.append(f"{clip_id}: media path escapes media root")
                continue
            if not target.is_file():
                errors.append(f"{clip_id}: media file is missing")
                continue
            actual_hash = sha256_file(target)
            if row.get("sha256") != actual_hash:
                errors.append(f"{clip_id}: sha256 mismatch")
            if row.get("byte_size") != target.stat().st_size:
                errors.append(f"{clip_id}: byte_size mismatch")
            if not row.get("capture_date"):
                errors.append(f"{clip_id}: capture_date is required")
    counts = {
        role: sum(item.get("record_role") == role for item in rows if isinstance(item, dict))
        for role in ("TEST", "QUALITY", "GOLDEN")
    }
    if counts != {"TEST": 24, "QUALITY": 4, "GOLDEN": 1}:
        errors.append("record role counts must be TEST=24, QUALITY=4, GOLDEN=1")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "counts": counts, "payload": payload}


def lock(
    manifest: Path, media_root: Path, baseline_manifest: Path,
    baseline_results: Path, evaluation_spec: Path, output_dir: Path,
    visual_review: Path = DEFAULT_VISUAL_REVIEW,
) -> dict[str, Any]:
    output_dir = safe_output(output_dir)
    report = validate_manifest(manifest, media_root)
    if report["status"] != "PASS":
        raise ValueError("MANIFEST_INVALID: " + "; ".join(report["errors"]))
    baseline = json.loads(baseline_manifest.read_text(encoding="utf-8"))
    if baseline.get("valid_record_count") != 17 or baseline.get("calendar_dates") != ["2026-08-17", "2026-08-18", "2026-08-19"]:
        raise ValueError("BASELINE_MANIFEST_INVALID")
    baseline_snapshot = json.loads(baseline_results.read_text(encoding="utf-8"))
    admitted = sum(bool(item.get("admitted")) for item in baseline_snapshot.get("records", []))
    if (
        baseline_snapshot.get("schema_version") != "supplemental-baseline-results/1.0"
        or baseline_snapshot.get("baseline_status") != "PROVISIONAL"
        or baseline_snapshot.get("manifest_sha256") != sha256_file(baseline_manifest)
        or admitted != 17
    ):
        raise ValueError("BASELINE_RESULTS_INVALID")
    visual = json.loads(visual_review.read_text(encoding="utf-8"))
    visual_rows = {item.get("clip_id"): item for item in visual.get("records", [])}
    manifest_rows = {item.get("clip_id"): item for item in report["payload"]["records"]}
    if (
        visual.get("schema_version") != "supplemental-visual-review/1.1"
        or visual.get("human_signoff_status") != "CONFIRMED_BY_CAPTURE_TEAM"
        or visual.get("team_confirmation", {}).get("status") != "ACCEPTED"
        or set(visual_rows) != set(manifest_rows)
    ):
        raise ValueError("VISUAL_REVIEW_CONFIRMATION_INVALID")
    for clip_id, row in manifest_rows.items():
        reviewed = visual_rows[clip_id]
        if (
            reviewed.get("review_status") != "VALID"
            or reviewed.get("human_signoff_status") != "CONFIRMED_BY_CAPTURE_TEAM"
            or reviewed.get("algorithm_output_consulted") is not False
            or reviewed.get("media_relpath") != row.get("media_relpath")
            or str(reviewed.get("sha256", "")).lower() != str(row.get("sha256", "")).lower()
            or reviewed.get("byte_size") != row.get("byte_size")
        ):
            raise ValueError(f"VISUAL_REVIEW_RECORD_INVALID: {clip_id}")
    output_dir.mkdir(parents=True)
    locked_manifest = output_dir / "locked-manifest.json"
    shutil.copy2(manifest, locked_manifest)
    bindings = {
        "locked_manifest": locked_manifest, "baseline_manifest": baseline_manifest,
        "baseline_results": baseline_results,
        "ruleset": DEFAULT_RULESET, "model": DEFAULT_MODEL,
        "executor": Path(__file__).resolve(), "evaluation_spec": evaluation_spec,
        "visual_review": visual_review,
    }
    for name, path in bindings.items():
        if not path.is_file():
            raise ValueError(f"missing freeze input: {name}")
    payload = {
        "schema_version": "supplemental-validation-lock/1.0", "status": "LOCKED",
        "experiment_id": "supplemental-validation-v1.4",
        "locked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "records": 29, "valid_baseline_records": 17,
        "bindings": {
            name: {"path": str(path.resolve()), "sha256": sha256_file(path)}
            for name, path in bindings.items()
        },
        "media": [
            {"clip_id": row["clip_id"], "path": row["media_relpath"], "sha256": row["sha256"], "bytes": row["byte_size"]}
            for row in report["payload"]["records"]
        ],
    }
    write_new(output_dir / "lock.json", payload)
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['path']}" for item in payload["media"]) + "\n",
        encoding="utf-8",
    )
    return payload


def verify_lock(lock_path: Path, media_root: Path | None = None) -> dict[str, Any]:
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for name, binding in payload.get("bindings", {}).items():
        path = Path(binding.get("path", ""))
        if not path.is_file() or sha256_file(path) != binding.get("sha256"):
            errors.append(f"freeze binding changed: {name}")
    if media_root is not None:
        resolved_root = media_root.resolve()
        for item in payload.get("media", []):
            path = (resolved_root / item["path"]).resolve()
            try:
                path.relative_to(resolved_root)
            except ValueError:
                errors.append(f"locked media escapes root: {item['clip_id']}")
                continue
            if not path.is_file() or sha256_file(path) != item["sha256"]:
                errors.append(f"locked media changed: {item['clip_id']}")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "payload": payload}


def _personal_speed_evidence(observation: Any, baseline: dict[str, Any], ruleset: Ruleset) -> SimpleNamespace | None:
    stats = baseline.get("baselines", {}).get("relative_gait_speed", {})
    assessment = assess_relative_gait_speed(float(observation.feature_value), stats, ruleset)
    if assessment["status"] != "EVIDENCE":
        return None
    current = float(observation.feature_value)
    return SimpleNamespace(
        evidence_id=f"evi-personal-{observation.observation_id}", evidence_type="relative_speed_change",
        timestamp=observation.timestamp, confidence=observation.confidence,
        data_quality=observation.data_quality, severity=assessment["severity"],
        observation_ids=[observation.observation_id], source_mode=observation.source_mode,
        simulated=observation.simulated, risk_domain="FALL", current_value=current,
        baseline_value=assessment["baseline_median"], baseline_deviation=assessment["deviation"],
        baseline_mad=assessment["baseline_mad"], baseline_status=assessment["baseline_status"],
    )


def _memory_filtered_evidence(
    evidences: list[Any], config: dict[str, bool],
) -> list[Any]:
    retained = []
    for evidence in evidences:
        raw_scale = getattr(evidence, "time_scale", "SHORT")
        scale = getattr(raw_scale, "value", raw_scale)
        if scale == "MEDIUM" and not config["medium_memory"]:
            continue
        if scale == "LONG" and not config["long_memory"]:
            continue
        retained.append(evidence)
    return retained


async def _run_record(
    row: dict[str, Any], media_root: Path, baseline: dict[str, Any],
    config_id: str, config: dict[str, bool], ruleset: Ruleset,
) -> dict[str, Any]:
    path = (media_root / row["media_relpath"]).resolve()
    job = AlgorithmJob(
        schema_version="algorithm-job/1.0", job_id=f"sv14-{config_id}-{row['clip_id']}",
        correlation_id=f"sv14-{config_id}-{row['clip_id']}", resident_id="resident-sv01",
        asset_id=f"asset-{row['clip_id']}", media_type=MediaType.VIDEO, media_locator=str(path),
        captured_at=f"{row['capture_date']}T12:00:00+08:00", source_mode="RECORDED_REPLAY",
        simulated=True, location="living_room", camera_position_id=row["camera_position_id"],
        scene_config_id="supplemental-v14-fixed-scene", requested_modules=[AlgorithmModule.GAIT], deadline_ms=120000,
    )
    started = time.perf_counter()
    batch = await run_with_config(
        job,
        quality_gate=config["quality_gate"],
        offline_ablation=bool(config.get("offline_only")),
    )
    evidences = _memory_filtered_evidence(list(batch.evidences), config)
    if config["personal_baseline"]:
        speed = next((item for item in batch.observations if item.feature_name == "step_speed_norm_s"), None)
        personal = _personal_speed_evidence(speed, baseline, ruleset) if speed is not None else None
        if personal is not None:
            evidences.append(personal)
    policy = FallDecisionPolicy(ruleset)
    previous_state = "GREEN"
    active_status = None
    active_created_at = None
    decisions = []
    recent: list[Any] = []
    for evidence in evidences:
        recent.append(evidence)
        decision = policy.evaluate(
            now=evidence.timestamp, previous_state=previous_state, active_status=active_status,
            active_created_at=active_created_at, recovery_started_at=None, recent=recent,
            trigger=evidence, context_score=0.0,
        )
        decisions.append({"evidence_id": evidence.evidence_id, "matched_rule": decision.matched_rule, "risk_level": decision.risk_level, "action": decision.action})
        previous_state = decision.risk_level
        if decision.action == "CREATE_EVENT":
            active_status, active_created_at = decision.next_status, evidence.timestamp
    orange = any(item["action"] == "CREATE_EVENT" and item["risk_level"] == "ORANGE" for item in decisions)
    trend_alert = any(item.evidence_type in {"relative_speed_change", "gait_instability"} and item.confidence >= 0.7 and item.data_quality >= 0.7 for item in evidences)
    quality_gate = batch.status.value == "LOW_QUALITY" or any(item.evidence_type == "assessment_indeterminate" for item in evidences)
    feature_values = {
        item.feature_name: item.feature_value
        for item in batch.observations
    }
    return {
        "clip_id": row["clip_id"], "scenario_id": row["scenario_id"], "record_role": row["record_role"],
        "captured_at": job.captured_at.isoformat(),
        "config_id": config_id, "adapter_status": batch.status.value,
        "assessment_status": "INSUFFICIENT" if quality_gate else "VALID",
        "orange": orange, "trend_alert": trend_alert, "quality_gate": quality_gate,
        "evidence_types": [item.evidence_type for item in evidences], "decisions": decisions,
        "feature_values": feature_values,
        "memory_layers": {
            "short": True,
            "medium": bool(config["medium_memory"]),
            "long": bool(config["long_memory"]),
            "personal_baseline": bool(config["personal_baseline"]),
        },
        "processing_latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "diagnostics": batch.diagnostics,
    }


def golden_loop_acceptance(record: dict[str, Any], ruleset: Ruleset) -> dict[str, Any]:
    """Evaluate the recorded closed-loop claims separately from performance metrics."""
    states: list[str] = []
    transitions: list[dict[str, Any]] = []
    intervention: dict[str, Any] | None = None
    if record["orange"]:
        states.extend(("ORANGE", "INTERVENING"))
        tool_result = asyncio.run(MockVoiceTool().execute(
            SimpleNamespace(event_id=f"golden-{record['clip_id']}"),
            "Please remain stable while the system continues observing.",
        ))
        intervention = {
            "tool": tool_result.tool_name,
            "delivery_status": tool_result.delivery_status,
            "simulated": tool_result.simulated,
        }
    feature_values = record.get("feature_values", {})
    stable_duration = float(feature_values.get("stable_posture_duration", 0.0) or 0.0)
    recovered = "posture_recovered" in record.get("evidence_types", [])
    clip_duration = float(record.get("diagnostics", {}).get("duration_s", 0.0) or 0.0)
    clip_start = datetime.fromisoformat(record["captured_at"])
    clip_end = clip_start + timedelta(seconds=clip_duration)
    stable_window_start = clip_end - timedelta(seconds=stable_duration)
    recovery_at = stable_window_start + timedelta(
        seconds=float(ruleset.thresholds["stable_posture_seconds"])
    )
    resolve_at = recovery_at + timedelta(
        seconds=float(ruleset.thresholds["observation_seconds"])
    )
    temporal_coverage = (
        clip_duration > 0
        and stable_window_start > clip_start
        and recovery_at < resolve_at <= clip_end
    )
    policy = FallDecisionPolicy(ruleset)
    if record["orange"] and recovered and temporal_coverage:
        recovery = SimpleNamespace(
            evidence_id=f"evi-golden-recovery-{record['clip_id']}",
            evidence_type="posture_recovered",
            timestamp=recovery_at,
            confidence=0.9,
            data_quality=0.9,
            severity=0.0,
            current_value=stable_duration,
            risk_domain="FALL",
            observation_ids=[f"obs-golden-recovery-{record['clip_id']}"],
            source_mode="RECORDED_REPLAY",
            simulated=True,
        )
        observing = policy.evaluate(
            now=recovery_at,
            previous_state="ORANGE",
            active_status="INTERVENING",
            active_created_at=clip_start,
            recovery_started_at=None,
            recent=[recovery],
            trigger=recovery,
        )
        transitions.append({
            "at": recovery_at.isoformat(),
            "matched_rule": observing.matched_rule,
            "action": observing.action,
            "next_status": observing.next_status,
        })
        if observing.action == "BEGIN_OBSERVING" and observing.next_status == "OBSERVING":
            states.append("OBSERVING")
            resolved = policy.evaluate(
                now=resolve_at,
                previous_state="ORANGE",
                active_status="OBSERVING",
                active_created_at=clip_start,
                recovery_started_at=recovery_at,
                recent=[recovery],
                trigger=None,
            )
            transitions.append({
                "at": resolve_at.isoformat(),
                "matched_rule": resolved.matched_rule,
                "action": resolved.action,
                "next_status": resolved.next_status,
            })
            if resolved.action == "RESOLVE" and resolved.next_status == "RESOLVED":
                states.append("RESOLVED")
    expected = ["ORANGE", "INTERVENING", "OBSERVING", "RESOLVED"]
    return {
        "schema_version": "supplemental-v14-golden-loop/1.0",
        "status": "PASS" if states == expected else "FAIL",
        "clip_id": record["clip_id"],
        "observed_sequence": states,
        "expected_sequence": expected,
        "stable_posture_duration_s": stable_duration,
        "clip_duration_s": clip_duration,
        "derived_stable_window_start": stable_window_start.isoformat(),
        "derived_recovery_at": recovery_at.isoformat(),
        "derived_resolve_at": resolve_at.isoformat(),
        "recorded_temporal_coverage": temporal_coverage,
        "required_observation_seconds": ruleset.thresholds["observation_seconds"],
        "audio_provenance": "SCRIPTED_AUDIO_PROMPT",
        "intervention": intervention,
        "state_machine_transitions": transitions,
        "included_in_performance_metrics": False,
        "claim_boundary": "Offline recorded-replay chain acceptance; no EZVIZ device audio claim.",
        "record": record,
    }


def run_locked(lock_path: Path, media_root: Path, baseline_results: Path, output_dir: Path) -> dict[str, Any]:
    output_dir = safe_output(output_dir)
    lock_report = verify_lock(lock_path, media_root)
    if lock_report["status"] != "PASS":
        raise ValueError("LOCK_INVALID: " + "; ".join(lock_report["errors"]))
    locked_baseline = lock_report["payload"].get("bindings", {}).get("baseline_results", {})
    if sha256_file(baseline_results) != locked_baseline.get("sha256"):
        raise ValueError("LOCKED_BASELINE_RESULTS_MISMATCH")
    manifest_path = Path(lock_report["payload"]["bindings"]["locked_manifest"]["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_results.read_text(encoding="utf-8"))
    ruleset = load_ruleset_version("ruleset-v1.4")
    output_dir.mkdir(parents=True)
    configs = ruleset.ablation_configs or {}
    performance_rows = [row for row in manifest["records"] if row["record_role"] != "GOLDEN"]
    golden_rows = [row for row in manifest["records"] if row["record_role"] == "GOLDEN"]
    if len(performance_rows) != 28 or len(golden_rows) != 1:
        raise ValueError("LOCKED_MANIFEST_ROLE_COUNTS_INVALID")
    all_results = {}
    for config_id in ("A", "B", "C", "D"):
        config = configs[config_id]
        records = [
            asyncio.run(_run_record(row, media_root, baseline, config_id, config, ruleset))
            for row in performance_rows
        ]
        config_payload = {
            "schema_version": "supplemental-v14-inference/1.0", "config_id": config_id,
            "config": config, "record_count": len(records), "records_sha256": sha256_json(records),
            "records": records,
        }
        config_dir = output_dir / config_id
        config_dir.mkdir()
        (config_dir / "inference-results.json").write_text(json.dumps(config_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        all_results[config_id] = config_payload
    golden_record = asyncio.run(
        _run_record(golden_rows[0], media_root, baseline, "A", configs["A"], ruleset)
    )
    golden_result = golden_loop_acceptance(golden_record, ruleset)
    golden_dir = output_dir / "golden-loop"
    golden_dir.mkdir()
    (golden_dir / "golden-loop-results.json").write_text(
        json.dumps(golden_result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "schema_version": "supplemental-v14-ablation-run/1.0", "status": "COMPLETE",
        "lock_sha256": sha256_file(lock_path), "baseline_results_sha256": sha256_file(baseline_results),
        "configs": {key: {"records_sha256": value["records_sha256"], "record_count": value["record_count"]} for key, value in all_results.items()},
        "performance_record_count": 28,
        "golden_loop": {
            "status": golden_result["status"],
            "result_path": str((golden_dir / "golden-loop-results.json").resolve()),
            "audio": "SCRIPTED_AUDIO_PROMPT",
            "intervention": "mock_voice",
            "simulated": True,
            "included_in_metrics": False,
        },
    }
    (output_dir / "run-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if not total:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def _rate(value: int, total: int) -> dict[str, Any]:
    return {"numerator": value, "denominator": total, "rate": round(value / total, 6) if total else None, "wilson_95": wilson(value, total)}


def confusion(records: list[dict[str, Any]], positive: Callable[[dict[str, Any]], bool], negative: Callable[[dict[str, Any]], bool], prediction: str) -> dict[str, Any]:
    selected = [item for item in records if positive(item) or negative(item)]
    tp = sum(positive(item) and bool(item[prediction]) for item in selected)
    fn = sum(positive(item) and not bool(item[prediction]) for item in selected)
    fp = sum(negative(item) and bool(item[prediction]) for item in selected)
    tn = sum(negative(item) and not bool(item[prediction]) for item in selected)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    return {
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "precision": None if precision is None else round(precision, 6),
        "recall": None if recall is None else round(recall, 6),
        "f1": None if f1 is None else round(f1, 6),
        "specificity": None if specificity is None else round(specificity, 6),
        "false_positive_rate": None if specificity is None else round(1 - specificity, 6),
        "precision_wilson_95": wilson(tp, tp + fp),
        "recall_wilson_95": wilson(tp, tp + fn),
        "specificity_wilson_95": wilson(tn, tn + fp),
        "false_positive_rate_wilson_95": wilson(fp, fp + tn),
    }


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    return round(ordered[low] if low == high else ordered[low] + (ordered[high] - ordered[low]) * (position - low), 3)


def analyze(run_dir: Path, output: Path) -> dict[str, Any]:
    results = {}
    for config_id in ("A", "B", "C", "D"):
        source = json.loads((run_dir / config_id / "inference-results.json").read_text(encoding="utf-8"))
        records = source["records"]
        test = lambda item: item["record_role"] == "TEST"
        negative = lambda item: item["scenario_id"].startswith("NEG_")
        immediate = confusion(
            records,
            lambda item: item["scenario_id"] == "POS_RAPID_RISE_SWAY",
            lambda item: test(item) and item["scenario_id"] != "POS_RAPID_RISE_SWAY",
            "orange",
        )
        trend = confusion(
            records,
            lambda item: item["scenario_id"] in {"POS_SLOW_SMALL_STEP_SWAY", "POS_ASYMMETRIC_STEP"},
            negative,
            "trend_alert",
        )
        quality = confusion(
            records,
            lambda item: item["record_role"] == "QUALITY",
            test,
            "quality_gate",
        )
        scenarios = {}
        targets = {
            "POS_SLOW_SMALL_STEP_SWAY": {"gait_instability", "relative_speed_change"},
            "POS_ASYMMETRIC_STEP": {"gait_instability"},
        }
        for scenario, target_types in targets.items():
            rows = [item for item in records if item["scenario_id"] == scenario]
            scenarios[scenario] = {
                "any_target": _rate(
                    sum(bool(set(item["evidence_types"]) & target_types) for item in rows),
                    len(rows),
                ),
                "by_type": {
                    evidence_type: _rate(
                        sum(evidence_type in item["evidence_types"] for item in rows),
                        len(rows),
                    )
                    for evidence_type in sorted(target_types)
                },
            }
        metric_records = [item for item in records if item["record_role"] != "GOLDEN"]
        latencies = [float(item["processing_latency_ms"]) for item in metric_records]
        results[config_id] = {
            "immediate_orange": immediate, "gait_trend": trend, "quality_gate": quality,
            "target_evidence_by_scenario": scenarios,
            "offline_processing_latency_ms": {"median": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95), "max": max(latencies) if latencies else None},
        }
    payload = {
        "schema_version": "supplemental-v14-metrics/1.0", "status": "COMPLETE",
        "ruleset_version": "ruleset-v1.4", "configs": results,
        "latency_claim_boundary": "Offline end-to-end processing time; not real-time alarm latency.",
        "p03_replaced": False, "golden_loop_included_in_metrics": False,
    }
    write_new(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("template"); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("validate"); p.add_argument("--manifest", type=Path, required=True); p.add_argument("--media-root", type=Path)
    p = sub.add_parser("lock"); p.add_argument("--manifest", type=Path, required=True); p.add_argument("--media-root", type=Path, required=True); p.add_argument("--baseline-manifest", type=Path, default=DEFAULT_BASELINE_MANIFEST); p.add_argument("--baseline-results", type=Path, default=DEFAULT_BASELINE_RESULTS); p.add_argument("--evaluation-spec", type=Path, default=DEFAULT_SPEC); p.add_argument("--visual-review", type=Path, default=DEFAULT_VISUAL_REVIEW); p.add_argument("--output-dir", type=Path, required=True)
    p = sub.add_parser("verify-lock"); p.add_argument("--lock", type=Path, required=True); p.add_argument("--media-root", type=Path)
    p = sub.add_parser("run"); p.add_argument("--lock", type=Path, required=True); p.add_argument("--media-root", type=Path, required=True); p.add_argument("--baseline-results", type=Path, required=True); p.add_argument("--output-dir", type=Path, required=True)
    p = sub.add_parser("analyze"); p.add_argument("--run-dir", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "template": result = template(args.output.resolve())
    elif args.command == "validate": result = validate_manifest(args.manifest.resolve(), args.media_root.resolve() if args.media_root else None)
    elif args.command == "lock": result = lock(args.manifest.resolve(), args.media_root.resolve(), args.baseline_manifest.resolve(), args.baseline_results.resolve(), args.evaluation_spec.resolve(), args.output_dir.resolve(), args.visual_review.resolve())
    elif args.command == "verify-lock": result = verify_lock(args.lock.resolve(), args.media_root.resolve() if args.media_root else None)
    elif args.command == "run": result = run_locked(args.lock.resolve(), args.media_root.resolve(), args.baseline_results.resolve(), args.output_dir.resolve())
    else: result = analyze(args.run_dir.resolve(), args.output.resolve())
    print(json.dumps({key: value for key, value in result.items() if key not in {"payload", "records", "configs"}}, ensure_ascii=False, indent=2))
    return 0 if result.get("status") not in {"FAIL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
