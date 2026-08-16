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
    registry = AdapterRegistry()
    registry.load_configured()

    batch = asyncio.run(registry.invoke(AlgorithmModule.GAIT, _job(feature_path)))

    assert batch.module == AlgorithmModule.GAIT
    assert batch.status == "SUCCESS"
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
