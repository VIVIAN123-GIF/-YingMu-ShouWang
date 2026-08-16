from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import uuid

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.database import Base
from backend.db.models import (
    AgentExplanationJob,
    AlarmProcessingTask,
    Asset,
    Evidence,
    InterventionResult,
    Observation,
    RiskEvent,
)
from backend.service import algorithm_task_service
from backend.service.algorithm_task_service import process_algorithm_task
from backend.api.exception_handlers import (
    service_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from backend.api.v1 import events as events_api
from backend.api.v1 import evidence as evidence_api
from backend.db.database import get_db
from backend.service.errors import ServiceError
from backend.service.agent_explanation_job_service import (
    enqueue_event_explanation,
    process_explanation_job,
)
from backend.service.agent_explanation_service import AgentExplanationService
from backend.service.feedback_aggregation_service import (
    aggregate_no_response,
    aggregate_persistent_instability,
)
from backend.service.recovery_scheduler_service import advance_one_due_event
from backend.service.risk_service import _context, evaluate
from backend.service.serialization import dumps
from contracts.v1.algorithm import AdapterBatch, AlgorithmModule


CN_TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 16, 10, 0, tzinfo=CN_TZ)


def observation_row(observation_id: str, resident_id: str, *, scene: str | None = None):
    return Observation(
        schema_version="1.0",
        observation_id=observation_id,
        resident_id=resident_id,
        timestamp=NOW,
        source="pose",
        feature_name="trunk_sway_angle_deg",
        feature_value=dumps(18.0),
        unit="degree",
        location="living_room",
        confidence=0.9,
        data_quality=0.9,
        source_mode="MOCK",
        asset_id="asset-test",
        simulated=True,
        extra_metadata=dumps({"scene_config_id": scene}) if scene else dumps({}),
        device_sn=None,
    )


def evidence_row(
    evidence_id: str,
    observation_id: str,
    resident_id: str,
    evidence_type: str,
    *,
    risk_domain: str = "FALL",
    timestamp: datetime = NOW,
):
    return Evidence(
        schema_version="1.0",
        evidence_id=evidence_id,
        observation_ids=dumps([observation_id]),
        resident_id=resident_id,
        timestamp=timestamp,
        risk_domain=risk_domain,
        evidence_type=evidence_type,
        severity=0.8,
        confidence=0.9,
        data_quality=0.9,
        baseline_value=5.0,
        current_value=18.0,
        baseline_deviation=2.6,
        time_scale="SHORT",
        location="living_room",
        explanation=f"evidence {evidence_type}",
        adapter_version="test-v1",
        source_mode="MOCK",
        simulated=True,
    )


def event_row(event_id: str, resident_id: str, *, status: str = "INTERVENING"):
    return RiskEvent(
        schema_version="1.0",
        event_id=event_id,
        resident_id=resident_id,
        created_at=NOW - timedelta(minutes=2),
        updated_at=NOW - timedelta(minutes=2),
        primary_domain="FALL",
        related_domains=dumps([]),
        risk_level="ORANGE",
        risk_score=0.82,
        evidence_ids=dumps([f"evi-{event_id}"]),
        evidence_summary=dumps([{
            "evidence_id": f"evi-{event_id}",
            "evidence_type": "trunk_sway",
            "explanation": "structured instability evidence",
        }]),
        time_horizon="IMMINENT",
        recommended_action="sit down and remain stable",
        intervention_policy="fall-orange-gentle-v1",
        status=status,
        ruleset_version="ruleset-v1.0",
        source_mode="MOCK",
        simulated=True,
        recovery_started_at=(NOW - timedelta(seconds=61)) if status == "OBSERVING" else None,
    )


def asset_row(asset_id: str, *, content_type: str = "image/jpeg"):
    return Asset(
        asset_id=asset_id,
        title="private test asset",
        source_mode="MOCK",
        simulated=True,
        stream_url=None,
        fallback_url=None,
        fallback_kind="private_storage",
        available=True,
        verification_status="VERIFIED_TEST",
        captured_at=NOW,
        notice="test only",
        device_ref="device-redacted-test",
        device_model="EZVIZ_C6C",
        camera_position_id="living-room-c6c-v1",
        authorization_status="AUTHORIZED",
        authorization_record_id="consent-test",
        retention_until=NOW + timedelta(days=1),
        content_sha256="a" * 64,
        content_type=content_type,
        byte_size=16,
        storage_key=f"objects/{asset_id}",
    )


def alarm_task_row(task_id: str, asset_id: str):
    return AlarmProcessingTask(
        task_id=task_id,
        alarm_msg_id=f"alarm-{task_id}",
        resident_id=f"resident-{task_id}",
        device_sn="device-private-test",
        status="ALGORITHM_PROCESSING",
        attempt_count=1,
        algorithm_attempt_count=1,
        capture_asset_id=asset_id,
        available_at=NOW.replace(tzinfo=None),
    )


class FakeRegistry:
    def __init__(self, adapters=None):
        self.adapters = adapters or {}

    def load_configured(self):
        return None

    def get(self, module):
        return self.adapters.get(module)

    async def invoke(self, module, job):
        return await self.adapters[module](job)


async def with_database(tmp_path, operation):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p0.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as db:
            return await operation(db)
    finally:
        await engine.dispose()


def test_internal_evidence_is_idempotent_and_escalates_before_low_quality(tmp_path):
    async def operation(db):
        resident_id = "resident-no-response"
        event = event_row("event-no-response", resident_id)
        obs = observation_row("obs-event-no-response", resident_id)
        original = evidence_row("evi-event-no-response", obs.observation_id, resident_id, "trunk_sway")
        intervention = InterventionResult(
            schema_version="1.0",
            result_id="result-no-response",
            event_id=event.event_id,
            started_at=NOW - timedelta(seconds=70),
            completed_at=NOW - timedelta(seconds=70),
            action_type="voice",
            tool_name="mock_voice",
            delivery_status="SUCCESS",
            resident_response=None,
            family_feedback=None,
            risk_after=None,
            resolved=False,
            resolution_reason="simulated delivery",
            operator="system",
            source_mode="MOCK",
            simulated=True,
        )
        db.add_all([obs, original, event, intervention])
        await db.commit()
        first = await aggregate_no_response(db, event, NOW)
        second = await aggregate_no_response(db, event, NOW + timedelta(seconds=5))
        result = await evaluate(db, resident_id, NOW)
        count = (await db.execute(select(func.count(Evidence.id)).where(
            Evidence.evidence_type == "no_response"
        ))).scalar_one()
        return first.evidence_id, second.evidence_id, result, count

    first_id, second_id, result, count = asyncio.run(with_database(tmp_path, operation))
    assert first_id == second_id
    assert count == 1
    assert result["matched_rule"] == "R-FALL-07"
    assert result["next_state"] == "RED"


def test_persistent_instability_uses_three_qualified_source_consistent_items(tmp_path):
    async def operation(db):
        resident_id = "resident-persistent"
        event = event_row("event-persistent", resident_id)
        rows = [event]
        for index in range(3):
            obs = observation_row(f"obs-persistent-{index}", resident_id)
            rows.extend([
                obs,
                evidence_row(
                    f"evi-persistent-{index}",
                    obs.observation_id,
                    resident_id,
                    "gait_instability" if index % 2 else "trunk_sway",
                    timestamp=NOW - timedelta(seconds=20 - index),
                ),
            ])
        db.add_all(rows)
        await db.commit()
        first = await aggregate_persistent_instability(db, event, NOW)
        second = await aggregate_persistent_instability(db, event, NOW)
        return first.evidence_id, second.evidence_id, len(first.observation_ids)

    first_id, second_id, encoded_length = asyncio.run(with_database(tmp_path, operation))
    assert first_id == second_id
    assert encoded_length > 2


def test_environment_context_requires_fall_and_records_scene_policy(tmp_path):
    async def operation(db):
        system_only = "resident-system-only"
        mixed = "resident-mixed"
        rows = []
        for resident in (system_only, mixed):
            obs = observation_row(f"obs-zone-{resident}", resident, scene="scene-living-room-v1")
            rows.extend([
                obs,
                evidence_row(
                    f"evi-zone-{resident}", obs.observation_id, resident,
                    "high_risk_zone_entry", risk_domain="SYSTEM",
                ),
            ])
        fall_obs = observation_row("obs-fall-mixed", mixed)
        rows.extend([fall_obs, evidence_row("evi-fall-mixed", fall_obs.observation_id, mixed, "trunk_sway")])
        db.add_all(rows)
        await db.commit()
        _, system_context, _ = await _context(db, system_only, NOW)
        _, mixed_context, _ = await _context(db, mixed, NOW)
        return system_context, mixed_context

    system_context, mixed_context = asyncio.run(with_database(tmp_path, operation))
    assert system_context["contributions"]["high_risk_zone"] == 0
    assert mixed_context["contributions"]["high_risk_zone"] == 0.25
    assert mixed_context["policy_version"] == "env-context-v1.0"
    assert mixed_context["environment_evidence_ids"] == ["evi-zone-resident-mixed"]
    assert mixed_context["scene_config_ids"] == ["scene-living-room-v1"]


def test_observing_event_resolves_only_when_scheduler_reaches_60_seconds(tmp_path):
    async def operation(db):
        resident_id = "resident-recovery"
        event = event_row("event-recovery", resident_id, status="OBSERVING")
        obs = observation_row("obs-event-recovery", resident_id)
        evidence = evidence_row("evi-event-recovery", obs.observation_id, resident_id, "posture_recovered")
        db.add_all([obs, evidence, event])
        await db.commit()
        result = await advance_one_due_event(db, now=NOW)
        await db.refresh(event)
        return result, event.status

    result, status = asyncio.run(with_database(tmp_path, operation))
    assert result["matched_rule"] == "R-FALL-05"
    assert status == "RESOLVED"


def test_agent_job_is_version_idempotent_and_persists_fallback(tmp_path):
    async def operation(db):
        resident_id = "resident-agent-job"
        event = event_row("event-agent-job", resident_id)
        obs = observation_row("obs-event-agent-job", resident_id)
        evidence = evidence_row("evi-event-agent-job", obs.observation_id, resident_id, "trunk_sway")
        db.add_all([obs, evidence, event])
        await db.commit()
        first, created = await enqueue_event_explanation(db, event.event_id)
        second, repeated_created = await enqueue_event_explanation(db, event.event_id)
        processed = await process_explanation_job(
            db, first, service=AgentExplanationService(provider=None)
        )
        return created, repeated_created, first.request_id, second.request_id, processed.status

    created, repeated_created, first_id, second_id, status = asyncio.run(
        with_database(tmp_path, operation)
    )
    assert created is True
    assert repeated_created is False
    assert first_id == second_id
    assert status == "FALLBACK"


def test_unregistered_algorithm_adapter_finishes_failed(monkeypatch, tmp_path):
    media = tmp_path / "capture.jpg"
    media.write_bytes(b"test-image")
    monkeypatch.setattr(algorithm_task_service, "resolve_private_asset_path", lambda _: media)

    async def operation(db):
        asset = asset_row("asset-missing-adapter")
        task = alarm_task_row("task-missing-adapter", asset.asset_id)
        db.add_all([asset, task])
        await db.commit()
        result = await process_algorithm_task(db, task, registry=FakeRegistry())
        return result.status, result.error_code

    status, error_code = asyncio.run(with_database(tmp_path, operation))
    assert status == "FAILED"
    assert error_code == "ADAPTER_NOT_REGISTERED"


def test_one_algorithm_failure_does_not_cancel_valid_module(monkeypatch, tmp_path):
    media = tmp_path / "capture.mp4"
    media.write_bytes(b"test-video")
    monkeypatch.setattr(algorithm_task_service, "resolve_private_asset_path", lambda _: media)

    async def gait(job):
        return AdapterBatch.model_validate({
            "schema_version": "adapter-batch/1.0",
            "job_id": job.job_id,
            "module": "GAIT",
            "adapter_version": "gait-test-v1",
            "status": "NO_EVIDENCE",
            "started_at": NOW,
            "completed_at": NOW,
            "observations": [{
                "schema_version": "1.0",
                "observation_id": "obs-partial-valid",
                "resident_id": job.resident_id,
                "timestamp": NOW,
                "source": "pose",
                "feature_name": "valid_frame_ratio",
                "feature_value": 0.9,
                "unit": "ratio",
                "location": "living_room",
                "confidence": 0.9,
                "data_quality": 0.9,
                "source_mode": job.source_mode,
                "asset_id": job.asset_id,
                "simulated": job.simulated,
                "metadata": {"model_version": "test-v1"},
            }],
            "evidences": [],
            "resident_response_candidate": None,
            "diagnostics": {},
            "error": None,
        })

    async def trajectory(_job):
        raise RuntimeError("isolated test failure")

    registry = FakeRegistry({
        AlgorithmModule.GAIT: gait,
        AlgorithmModule.TRAJECTORY: trajectory,
    })

    async def operation(db):
        asset = asset_row("asset-partial", content_type="video/mp4")
        task = alarm_task_row("task-partial", asset.asset_id)
        db.add_all([asset, task])
        await db.commit()
        result = await process_algorithm_task(db, task, registry=registry)
        persisted = (await db.execute(select(Observation).where(
            Observation.observation_id == "obs-partial-valid"
        ))).scalar_one_or_none()
        return result.status, result.error_code, persisted is not None

    status, error_code, observation_saved = asyncio.run(with_database(tmp_path, operation))
    assert status == "NO_EVIDENCE"
    assert error_code == "PARTIAL_ALGORITHM_FAILURE"
    assert observation_saved is True


def test_public_api_rejects_internal_evidence_and_controls_explanation_enqueue(tmp_path):
    resident_id = "resident-p0-api"
    event_id = "event-p0-api"

    database = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    factory = async_sessionmaker(database, expire_on_commit=False)

    async def seed():
        async with database.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as db:
            obs = observation_row("obs-event-p0-api", resident_id)
            evidence = evidence_row("evi-event-p0-api", obs.observation_id, resident_id, "trunk_sway")
            db.add_all([obs, evidence, event_row(event_id, resident_id)])
            await db.commit()

    async def override_db():
        async with factory() as db:
            yield db

    api = FastAPI()
    api.add_exception_handler(ServiceError, service_error_handler)
    api.add_exception_handler(RequestValidationError, validation_error_handler)
    api.add_exception_handler(Exception, unexpected_error_handler)

    @api.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = f"req-{uuid.uuid4().hex}"
        return await call_next(request)

    router = APIRouter(prefix="/api/v1")
    router.include_router(evidence_api.router)
    router.include_router(events_api.router)
    api.include_router(router)
    api.dependency_overrides[get_db] = override_db

    asyncio.run(seed())
    with TestClient(api) as client:
        forbidden = client.post("/api/v1/evidence", json={
            "schema_version": "1.0",
            "evidence_id": "evi-forged-no-response",
            "observation_ids": ["obs-event-p0-api"],
            "resident_id": resident_id,
            "timestamp": NOW.isoformat(),
            "risk_domain": "FALL",
            "evidence_type": "no_response",
            "severity": 1.0,
            "confidence": 1.0,
            "data_quality": 1.0,
            "baseline_value": 60.0,
            "current_value": 61.0,
            "baseline_deviation": 1.0,
            "time_scale": "SHORT",
            "location": "living_room",
            "explanation": "forged internal evidence",
            "adapter_version": "external",
            "source_mode": "MOCK",
            "simulated": True,
        })
        unauthorized = client.post(f"/api/v1/events/{event_id}/explanation")
        created = client.post(
            f"/api/v1/events/{event_id}/explanation",
            headers={"X-Control-Token": "test-control-token"},
        )
        repeated = client.post(
            f"/api/v1/events/{event_id}/explanation",
            headers={"X-Control-Token": "test-control-token"},
        )
        latest = client.get(f"/api/v1/events/{event_id}/explanation")
    asyncio.run(database.dispose())
    assert forbidden.status_code == 422
    assert forbidden.json()["error"]["code"] == "INTERNAL_EVIDENCE_FORBIDDEN"
    assert unauthorized.status_code == 403
    assert created.status_code == 201
    assert repeated.status_code == 200
    assert latest.status_code == 200
    assert latest.json()["status"] == "PENDING"
