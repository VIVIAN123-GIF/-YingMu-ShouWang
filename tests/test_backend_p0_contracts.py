from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from contracts.v1.algorithm import (
    AdapterBatch,
    AlgorithmJob,
    validate_batch_for_job,
)


NOW = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)


def job(**updates) -> AlgorithmJob:
    payload = {
        "schema_version": "algorithm-job/1.0",
        "job_id": "job-001",
        "correlation_id": "alarm-task-001",
        "resident_id": "resident-001",
        "asset_id": "asset-001",
        "media_type": "VIDEO",
        "media_locator": "C:/private/authorized.mp4",
        "captured_at": NOW,
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "location": "living_room",
        "camera_position_id": "living-room-c6c-v1",
        "scene_config_id": "scene-living-room-v1",
        "requested_modules": ["GAIT"],
        "deadline_ms": 8000,
    }
    payload.update(updates)
    return AlgorithmJob.model_validate(payload)


def observation(**updates) -> dict:
    payload = {
        "schema_version": "1.0",
        "observation_id": "obs-001",
        "resident_id": "resident-001",
        "timestamp": NOW,
        "source": "pose",
        "feature_name": "valid_frame_ratio",
        "feature_value": 0.91,
        "unit": "ratio",
        "location": "living_room",
        "confidence": 0.92,
        "data_quality": 0.91,
        "source_mode": "RECORDED_REPLAY",
        "asset_id": "asset-001",
        "simulated": True,
        "metadata": {"model_version": "test-v1"},
    }
    payload.update(updates)
    return payload


def evidence(evidence_type: str = "trunk_sway", **updates) -> dict:
    payload = {
        "schema_version": "1.0",
        "evidence_id": "evi-001",
        "observation_ids": ["obs-001"],
        "resident_id": "resident-001",
        "timestamp": NOW,
        "risk_domain": "FALL",
        "evidence_type": evidence_type,
        "severity": 0.8,
        "confidence": 0.9,
        "data_quality": 0.9,
        "baseline_value": 5.0,
        "current_value": 18.0,
        "baseline_deviation": 2.6,
        "time_scale": "SHORT",
        "location": "living_room",
        "explanation": "structured test evidence",
        "adapter_version": "test-v1",
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
    }
    payload.update(updates)
    return payload


def batch(**updates) -> AdapterBatch:
    payload = {
        "schema_version": "adapter-batch/1.0",
        "job_id": "job-001",
        "module": "GAIT",
        "adapter_version": "gait-test-v1",
        "status": "SUCCESS",
        "started_at": NOW,
        "completed_at": NOW,
        "observations": [observation()],
        "evidences": [],
        "resident_response_candidate": None,
        "diagnostics": {"elapsed_ms": 1},
        "error": None,
    }
    payload.update(updates)
    return AdapterBatch.model_validate(payload)


def test_algorithm_contract_requires_timezone_and_complete_failure_error():
    with pytest.raises(ValidationError, match="timezone"):
        job(captured_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError, match="require error"):
        batch(status="FAILED", observations=[], error=None)
    with pytest.raises(ValidationError, match="credentials"):
        job(media_locator="https://internal.invalid/media?accessToken=secret")


def test_no_evidence_and_low_quality_require_quality_observation():
    with pytest.raises(ValidationError, match="NO_EVIDENCE"):
        batch(status="NO_EVIDENCE", observations=[])
    with pytest.raises(ValidationError, match="LOW_QUALITY"):
        batch(status="LOW_QUALITY", observations=[])


def test_image_job_rejects_temporal_evidence():
    image_job = job(media_type="IMAGE")
    temporal_batch = batch(evidences=[evidence()])
    with pytest.raises(ValueError, match="IMAGE jobs"):
        validate_batch_for_job(temporal_batch, image_job)


def test_batch_outputs_must_inherit_job_provenance_and_reference_local_observations():
    with pytest.raises(ValueError, match="provenance"):
        validate_batch_for_job(batch(observations=[observation(asset_id="other")]), job())
    with pytest.raises(ValueError, match="same AdapterBatch"):
        validate_batch_for_job(
            batch(evidences=[evidence(observation_ids=["obs-other"])]),
            job(),
        )


def test_only_language_can_report_resident_response():
    with pytest.raises(ValidationError, match="language-only"):
        batch(resident_response_candidate={
            "intent": "STABLE",
            "confidence": 0.9,
            "transcript_observation_id": "obs-001",
        })
