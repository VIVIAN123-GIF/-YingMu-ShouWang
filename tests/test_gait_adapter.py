from __future__ import annotations

import asyncio
import json
from pathlib import Path

from contracts.v1.gait_adapter import AdapterBatch, AlgorithmJob, FROZEN_FEATURES, run


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
        job_id="job-gait-test-001",
        resident_id="resident-test-001",
        asset_id="asset-gait-test-001",
        media_type="gait_feature_json",
        media_locator=str(path),
        captured_at="2026-08-16T09:30:00+08:00",
        source_mode="RECORDED_REPLAY",
        simulated=True,
        location="bedroom",
        camera_position_id="camera-position-test-001",
        scene_config_id="scene-config-test-001",
    )


def test_gait_adapter_batch_contract_and_references(tmp_path: Path):
    feature_path = tmp_path / "features.json"
    _write_features(feature_path)

    batch = asyncio.run(run(_job(feature_path)))
    AdapterBatch.model_validate(batch.model_dump())

    assert batch.schema_version == "adapter-batch/1.0"
    assert batch.module == "GAIT"
    assert batch.status == "SUCCESS"
    assert all(item.feature_name in FROZEN_FEATURES for item in batch.observations)

    observation_ids = {item.observation_id for item in batch.observations}
    assert observation_ids
    assert batch.evidences
    for item in batch.observations:
        assert item.resident_id == "resident-test-001"
        assert item.asset_id == "asset-gait-test-001"
        assert item.source_mode.value == "RECORDED_REPLAY"
        assert item.simulated is True
    for item in batch.evidences:
        assert item.resident_id == "resident-test-001"
        assert item.asset_id == "asset-gait-test-001"
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


def test_gait_adapter_live_video_contract_does_not_expose_paths(tmp_path: Path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake-video-bytes")
    model_path = tmp_path / "mediapipe_pose.tflite"
    model_path.write_bytes(b"model")

    job = AlgorithmJob(
        job_id="job-gait-live-001",
        resident_id="resident-live-001",
        asset_id="asset-live-001",
        media_type="video",
        media_locator=str(video_path),
        model_path=str(model_path),
        captured_at="2026-08-16T09:30:00+08:00",
        source_mode="LIVE_DEVICE",
        simulated=False,
        location="bedroom",
    )

    batch = asyncio.run(run(job))

    assert batch.job_id == job.job_id
    assert batch.observations
    assert batch.evidences or batch.status in {"NO_EVIDENCE", "LOW_QUALITY", "SUCCESS"}
    assert all(item.resident_id == job.resident_id for item in batch.observations)
    assert all(item.source_mode.value == "LIVE_DEVICE" for item in batch.observations)
    assert all(item.simulated is False for item in batch.observations)
    assert all(item.resident_id == job.resident_id for item in batch.evidences)
    for evidence in batch.evidences:
        assert evidence.observation_ids
        assert all(any(obs.observation_id == obs_id for obs in batch.observations) for obs_id in evidence.observation_ids)
    payload = batch.model_dump_json()
    assert str(video_path) not in payload
    assert str(model_path) not in payload
    assert "media_locator" not in payload


def test_gait_adapter_missing_model_reports_failed(tmp_path: Path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake-video-bytes")

    job = AlgorithmJob(
        job_id="job-gait-failed-001",
        resident_id="resident-live-002",
        asset_id="asset-live-002",
        media_type="video",
        media_locator=str(video_path),
        model_path=str(tmp_path / "missing_mediapipe.tflite"),
        captured_at="2026-08-16T09:30:00+08:00",
        source_mode="LIVE_DEVICE",
        simulated=False,
    )

    batch = asyncio.run(run(job))

    assert batch.status == "FAILED"
    assert batch.error is not None
    assert batch.observations == []
    assert batch.evidences == []
