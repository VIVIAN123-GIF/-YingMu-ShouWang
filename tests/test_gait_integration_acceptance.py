from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from backend.db.database import engine
from backend.main import app
from contracts.v1.algorithm import AdapterBatch, AlgorithmJob, AlgorithmModule, MediaType, validate_batch_for_job
from scripts.run_gait_integration_acceptance import _backend_checks, _submit_backend, run_acceptance


def _job(path: Path) -> AlgorithmJob:
    return AlgorithmJob(
        schema_version="algorithm-job/1.0",
        job_id="job-gait-acceptance-test",
        correlation_id="corr-gait-acceptance-test",
        resident_id="resident-acceptance-test",
        asset_id="asset-gait-acceptance-test",
        media_type=MediaType.VIDEO,
        media_locator=str(path),
        captured_at="2026-08-20T09:30:00+08:00",
        source_mode="RECORDED_REPLAY",
        simulated=True,
        location="living_room",
        camera_position_id="camera-position-test",
        scene_config_id="scene-config-test",
        requested_modules=[AlgorithmModule.GAIT],
        deadline_ms=120000,
    )


def test_contract_run_archives_pairable_job_and_media_hash(tmp_path: Path):
    feature_path = tmp_path / "features.json"
    feature_path.write_text(json.dumps({"features": {
        "rise_duration_s": 1.0,
        "trunk_sway_angle_deg": 14.0,
        "step_speed_norm_s": 0.6,
        "step_asymmetry_ratio": 0.4,
        "valid_frame_ratio": 0.95,
    }}), encoding="utf-8")
    output_dir = tmp_path / "evidence"
    job = _job(feature_path)

    report = asyncio.run(run_acceptance(media_path=feature_path, output_dir=output_dir, job=job))

    assert report["verdict"] == "CONTRACT_PASS"
    assert report["media"]["path_retained_in_report"] is False
    archived_job = AlgorithmJob.model_validate_json(
        (output_dir / "algorithm_job.redacted.json").read_text(encoding="utf-8")
    )
    batch = AdapterBatch.model_validate_json(
        (output_dir / "adapter_batch.json").read_text(encoding="utf-8")
    )
    validate_batch_for_job(batch, archived_job)
    assert archived_job.job_id == batch.job_id
    assert archived_job.resident_id == batch.observations[0].resident_id
    assert archived_job.asset_id == batch.observations[0].asset_id


def test_backend_checks_require_first_write_retry_event_and_trace(tmp_path: Path):
    feature_path = tmp_path / "features.json"
    feature_path.write_text(json.dumps({"features": {
        "rise_duration_s": 1.0,
        "trunk_sway_angle_deg": 14.0,
        "step_speed_norm_s": 0.6,
        "step_asymmetry_ratio": 0.4,
        "valid_frame_ratio": 0.95,
    }}), encoding="utf-8")
    job = _job(feature_path)
    output_dir = tmp_path / "batch"
    asyncio.run(run_acceptance(media_path=feature_path, output_dir=output_dir, job=job))
    batch = AdapterBatch.model_validate_json((output_dir / "adapter_batch.json").read_text(encoding="utf-8"))
    evidence_id = batch.evidences[0].evidence_id
    receipts = {
        "first_write": [{"status_code": 201}, {"status_code": 201}],
        "idempotent_retry": [{"status_code": 200}, {"status_code": 200}],
        "event_details": [{"status_code": 200, "body": {
            "event_id": "event-test",
            "evidence_ids": [evidence_id],
            "rule_traces": [{"matched_rule": "test"}],
        }}],
    }

    checks = _backend_checks(receipts, batch)

    assert all(item["passed"] for item in checks)


def test_backend_checks_reject_incomplete_evidence_chain(tmp_path: Path):
    feature_path = tmp_path / "features.json"
    feature_path.write_text(json.dumps({"features": {
        "rise_duration_s": 1.0,
        "valid_frame_ratio": 0.95,
    }}), encoding="utf-8")
    job = _job(feature_path)
    output_dir = tmp_path / "batch"
    asyncio.run(run_acceptance(media_path=feature_path, output_dir=output_dir, job=job))
    batch = AdapterBatch.model_validate_json((output_dir / "adapter_batch.json").read_text(encoding="utf-8"))
    receipts = {
        "first_write": [{"status_code": 201}],
        "idempotent_retry": [{"status_code": 200}],
        "event_details": [],
    }

    checks = _backend_checks(receipts, batch)

    assert not next(item for item in checks if item["name"] == "risk_event_returned")["passed"]
    assert not next(item for item in checks if item["name"] == "rule_trace_archived")["passed"]


def test_generated_batch_reaches_backend_event_and_rule_trace(tmp_path: Path):
    run_id = uuid.uuid4().hex[:10]
    feature_path = tmp_path / "features.json"
    feature_path.write_text(json.dumps({"features": {
        "rise_duration_s": 1.0,
        "trunk_sway_angle_deg": 16.0,
        "step_speed_norm_s": 0.6,
        "step_asymmetry_ratio": 0.4,
        "valid_frame_ratio": 0.95,
    }}), encoding="utf-8")
    job = _job(feature_path).model_copy(update={
        "job_id": f"job-gait-backend-{run_id}",
        "correlation_id": f"corr-gait-backend-{run_id}",
        "resident_id": f"resident-gait-backend-{run_id}",
        "asset_id": f"asset-gait-backend-{run_id}",
    })
    output_dir = tmp_path / "batch"
    asyncio.run(run_acceptance(media_path=feature_path, output_dir=output_dir, job=job))
    batch = AdapterBatch.model_validate_json((output_dir / "adapter_batch.json").read_text(encoding="utf-8"))
    asset = {
        "asset_id": job.asset_id,
        "title": "Redacted authorized test clip",
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "stream_url": None,
        "fallback_url": None,
        "fallback_kind": "LOCAL_AUTHORIZED_CLIP",
        "available": False,
        "verification_status": "VERIFIED",
        "captured_at": job.captured_at.isoformat(),
        "notice": "Test metadata only",
        "device_ref": f"device-ref-{run_id}",
        "device_model": "EZVIZ_C6C",
        "camera_position_id": job.camera_position_id,
        "authorization_status": "AUTHORIZED",
        "authorization_record_id": f"auth-{run_id}",
        "retention_until": "2026-09-30T23:59:59+08:00",
        "content_sha256": "a" * 64,
        "content_type": "video/mp4",
        "byte_size": 1024,
    }

    try:
        with TestClient(app) as client:
            def requester(method: str, url: str, payload: dict | None, timeout: float):
                del timeout
                response = client.request(method, urlparse(url).path, json=payload)
                return {
                    "method": method,
                    "url": url,
                    "status_code": response.status_code,
                    "body": response.json(),
                }

            receipts = _submit_backend("http://testserver", asset, batch, 10.0, requester)
    finally:
        asyncio.run(engine.dispose())

    checks = _backend_checks(receipts, batch)
    assert all(item["passed"] for item in checks)
