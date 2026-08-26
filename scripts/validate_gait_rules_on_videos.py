"""Run gait-adapter-v1.2 and ruleset-v1.2 on private labeled replay videos."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from contracts.v1.algorithm import AlgorithmJob, AlgorithmModule, MediaType
from contracts.v1.decision import FallDecisionPolicy
from contracts.v1.gait_adapter import ADAPTER_VERSION, run
from contracts.v1.ruleset import load_ruleset


REPORT_DIAGNOSTIC_KEYS = (
    "rise_window_start_s",
    "rise_window_end_s",
    "trunk_sway_window_type",
    "trunk_sway_window_start_s",
    "trunk_sway_window_end_s",
    "trunk_sway_sample_count",
    "trunk_sway_p5_deg",
    "trunk_sway_p95_deg",
    "trunk_sway_failure_reason",
    "sit_to_stand_transition_confirmed",
    "assessment_status",
    "assessment_reason_code",
    "post_rise_tracking_ratio",
    "post_rise_orientation_quality",
)

REPORT_FEATURE_KEYS = {
    "assessment_status",
    "assessment_reason_code",
    "sit_to_stand_transition_confirmed",
    "rise_duration_s",
    "trunk_sway_angle_deg",
    "post_rise_sway_reversal_count",
    "post_rise_pelvis_lateral_excursion_norm",
    "post_rise_support_width_change_norm",
    "post_rise_compensatory_step_count",
    "post_rise_tracking_ratio",
    "post_rise_orientation_quality",
    "post_rise_locomotion_detected",
    "step_asymmetry_ratio",
    "valid_frame_ratio",
}


@dataclass(frozen=True)
class Case:
    case_ref: str
    expected: str
    path: Path


def _parse_case(value: str) -> Case:
    parts = value.split("|", 2)
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise argparse.ArgumentTypeError("case must be CASE_REF|EXPECTED|PRIVATE_VIDEO_PATH")
    case_ref, expected, raw_path = (part.strip() for part in parts)
    if expected not in {"ORANGE", "YELLOW", "UNKNOWN", "GREEN", "NO_ORANGE"}:
        raise argparse.ArgumentTypeError(
            "EXPECTED must be ORANGE, YELLOW, UNKNOWN, GREEN, or NO_ORANGE"
        )
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError("private video is not readable")
    return Case(case_ref=case_ref, expected=expected, path=path)


def _matches_expected(expected: str, risk_level: str) -> bool:
    if expected == "NO_ORANGE":
        return risk_level != "ORANGE"
    return risk_level == expected


def _sanitized_diagnostics(diagnostics: dict) -> dict:
    return {
        key: diagnostics[key]
        for key in REPORT_DIAGNOSTIC_KEYS
        if diagnostics.get(key) is not None
    }


async def _evaluate_case(case: Case, index: int) -> dict:
    captured_at = datetime.now(timezone.utc).astimezone()
    job = AlgorithmJob(
        schema_version="algorithm-job/1.0",
        job_id=f"job-private-rule-validation-{index:03d}",
        correlation_id=f"corr-private-rule-validation-{index:03d}",
        resident_id=f"resident-private-validation-{index:03d}",
        asset_id=f"asset-private-validation-{index:03d}",
        media_type=MediaType.VIDEO,
        media_locator=str(case.path),
        captured_at=captured_at,
        source_mode="RECORDED_REPLAY",
        simulated=True,
        location="authorized_test_scene",
        camera_position_id="camera-position-private-validation",
        scene_config_id="scene-config-private-validation",
        requested_modules=[AlgorithmModule.GAIT],
        deadline_ms=120_000,
    )
    batch = await run(job)
    policy = FallDecisionPolicy(load_ruleset())
    decision = policy.evaluate(
        now=captured_at,
        previous_state="GREEN",
        active_status=None,
        active_created_at=None,
        recovery_started_at=None,
        recent=list(batch.evidences),
        trigger=None,
    )
    features = {
        item.feature_name: item.feature_value
        for item in batch.observations
        if item.feature_name in REPORT_FEATURE_KEYS
    }
    diagnostics = _sanitized_diagnostics(batch.diagnostics)
    return {
        "case_ref": case.case_ref,
        "expected": case.expected,
        "result": "PASS" if _matches_expected(case.expected, decision.risk_level) else "FAIL",
        "adapter_status": batch.status.value,
        "features": features,
        "diagnostics": diagnostics,
        "evidence_types": [item.evidence_type for item in batch.evidences],
        "matched_rule": decision.matched_rule,
        "risk_level": decision.risk_level,
        "event_action": decision.action,
    }


async def _run(cases: list[Case]) -> int:
    results = []
    for index, case in enumerate(cases, start=1):
        results.append(await _evaluate_case(case, index))
    passed = sum(item["result"] == "PASS" for item in results)
    report = {
        "schema_version": "gait-private-rule-validation/1.1",
        "adapter_version": ADAPTER_VERSION,
        "ruleset_version": load_ruleset().version,
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "overall_result": "PASS" if passed == len(results) else "FAIL",
        "cases": results,
        "contains_media_path": False,
        "contains_device_identifier": False,
        "contains_credentials": False,
        "contains_raw_landmarks": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["overall_result"] == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate gait rules against authorized private replay videos."
    )
    parser.add_argument("--case", action="append", type=_parse_case, required=True)
    args = parser.parse_args()
    return asyncio.run(_run(args.case))


if __name__ == "__main__":
    raise SystemExit(main())
