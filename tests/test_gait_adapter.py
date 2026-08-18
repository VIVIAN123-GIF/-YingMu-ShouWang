from __future__ import annotations

import asyncio
import json
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


def test_gait_adapter_registry_invocation(monkeypatch, tmp_path: Path):
    feature_path = tmp_path / "features.json"
    _write_features(feature_path)
    monkeypatch.setenv("YINGMU_GAIT_ADAPTER", "contracts.v1.gait_adapter:run")
    # Keep this single-module registry test independent of developer-local
    # trajectory/language adapter settings in .env.
    monkeypatch.delenv("YINGMU_TRAJECTORY_ADAPTER", raising=False)
    monkeypatch.delenv("YINGMU_LANGUAGE_ADAPTER", raising=False)
    registry = AdapterRegistry()
    registry.load_configured()

    batch = asyncio.run(registry.invoke(AlgorithmModule.GAIT, _job(feature_path)))

    assert batch.module == AlgorithmModule.GAIT
    assert batch.status == "SUCCESS"
    assert batch.error is None


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
