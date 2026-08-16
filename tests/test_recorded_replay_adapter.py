from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "deliverables" / "zy" / "pose-demo" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import recorded_replay_adapter as adapter


def record(take_id: str = "take-golden-01") -> dict:
    return {
        "take_id": take_id,
        "asset_id": f"asset-{take_id}",
        "resident_id": "resident-sim-001",
        "device_ref": "device-ref-c6c-001",
        "camera_position_id": "camera-position-001",
        "captured_at": "2026-08-02T14:00:00+08:00",
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "authorization_status": "AUTHORIZED",
        "authorization_record_id": "auth-ref-001",
        "retention_until": "2026-08-31T23:59:59+08:00",
        "observation_60s_completed": False,
    }


def analysis(*, stable_seconds: float = 14.9, rapid_quality: float = 0.8, sway_quality: float = 0.75) -> dict:
    return {
        "candidates": {
            "rapid_rise": {
                "detected": True, "start_ms": 10000, "end_ms": 10800,
                "duration_s": 0.8, "displacement": 0.12, "speed": 0.15,
                "data_quality": rapid_quality,
            },
            "trunk_sway": {
                "detected": True, "timestamp_ms": 15000, "amplitude_deg": 18.0,
                "absolute_angle_deg": 16.0, "reference_angle_deg": 2.0,
                "data_quality": sway_quality,
            },
            "posture_recovered": {
                "detected": True, "start_ms": 20000, "end_ms": 20000 + stable_seconds * 1000,
                "duration_s": stable_seconds, "max_angle_deg": 3.613,
                "data_quality": 0.9, "frame_count": stable_seconds * 15,
            },
        }
    }


def frame(timestamp_ms: int, angle: float, quality: float = 0.9) -> dict:
    return {
        "timestamp_ms": timestamp_ms,
        "trunk_angle_deg_smooth": angle,
        "core_visibility_mean": quality,
    }


def test_clip_offsets_and_timezone_are_preserved():
    assert adapter.parse_offset("00:14.500") == 14.5
    assert adapter.iso_at("2026-08-02T14:00:00+08:00", 14.5) == "2026-08-02T14:00:14.500+08:00"
    with pytest.raises(ValueError, match="timezone"):
        adapter.iso_at("2026-08-02T14:00:00", 1)


def test_stability_is_longest_continuous_quality_qualified_interval():
    rows = [
        frame(0, 3), frame(1000, 4), frame(2000, 9),
        frame(3000, 3), frame(4000, 4), frame(5000, 5),
        frame(6000, 3, 0.69), frame(7000, 2),
    ]
    result = adapter.stable_tail(rows, after_ms=2000)
    assert result["start_ms"] == 3000
    assert result["end_ms"] == 5000
    assert result["duration_s"] == 2.0
    assert result["frame_count"] == 3


def test_rapid_only_policy_suppresses_sway_and_recovery_candidates():
    package = adapter.build_package(record("take-rapid-only-01"), analysis())
    assert [item["evidence_type"] for item in package["evidence"]] == ["rapid_rise"]
    assert package["eligible_for_real_resolved_claim"] is False


def test_recovery_duration_and_angle_are_separate_observations():
    package = adapter.build_package(record(), analysis(stable_seconds=14.9))
    recovery = next(item for item in package["evidence"] if item["evidence_type"] == "posture_recovered")
    observations = {item["feature_name"]: item for item in package["observations"]}
    assert recovery["current_value"] == 14.9
    assert recovery["baseline_value"] == 15.0
    assert observations["stable_posture_duration"]["feature_value"] == 14.9
    assert observations["stable_trunk_angle_deg"]["feature_value"] == 3.613
    assert set(recovery["observation_ids"]) == {
        observations["stable_posture_duration"]["observation_id"],
        observations["stable_trunk_angle_deg"]["observation_id"],
    }
    assert package["partial_acceptance_stage"] == "EVIDENCE_ONLY"


def test_high_confidence_and_15_seconds_only_reaches_observing_stage():
    package = adapter.build_package(record(), analysis(stable_seconds=15.0, rapid_quality=0.8))
    assert package["partial_acceptance_stage"] == "OBSERVING_ONLY"
    assert package["eligible_for_real_resolved_claim"] is False
    assert package["acceptance_status"] == "PENDING_ASSET"


def test_quality_below_point_seven_is_not_emitted_as_evidence():
    package = adapter.build_package(record(), analysis(rapid_quality=0.69, sway_quality=0.69))
    assert {item["evidence_type"] for item in package["evidence"]} == {"posture_recovered"}
    assert {item["evidence_type"] for item in package["rejected_candidates"]} == {"rapid_rise", "trunk_sway"}
    assert package["partial_acceptance_stage"] == "QUALITY_BLOCKED"


def test_under_15_policy_emits_real_subthreshold_recovery():
    package = adapter.build_package(record("take-under15-01"), analysis(stable_seconds=7.534))
    assert [item["evidence_type"] for item in package["evidence"]] == ["trunk_sway", "posture_recovered"]
    recovery = package["evidence"][-1]
    assert recovery["current_value"] == 7.534
    assert recovery["current_value"] < recovery["baseline_value"]
