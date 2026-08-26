from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

from contracts.v1.algorithm import (
    AdapterBatch,
    AlgorithmJob,
    AlgorithmModule,
    MediaType,
    validate_batch_for_job,
)
from contracts.v1.gait_adapter import FROZEN_FEATURES, run
from contracts.v1.gait_video import _derive_gait_features
from backend.service.adapter_registry import AdapterRegistry


def _write_features(path: Path, valid_frame_ratio: float = 0.91) -> None:
    path.write_text(
        json.dumps(
            {
                "features": {
                    "rise_duration_s": 1.24,
                    "trunk_sway_angle_deg": 16.8,
                    "step_speed_norm_s": 0.88,
                    "step_asymmetry_ratio": 0.42,
                    "stable_posture_duration": 18.0,
                    "stable_trunk_angle_deg": 5.6,
                    "valid_frame_ratio": valid_frame_ratio,
                }
            }
        ),
        encoding="utf-8",
    )


def _write_v12_features(path: Path, **changes) -> None:
    features = {
        "assessment_status": "VALID",
        "assessment_reason_code": "ASSESSABLE_POST_RISE_WINDOW",
        "sit_to_stand_transition_confirmed": True,
        "rise_duration_s": 2.2,
        "trunk_sway_angle_deg": 16.8,
        "post_rise_sway_reversal_count": 3,
        "post_rise_pelvis_lateral_excursion_norm": 0.48,
        "post_rise_support_width_change_norm": 0.12,
        "post_rise_compensatory_step_count": 0,
        "post_rise_feet_visibility": 0.92,
        "post_rise_tracking_ratio": 0.91,
        "post_rise_orientation_quality": 0.88,
        "valid_frame_ratio": 0.91,
    }
    features.update(changes)
    path.write_text(json.dumps({"features": features}), encoding="utf-8")


def _job(path: Path) -> AlgorithmJob:
    return AlgorithmJob(
        schema_version="algorithm-job/1.0",
        job_id="job-gait-test-001",
        correlation_id="corr-gait-test-001",
        resident_id="resident-test-001",
        asset_id="asset-gait-test-001",
        media_type=MediaType.VIDEO,
        media_locator=str(path),
        captured_at="2026-08-16T09:30:00+08:00",
        source_mode="RECORDED_REPLAY",
        simulated=True,
        location="bedroom",
        camera_position_id="camera-position-test-001",
        scene_config_id="scene-config-test-001",
        requested_modules=[AlgorithmModule.GAIT],
        deadline_ms=8000,
    )


def test_gait_adapter_batch_contract_and_references(tmp_path: Path):
    feature_path = tmp_path / "features.json"
    _write_features(feature_path)

    batch = asyncio.run(run(_job(feature_path)))
    validate_batch_for_job(AdapterBatch.model_validate(batch.model_dump()), _job(feature_path))

    assert batch.schema_version == "adapter-batch/1.0"
    assert batch.module == "GAIT"
    assert batch.status == "SUCCESS"
    assert all(item.feature_name in FROZEN_FEATURES for item in batch.observations)

    observation_ids = {item.observation_id for item in batch.observations}
    assert observation_ids
    assert batch.evidences
    for item in batch.observations:
        assert item.resident_id == "resident-test-001"
        assert item.source_mode.value == "RECORDED_REPLAY"
        assert item.simulated is True
    for item in batch.evidences:
        assert item.resident_id == "resident-test-001"
        assert "asset_id" not in item.model_dump()
        assert item.source_mode.value == "RECORDED_REPLAY"
        assert item.simulated is True
        assert set(item.observation_ids).issubset(observation_ids)
        assert item.evidence_type in {
            "rapid_rise",
            "slow_rise",
            "trunk_sway",
            "gait_instability",
            "relative_speed_change",
            "posture_recovered",
            "tracking_lost",
        }

    recovered = next(item for item in batch.evidences if item.evidence_type == "posture_recovered")
    recovered_features = {
        item.feature_name
        for item in batch.observations
        if item.observation_id in recovered.observation_ids
    }
    assert recovered_features == {"stable_posture_duration", "stable_trunk_angle_deg"}


def test_gait_adapter_ids_are_stable_for_same_input(tmp_path: Path):
    feature_path = tmp_path / "features.json"
    _write_features(feature_path)
    job = _job(feature_path)

    first = asyncio.run(run(job))
    second = asyncio.run(run(job))

    assert [item.observation_id for item in first.observations] == [item.observation_id for item in second.observations]
    assert [item.evidence_id for item in first.evidences] == [item.evidence_id for item in second.evidences]


def test_gait_adapter_low_quality(tmp_path: Path):
    feature_path = tmp_path / "features.json"
    _write_features(feature_path, valid_frame_ratio=0.41)

    batch = asyncio.run(run(_job(feature_path)))

    assert batch.status == "LOW_QUALITY"
    assert any(item.evidence_type == "tracking_lost" for item in batch.evidences)
    assert batch.error is None


def test_gait_adapter_invalid_input_is_contract_failed(tmp_path: Path):
    job = _job(tmp_path / "missing.json")

    batch = asyncio.run(run(job))

    assert batch.status == "FAILED"
    assert batch.error is not None
    assert batch.error.code == "FEATURE_INPUT_INVALID"
    assert batch.observations == []
    assert batch.evidences == []


def test_gait_adapter_image_does_not_emit_temporal_evidence(tmp_path: Path):
    feature_path = tmp_path / "features.json"
    _write_features(feature_path)
    job = _job(feature_path).model_copy(update={"media_type": MediaType.IMAGE})

    batch = asyncio.run(run(job))

    assert batch.status == "NO_EVIDENCE"
    assert batch.observations
    assert batch.evidences == []


def test_gait_adapter_real_image_is_no_evidence(tmp_path: Path):
    image_path = tmp_path / "capture.jpg"
    image_path.write_bytes(b"not-used-by-image-quality-path")
    job = _job(image_path).model_copy(update={"media_type": MediaType.IMAGE})

    batch = asyncio.run(run(job))

    assert batch.status == "NO_EVIDENCE"
    assert batch.error is None
    assert batch.evidences == []
    assert [item.feature_name for item in batch.observations] == ["valid_frame_ratio"]


def test_gait_adapter_registry_invocation(monkeypatch, tmp_path: Path):
    feature_path = tmp_path / "features.json"
    _write_features(feature_path)
    monkeypatch.setenv("YINGMU_GAIT_ADAPTER", "contracts.v1.gait_adapter:run")
    # An unrelated configured adapter must not block a GAIT-only task.
    monkeypatch.setenv("YINGMU_LANGUAGE_ADAPTER", "missing.language_adapter:run")
    registry = AdapterRegistry()
    registry.load_configured([AlgorithmModule.GAIT])

    batch = asyncio.run(registry.invoke(AlgorithmModule.GAIT, _job(feature_path)))

    assert batch.module == AlgorithmModule.GAIT
    assert batch.status == "SUCCESS"
    assert batch.error is None
    assert registry.get(AlgorithmModule.LANGUAGE) is None


def test_gait_adapter_extracts_features_from_mp4(monkeypatch, tmp_path: Path):
    video_path = tmp_path / "authorized-replay.mp4"
    video_path.write_bytes(b"test-video-placeholder")

    def fake_extract(path: Path):
        assert path == video_path
        return (
            {
                "rise_duration_s": 1.2,
                "trunk_sway_angle_deg": 14.0,
                "step_speed_norm_s": 0.8,
                "step_asymmetry_ratio": 0.4,
                "valid_frame_ratio": 0.9,
            },
            {
                "feature_source_type": "video",
                "frames_processed": 120,
                "pose_frames": 108,
            },
        )

    monkeypatch.setattr("contracts.v1.gait_adapter.extract_gait_features", fake_extract)
    batch = asyncio.run(run(_job(video_path)))

    assert batch.status == "SUCCESS"
    assert batch.diagnostics["feature_source_type"] == "video"
    assert batch.diagnostics["frames_processed"] == 120
    assert {item.feature_name for item in batch.observations} == {
        "rise_duration_s",
        "trunk_sway_angle_deg",
        "step_speed_norm_s",
        "step_asymmetry_ratio",
        "valid_frame_ratio",
    }


def test_video_pose_rows_are_converted_to_frozen_features():
    rows = [
        {
            "timestamp_ms": float(index * 500),
            "pelvis_x": 0.45 + index * 0.01,
            "pelvis_y": 0.70 - index * 0.02,
            "trunk_angle_deg": float(index * 3),
            "left_stride_extent": 0.12,
            "right_stride_extent": 0.08,
            "support_distance": 0.20,
            "core_visibility_mean": 0.92,
        }
        for index in range(8)
    ]

    features, diagnostics = _derive_gait_features(
        rows, total_frames=10, fps=2.0, duration_s=5.0,
    )

    assert set(features).issubset(FROZEN_FEATURES)
    assert features["valid_frame_ratio"] == 0.8
    assert features["step_asymmetry_ratio"] > 0
    assert features["support_distance_norm"] == 0.2
    assert features["turn_angular_velocity_deg_s"] > 0
    assert diagnostics["feature_source_type"] == "video"


def test_gait_adapter_no_evidence(tmp_path: Path):
    feature_path = tmp_path / "features.json"
    feature_path.write_text(
        json.dumps(
            {
                "features": {
                    "rise_duration_s": 2.2,
                    "trunk_sway_angle_deg": 4.0,
                    "step_speed_norm_s": 1.0,
                    "step_asymmetry_ratio": 0.08,
                    "valid_frame_ratio": 0.95,
                }
            }
        ),
        encoding="utf-8",
    )

    batch = asyncio.run(run(_job(feature_path)))

    assert batch.status == "NO_EVIDENCE"
    assert batch.observations
    assert batch.evidences == []
    assert batch.error is None


def test_v12_adapter_emits_transition_bound_independent_signal_families(tmp_path: Path):
    feature_path = tmp_path / "v12-features.json"
    _write_v12_features(feature_path)

    batch = asyncio.run(run(_job(feature_path)))

    by_type = {item.evidence_type: item for item in batch.evidences}
    assert batch.status == "SUCCESS"
    assert {"sit_to_stand_transition", "trunk_sway", "post_rise_lateral_drift"}.issubset(by_type)
    transition_observation_id = by_type["sit_to_stand_transition"].observation_ids[0]
    assert transition_observation_id in by_type["trunk_sway"].observation_ids
    assert transition_observation_id in by_type["post_rise_lateral_drift"].observation_ids


def test_v12_adapter_no_transition_does_not_emit_post_rise_risk(tmp_path: Path):
    feature_path = tmp_path / "no-transition.json"
    _write_v12_features(
        feature_path,
        assessment_status="NO_TRANSITION",
        assessment_reason_code="NO_SIT_TO_STAND_TRANSITION",
        sit_to_stand_transition_confirmed=False,
    )

    batch = asyncio.run(run(_job(feature_path)))

    assert batch.status == "NO_EVIDENCE"
    assert batch.evidences == []


def test_v12_adapter_indeterminate_returns_only_review_evidence(tmp_path: Path):
    feature_path = tmp_path / "indeterminate.json"
    _write_v12_features(
        feature_path,
        assessment_status="INDETERMINATE",
        assessment_reason_code="CAMERA_ORIENTATION_UNSUITABLE",
        post_rise_orientation_quality=0.2,
    )

    batch = asyncio.run(run(_job(feature_path)))

    assert batch.status == "LOW_QUALITY"
    assert [item.evidence_type for item in batch.evidences] == ["assessment_indeterminate"]


def _video_rows(
    *,
    duration_s: float = 8.0,
    rise_start_s: float | None = 1.0,
    angle_at=None,
) -> list[dict[str, float]]:
    rows = []
    for index in range(int(duration_s * 4) + 1):
        timestamp_s = index / 4
        if rise_start_s is None:
            pelvis_y = 0.70
        else:
            rise_progress = min(max(timestamp_s - rise_start_s, 0.0), 1.0)
            pelvis_y = 0.70 - 0.12 * rise_progress
        angle = float(angle_at(timestamp_s) if angle_at else 0.0)
        rows.append(
            {
                "timestamp_ms": timestamp_s * 1000,
                "pelvis_x": 0.50,
                "pelvis_y": pelvis_y,
                "trunk_angle_deg": angle,
                "left_stride_extent": 0.10,
                "right_stride_extent": 0.10,
                "support_distance": 0.20,
                "core_visibility_mean": 0.95,
                "body_scale": 0.20,
                "orientation_quality": 1.0,
                "feet_visibility_mean": 0.95,
                "left_ankle_x": 0.45,
                "left_ankle_y": 0.85,
                "right_ankle_x": 0.55,
                "right_ankle_y": 0.85,
            }
        )
    return rows


def test_post_rise_sway_uses_robust_signed_amplitude_not_absolute_tilt():
    rows = _video_rows(angle_at=lambda _timestamp: 20.0)

    features, diagnostics = _derive_gait_features(
        rows, total_frames=len(rows), fps=4.0, duration_s=8.0
    )

    assert features["trunk_sway_angle_deg"] == 0
    assert diagnostics["trunk_sway_window_type"] == "POST_RISE"
    assert diagnostics["rise_window_end_s"] is not None


def test_post_rise_left_right_motion_produces_sway_amplitude():
    rows = _video_rows(
        angle_at=lambda timestamp: (
            12.0 * math.sin((timestamp - 2.0) * math.pi)
            if timestamp >= 2.0
            else 0.0
        )
    )

    features, diagnostics = _derive_gait_features(
        rows, total_frames=len(rows), fps=4.0, duration_s=8.0
    )

    assert features["trunk_sway_angle_deg"] >= 20
    assert diagnostics["trunk_sway_p5_deg"] < 0
    assert diagnostics["trunk_sway_p95_deg"] > 0


def test_pre_rise_motion_does_not_pollute_post_rise_sway():
    rows = _video_rows(
        rise_start_s=2.0,
        angle_at=lambda timestamp: 18.0 * math.sin(timestamp * math.pi) if timestamp < 2.0 else 2.0,
    )

    features, diagnostics = _derive_gait_features(
        rows, total_frames=len(rows), fps=4.0, duration_s=8.0
    )

    assert features["trunk_sway_angle_deg"] == 0
    assert diagnostics["trunk_sway_window_type"] == "POST_RISE"


def test_single_frame_sway_outlier_does_not_raise_robust_amplitude():
    rows = _video_rows(angle_at=lambda timestamp: 80.0 if timestamp == 4.0 else 0.0)

    features, _diagnostics = _derive_gait_features(
        rows, total_frames=len(rows), fps=4.0, duration_s=8.0
    )

    assert features["trunk_sway_angle_deg"] == 0


def test_incomplete_post_rise_window_does_not_fabricate_sway():
    rows = _video_rows(duration_s=4.0, rise_start_s=1.0, angle_at=lambda timestamp: timestamp * 4)

    features, diagnostics = _derive_gait_features(
        rows, total_frames=len(rows), fps=4.0, duration_s=4.0
    )

    assert "trunk_sway_angle_deg" not in features
    assert diagnostics["trunk_sway_window_type"] == "POST_RISE_WINDOW_INSUFFICIENT"
    assert diagnostics["trunk_sway_failure_reason"] == "POST_RISE_WINDOW_INSUFFICIENT"


def test_no_rise_uses_full_clip_fallback_for_negative_calibration_only():
    rows = _video_rows(rise_start_s=None, angle_at=lambda timestamp: 4.0 * math.sin(timestamp))

    features, diagnostics = _derive_gait_features(
        rows, total_frames=len(rows), fps=4.0, duration_s=8.0
    )

    assert "rise_duration_s" not in features
    assert features["trunk_sway_angle_deg"] > 0
    assert diagnostics["trunk_sway_window_type"] == "FULL_CLIP_FALLBACK"
    assert features["assessment_status"] == "NO_TRANSITION"


def test_post_rise_lateral_drift_support_change_and_compensatory_step_are_measured():
    rows = _video_rows()
    for row in rows:
        timestamp = row["timestamp_ms"] / 1000.0
        if 2.0 <= timestamp <= 6.5:
            phase = int((timestamp - 2.0) * 4) % 4
            row["pelvis_x"] = 0.50 + (0.24 if phase >= 2 else 0.0)
            row["support_distance"] = 0.29 if phase >= 2 else 0.20
            row["left_ankle_x"] = 0.55 if phase >= 2 else 0.45

    features, _ = _derive_gait_features(
        rows, total_frames=len(rows), fps=4.0, duration_s=8.0
    )

    assert features["assessment_status"] == "VALID"
    assert features["post_rise_pelvis_lateral_excursion_norm"] >= 0.45
    assert features["post_rise_support_width_change_norm"] >= 0.4
    assert features["post_rise_compensatory_step_count"] >= 1


def test_side_view_and_turning_are_indeterminate_instead_of_green():
    side_rows = _video_rows()
    for row in side_rows:
        row["orientation_quality"] = 0.2
    side_features, _ = _derive_gait_features(
        side_rows, total_frames=len(side_rows), fps=4.0, duration_s=8.0
    )
    assert side_features["assessment_status"] == "INDETERMINATE"
    assert side_features["assessment_reason_code"] == "CAMERA_ORIENTATION_UNSUITABLE"

    turning_rows = _video_rows()
    for index, row in enumerate(turning_rows):
        if row["timestamp_ms"] >= 1750:
            row["orientation_quality"] = 0.3 if index % 2 else 0.9
    turning_features, _ = _derive_gait_features(
        turning_rows, total_frames=len(turning_rows), fps=4.0, duration_s=8.0
    )
    assert turning_features["assessment_status"] == "INDETERMINATE"
    assert turning_features["assessment_reason_code"] == "TURNING_DURING_ASSESSMENT"


def test_bending_recovery_without_knee_extension_is_not_confirmed_as_sit_to_stand():
    rows = _video_rows(angle_at=lambda timestamp: 35.0 if 1.0 <= timestamp <= 2.0 else 0.0)
    for row in rows:
        row["left_knee_angle_deg"] = 165.0
        row["right_knee_angle_deg"] = 165.0

    features, diagnostics = _derive_gait_features(
        rows, total_frames=len(rows), fps=4.0, duration_s=8.0
    )

    assert features["sit_to_stand_transition_confirmed"] is False
    assert features["assessment_status"] == "INDETERMINATE"
    assert diagnostics["assessment_reason_code"] == "KNEE_EXTENSION_NOT_CONFIRMED"


def test_sustained_post_rise_locomotion_is_indeterminate_not_lateral_instability():
    rows = _video_rows()
    for row in rows:
        timestamp = row["timestamp_ms"] / 1000.0
        if timestamp >= 1.75:
            offset = 0.045 * (timestamp - 1.75)
            row["pelvis_x"] = 0.50 + offset
            row["left_ankle_x"] = 0.45 + offset
            row["right_ankle_x"] = 0.55 + offset

    features, _ = _derive_gait_features(
        rows, total_frames=len(rows), fps=4.0, duration_s=8.0
    )

    assert features["post_rise_locomotion_detected"] == 1.0
    assert features["assessment_status"] == "INDETERMINATE"
    assert features["assessment_reason_code"] == "LOCOMOTION_DURING_ASSESSMENT"
