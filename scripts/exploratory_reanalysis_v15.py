"""Run a non-blind v1.5 exploratory reanalysis without touching v1.4 outputs."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.v1.algorithm import AlgorithmJob, AlgorithmModule, MediaType  # noqa: E402
from contracts.v1.decision import FallDecisionPolicy  # noqa: E402
from contracts.v1.gait_adapter_v15 import run_with_config  # noqa: E402
from contracts.v1.memory import assess_relative_gait_speed  # noqa: E402
from contracts.v1.ruleset import load_ruleset_version  # noqa: E402
from scripts.supplemental_validation_v14 import confusion, percentile, sha256_file, write_new  # noqa: E402


RULESET = load_ruleset_version("ruleset-v1.5")
FORMAL_V14 = ROOT / "experiments" / "supplemental-validation-v1.4" / "results"
P03_PROTECTED = (ROOT / "experiments" / "three-participant").resolve()
RULESET_PATH = ROOT / "contracts" / "v1" / "rulesets" / "ruleset-v1.5.json"
ADAPTER_PATH = ROOT / "contracts" / "v1" / "gait_adapter_v15.py"
EXTRACTOR_PATH = ROOT / "contracts" / "v1" / "gait_video.py"
EXECUTOR_PATH = Path(__file__).resolve()


def safe_output(path: Path) -> Path:
    target = path.resolve()
    try:
        target.relative_to(P03_PROTECTED)
    except ValueError:
        pass
    else:
        raise ValueError("v1.5 exploratory outputs cannot target P03")
    if target.exists():
        raise ValueError(f"refusing to overwrite output: {target}")
    return target


def _v15_baseline(v14_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Bind the frozen three-date baseline to an explicit WALK context."""
    speed = dict(v14_snapshot["baselines"]["relative_gait_speed"])
    return {
        "schema_version": "exploratory-v15-context-baseline/1.0",
        "source_ruleset": "ruleset-v1.4",
        "ruleset_version": "ruleset-v1.5",
        "baseline_status": v14_snapshot["baseline_status"],
        "baselines_by_context": {"WALK": {"relative_gait_speed": speed}},
        "unavailable_contexts": ["POST_RISE_LOCOMOTION", "RISE_ONLY", "STATIC_OR_UNKNOWN"],
        "policy": "No cross-context fallback. Missing context returns a degradation reason.",
        "claim_boundary": "Reuses the frozen normal WALK baseline; no new baseline fitting on TEST media.",
    }


def _personal_evidence(observation: Any, baseline: dict[str, Any]) -> Any | None:
    metadata = dict(observation.metadata or {})
    context = metadata.get("activity_context")
    if (
        float(metadata.get("locomotion_duration_s") or 0.0)
        < float(RULESET.thresholds["relative_speed_min_locomotion_seconds"])
        or int(metadata.get("gait_cycle_count") or 0)
        < int(RULESET.thresholds["gait_min_complete_cycles"])
    ):
        return None
    stats = baseline.get("baselines_by_context", {}).get(context, {}).get("relative_gait_speed")
    if not stats:
        return None
    assessment = assess_relative_gait_speed(float(observation.feature_value), stats, RULESET)
    if assessment["status"] != "EVIDENCE":
        return None
    return SimpleNamespace(
        evidence_id=f"evi-v15-personal-{observation.observation_id}",
        evidence_type="relative_speed_change", timestamp=observation.timestamp,
        confidence=observation.confidence, data_quality=observation.data_quality,
        severity=assessment["severity"], observation_ids=[observation.observation_id],
        source_mode=observation.source_mode, simulated=observation.simulated,
        risk_domain="FALL", current_value=float(observation.feature_value),
        baseline_value=assessment["baseline_median"], baseline_deviation=assessment["deviation"],
        baseline_status=assessment["baseline_status"], activity_context=context,
        time_scale="MEDIUM",
    )


async def _run_record(
    row: dict[str, Any], media_root: Path, baseline: dict[str, Any],
) -> dict[str, Any]:
    path = (media_root / row["media_relpath"]).resolve()
    path.relative_to(media_root.resolve())
    if sha256_file(path) != row["sha256"]:
        raise ValueError(f"media hash mismatch: {row['clip_id']}")
    job = AlgorithmJob(
        schema_version="algorithm-job/1.0", job_id=f"v15-exploratory-{row['clip_id']}",
        correlation_id=f"v15-exploratory-{row['clip_id']}", resident_id="resident-sv01",
        asset_id=f"asset-{row['clip_id']}", media_type=MediaType.VIDEO,
        media_locator=str(path), captured_at=f"{row['capture_date']}T12:00:00+08:00",
        source_mode="RECORDED_REPLAY", simulated=True, location="living_room",
        camera_position_id=row["camera_position_id"],
        scene_config_id="supplemental-v15-exploratory-scene",
        requested_modules=[AlgorithmModule.GAIT], deadline_ms=120000,
    )
    started = time.perf_counter()
    batch = await run_with_config(job, quality_gate=True)
    evidences = list(batch.evidences)
    speed = next((item for item in batch.observations if item.feature_name == "step_speed_norm_s"), None)
    personal = _personal_evidence(speed, baseline) if speed is not None else None
    if personal is not None:
        evidences.append(personal)
    policy = FallDecisionPolicy(RULESET)
    recent: list[Any] = []
    decisions = []
    previous = "GREEN"
    active_status = active_created_at = None
    for evidence in evidences:
        recent.append(evidence)
        decision = policy.evaluate(
            now=evidence.timestamp, previous_state=previous, active_status=active_status,
            active_created_at=active_created_at, recovery_started_at=None,
            recent=recent, trigger=evidence, context_score=0.0,
        )
        decisions.append({
            "evidence_id": evidence.evidence_id, "matched_rule": decision.matched_rule,
            "risk_level": decision.risk_level, "action": decision.action,
        })
        previous = decision.risk_level
        if decision.action == "CREATE_EVENT":
            active_status, active_created_at = decision.next_status, evidence.timestamp
    quality_gate = batch.status.value == "LOW_QUALITY"
    trend_candidates = [
        item for item in evidences
        if item.evidence_type in {"relative_speed_change", "gait_instability"}
        and item.confidence >= 0.7 and item.data_quality >= 0.7
    ]
    features = {item.feature_name: item.feature_value for item in batch.observations}
    return {
        "clip_id": row["clip_id"], "scenario_id": row["scenario_id"],
        "record_role": row["record_role"], "adapter_status": batch.status.value,
        "assessment_status": "INSUFFICIENT" if quality_gate else "VALID",
        "orange": any(item["action"] == "CREATE_EVENT" for item in decisions),
        "trend_candidate": bool(trend_candidates),
        "persistent_trend_alert": False,
        "trend_persistence_reason": "ONE_CLIP_IS_ONE_ACTIVITY_WINDOW; TWO_INDEPENDENT_WINDOWS_REQUIRED",
        "quality_gate": quality_gate, "evidence_types": [item.evidence_type for item in evidences],
        "decisions": decisions, "feature_values": features,
        "activity_context": batch.diagnostics.get("activity_context"),
        "processing_latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "diagnostics": batch.diagnostics,
    }


def _wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if not total:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def run(
    manifest_path: Path, media_root: Path, baseline_path: Path,
    v14_metrics_path: Path, output_dir: Path,
) -> dict[str, Any]:
    output_dir = safe_output(output_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline_source = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline = _v15_baseline(baseline_source)
    output_dir.mkdir(parents=True)
    records = [asyncio.run(_run_record(row, media_root, baseline)) for row in manifest["records"]]
    performance = [item for item in records if item["record_role"] != "GOLDEN"]
    test = lambda item: item["record_role"] == "TEST"
    negative = lambda item: item["scenario_id"].startswith("NEG_")
    metrics = {
        "immediate_orange": confusion(
            performance,
            lambda item: item["scenario_id"] == "POS_RAPID_RISE_SWAY",
            lambda item: test(item) and item["scenario_id"] != "POS_RAPID_RISE_SWAY",
            "orange",
        ),
        "single_window_trend_candidate": confusion(
            performance,
            lambda item: item["scenario_id"] in {"POS_SLOW_SMALL_STEP_SWAY", "POS_ASYMMETRIC_STEP"},
            negative, "trend_candidate",
        ),
        "persistent_trend_alert": confusion(
            performance,
            lambda item: item["scenario_id"] in {"POS_SLOW_SMALL_STEP_SWAY", "POS_ASYMMETRIC_STEP"},
            negative, "persistent_trend_alert",
        ),
        "quality_gate": confusion(performance, lambda item: item["record_role"] == "QUALITY", test, "quality_gate"),
        "offline_processing_latency_ms": {
            "median": percentile([item["processing_latency_ms"] for item in performance], 0.5),
            "p95": percentile([item["processing_latency_ms"] for item in performance], 0.95),
            "max": max(item["processing_latency_ms"] for item in performance),
        },
    }
    golden = next(item for item in records if item["record_role"] == "GOLDEN")
    v14_hash_before = sha256_file(v14_metrics_path)
    payload = {
        "schema_version": "exploratory-v15-reanalysis/1.0", "status": "COMPLETE",
        "ruleset_version": RULESET.version, "classification": "EXPLORATORY_REANALYSIS",
        "not_formal_blind_validation": True, "media_previously_inspected": True,
        "labels_changed": False, "formal_v14_replaced": False,
        "inputs": {
            "manifest_sha256": sha256_file(manifest_path),
            "baseline_source_sha256": sha256_file(baseline_path),
            "formal_v14_metrics_sha256_before": v14_hash_before,
            "ruleset_sha256": sha256_file(RULESET_PATH),
            "adapter_sha256": sha256_file(ADAPTER_PATH),
            "extractor_sha256": sha256_file(EXTRACTOR_PATH),
            "executor_sha256": sha256_file(EXECUTOR_PATH),
        },
        "baseline": baseline, "record_count": len(records), "records": records,
        "metrics": metrics,
        "golden_loop": {
            "status": "PASS" if golden["orange"] else "FAIL",
            "orange": golden["orange"], "included_in_metrics": False,
            "claim_boundary": "Exploratory recorded replay; no real device audio claim.",
        },
        "limitations": [
            "Existing 29 clips were already inspected and cannot become a new blind test set.",
            "A single clip is one activity window; persistent trend alert requires two independent windows.",
            "No missing immediate signal family is synthesized.",
            "Furniture occlusion remains a limitation unless an observable proxy crosses the fixed gate.",
        ],
    }
    write_new(output_dir / "exploratory-results.json", payload)
    if sha256_file(v14_metrics_path) != v14_hash_before:
        raise RuntimeError("formal v1.4 metrics changed during exploratory analysis")
    checksums = [
        ("exploratory-results.json", sha256_file(output_dir / "exploratory-results.json")),
        (str(manifest_path), sha256_file(manifest_path)),
        (str(baseline_path), sha256_file(baseline_path)),
        (str(v14_metrics_path), sha256_file(v14_metrics_path)),
        (str(RULESET_PATH), sha256_file(RULESET_PATH)),
        (str(ADAPTER_PATH), sha256_file(ADAPTER_PATH)),
        (str(EXTRACTOR_PATH), sha256_file(EXTRACTOR_PATH)),
        (str(EXECUTOR_PATH), sha256_file(EXECUTOR_PATH)),
    ]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(f"{digest}  {name}" for name, digest in checksums) + "\n", encoding="utf-8"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--v14-metrics", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(
        args.manifest.resolve(), args.media_root.resolve(), args.baseline.resolve(),
        args.v14_metrics.resolve(), args.output_dir.resolve(),
    )
    print(json.dumps({
        "status": result["status"], "classification": result["classification"],
        "record_count": result["record_count"], "golden_loop": result["golden_loop"]["status"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
