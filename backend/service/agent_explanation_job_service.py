"""Persistence and execution boundary for versioned agent explanations."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import EZVIZ_LIVE_PLAYBACK_VERIFIED, EZVIZ_VOICE_VERIFIED
from backend.db.models import AgentExplanationJob, Evidence, ForewarningSnapshot, InterventionResult, RiskEvent
from backend.service.agent_explanation_service import (
    AgentExplanationService,
    build_default_agent_explanation_service,
)
from backend.service.errors import ServiceError
from backend.service.resident_response import canonical_resident_response
from backend.service.serialization import aware, dumps, loads, utc_naive_to_cn
from contracts.v1.agent import (
    AgentBaselineStatus,
    AgentEvidenceItem,
    AgentExplanationRequest,
    AgentForewarningSummary,
    AgentInterventionStatus,
    PlatformCapability,
)


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _event_snapshot(
    db: AsyncSession,
    event: RiskEvent,
) -> tuple[str, AgentExplanationRequest]:
    evidence_ids = loads(event.evidence_ids, [])
    evidence_rows = (await db.execute(
        select(Evidence).where(Evidence.evidence_id.in_(evidence_ids))
    )).scalars().all()
    evidence_by_id = {item.evidence_id: item for item in evidence_rows}
    evidence_items = [
        AgentEvidenceItem(
            evidence_type=evidence_by_id[evidence_id].evidence_type,
            explanation=evidence_by_id[evidence_id].explanation,
        )
        for evidence_id in evidence_ids
        if evidence_id in evidence_by_id
    ][:12]
    if not evidence_items:
        for item in loads(event.evidence_summary, [])[:12]:
            evidence_items.append(AgentEvidenceItem(
                evidence_type=item["evidence_type"],
                explanation=item["explanation"],
            ))
    if not evidence_items:
        raise ServiceError(409, "EVENT_EVIDENCE_REQUIRED", "event has no explainable Evidence")

    latest_intervention = (await db.execute(
        select(InterventionResult)
        .where(
            InterventionResult.event_id == event.event_id,
            InterventionResult.action_type != "family_feedback",
        )
        .order_by(InterventionResult.started_at.desc())
    )).scalars().first()
    # Represent a resident response as a normalized semantic instead of a transcript.
    if latest_intervention is not None and latest_intervention.resident_response:
        semantic = canonical_resident_response(latest_intervention.resident_response)
        if semantic is not None:
            evidence_items = evidence_items[:11]
            evidence_items.append(AgentEvidenceItem(
                evidence_type="resident_response",
                explanation=semantic,
            ))
    intervention_status = AgentInterventionStatus.NOT_STARTED
    if latest_intervention is not None:
        intervention_status = AgentInterventionStatus(latest_intervention.delivery_status)

    forewarning_row = (await db.execute(
        select(ForewarningSnapshot)
        .where(ForewarningSnapshot.event_id == event.event_id)
        .order_by(ForewarningSnapshot.evaluated_at.desc(), ForewarningSnapshot.id.desc())
    )).scalars().first()
    forewarning = None
    if forewarning_row is not None:
        factors = loads(forewarning_row.factors_payload, [])
        forewarning = AgentForewarningSummary(
            snapshot_id=forewarning_row.snapshot_id,
            assessment_status=forewarning_row.assessment_status,
            confidence_level=forewarning_row.confidence_level,
            baseline_status=AgentBaselineStatus(forewarning_row.baseline_status),
            instant_index=float(forewarning_row.instant_index),
            short_30s_index=float(forewarning_row.short_30s_index),
            trend_3min_index=float(forewarning_row.trend_3min_index),
            dominant_factors=[item.get("factor", "") for item in factors if item.get("factor")][:5],
            degradation_reasons=loads(forewarning_row.degradation_payload, [])[:8],
        )

    verified = [
        PlatformCapability.EZVIZ_DEVICE_STATUS,
        PlatformCapability.EZVIZ_CAPTURE,
        PlatformCapability.EZVIZ_WEBHOOK,
        PlatformCapability.MOCK_VOICE,
        PlatformCapability.TEXT_NOTICE,
    ]
    unverified = []
    if EZVIZ_LIVE_PLAYBACK_VERIFIED:
        verified.append(PlatformCapability.EZVIZ_LIVE_PLAYBACK)
    else:
        unverified.append(PlatformCapability.EZVIZ_LIVE_PLAYBACK)
    if EZVIZ_VOICE_VERIFIED:
        verified.append(PlatformCapability.EZVIZ_SERVER_VOICE)
    else:
        unverified.append(PlatformCapability.EZVIZ_SERVER_VOICE)

    version_payload: dict[str, Any] = {
        "event_id": event.event_id,
        "updated_at": aware(event.updated_at).isoformat(),
        "risk_level": event.risk_level,
        "risk_score": event.risk_score,
        "status": event.status,
        "evidence_ids": evidence_ids,
        "verified_capabilities": [item.value for item in verified],
        "unverified_capabilities": [item.value for item in unverified],
        "latest_intervention": None if latest_intervention is None else {
            "result_id": latest_intervention.result_id,
            "delivery_status": latest_intervention.delivery_status,
            "resident_response": latest_intervention.resident_response,
            "resolved": latest_intervention.resolved,
            "completed_at": aware(latest_intervention.completed_at).isoformat()
            if latest_intervention.completed_at else None,
        },
        "forewarning": forewarning.model_dump(mode="json") if forewarning else None,
    }
    version_hash = hashlib.sha256(dumps(version_payload).encode("utf-8")).hexdigest()
    request_id = AgentExplanationService.request_id_for_event(event.event_id, version_hash)
    request = AgentExplanationRequest(
        schema_version="agent-explanation/1.0",
        request_id=request_id,
        event_id=event.event_id,
        resident_id=event.resident_id,
        risk_level=event.risk_level,
        risk_score=float(event.risk_score),
        time_horizon=event.time_horizon,
        evidence=evidence_items,
        baseline_status=AgentBaselineStatus.UNAVAILABLE,
        intervention_status=intervention_status,
        verified_capabilities=verified,
        unverified_capabilities=unverified,
        forewarning=forewarning,
    )
    return version_hash, request


def job_dict(row: AgentExplanationJob) -> dict[str, Any]:
    return {
        "request_id": row.request_id,
        "event_id": row.event_id,
        "event_version_hash": row.event_version_hash,
        "status": row.status,
        "explanation": loads(row.response_payload, None),
        "generated_by": row.generated_by,
        "fallback_used": row.fallback_used,
        "attempt_count": row.attempt_count,
        "error_code": row.error_code,
        "created_at": utc_naive_to_cn(row.created_at),
        "completed_at": utc_naive_to_cn(row.completed_at) if row.completed_at else None,
    }


async def enqueue_event_explanation(
    db: AsyncSession,
    event_id: str,
) -> tuple[AgentExplanationJob, bool]:
    event = (await db.execute(
        select(RiskEvent).where(RiskEvent.event_id == event_id)
    )).scalar_one_or_none()
    if event is None:
        raise ServiceError(404, "EVENT_NOT_FOUND", "risk event does not exist")
    version_hash, request = await _event_snapshot(db, event)
    existing = (await db.execute(
        select(AgentExplanationJob).where(
            AgentExplanationJob.request_id == request.request_id
        )
    )).scalar_one_or_none()
    if existing:
        if existing.event_version_hash != version_hash or existing.request_payload != dumps(
            request.model_dump(mode="json")
        ):
            raise ServiceError(409, "EXPLANATION_REQUEST_CONFLICT", "request_id content conflicts")
        return existing, False
    row = AgentExplanationJob(
        request_id=request.request_id,
        event_id=event.event_id,
        event_version_hash=version_hash,
        request_payload=dumps(request.model_dump(mode="json")),
        status="PENDING",
        available_at=utcnow_naive(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, True


async def latest_event_explanation(db: AsyncSession, event_id: str) -> dict[str, Any]:
    event_exists = (await db.execute(
        select(RiskEvent.event_id).where(RiskEvent.event_id == event_id)
    )).scalar_one_or_none()
    if event_exists is None:
        raise ServiceError(404, "EVENT_NOT_FOUND", "risk event does not exist")
    row = (await db.execute(
        select(AgentExplanationJob)
        .where(AgentExplanationJob.event_id == event_id)
        .order_by(AgentExplanationJob.id.desc())
    )).scalars().first()
    if row is None:
        return {"event_id": event_id, "status": "NOT_REQUESTED", "attempt_count": 0}
    return job_dict(row)


async def claim_next_explanation_job(db: AsyncSession) -> AgentExplanationJob | None:
    now = utcnow_naive()
    candidate = (await db.execute(
        select(AgentExplanationJob)
        .where(
            or_(
                AgentExplanationJob.status.in_(("PENDING", "RETRY")),
                and_(
                    AgentExplanationJob.status == "PROCESSING",
                    AgentExplanationJob.lease_until <= now,
                ),
            ),
            AgentExplanationJob.available_at <= now,
        )
        .order_by(AgentExplanationJob.created_at)
        .limit(1)
    )).scalar_one_or_none()
    if candidate is None:
        return None
    claimed = await db.execute(
        update(AgentExplanationJob)
        .where(
            AgentExplanationJob.id == candidate.id,
            AgentExplanationJob.status == candidate.status,
        )
        .values(
            status="PROCESSING",
            attempt_count=AgentExplanationJob.attempt_count + 1,
            lease_until=now + timedelta(seconds=45),
            error_code=None,
        )
    )
    await db.commit()
    if claimed.rowcount != 1:
        return None
    claimed_job = await db.get(AgentExplanationJob, candidate.id)
    # db.get() opens a read transaction. Close it before the external model call.
    await db.commit()
    return claimed_job


async def process_explanation_job(
    db: AsyncSession,
    job: AgentExplanationJob,
    *,
    service: AgentExplanationService | None = None,
) -> AgentExplanationJob:
    service = service or build_default_agent_explanation_service()
    try:
        request = AgentExplanationRequest.model_validate(loads(job.request_payload, {}))
        response = await service.explain(request)
        job.response_payload = dumps(response.model_dump(mode="json"))
        job.generated_by = response.generated_by
        job.fallback_used = response.fallback_used
        job.status = "FALLBACK" if response.fallback_used else "SUCCESS"
        job.completed_at = utcnow_naive()
        job.lease_until = None
        job.error_code = None
    except Exception as exc:
        if job.attempt_count < job.max_attempts:
            job.status = "RETRY"
            job.available_at = utcnow_naive() + timedelta(seconds=2 ** job.attempt_count)
        else:
            job.status = "FAILED"
            job.completed_at = utcnow_naive()
        job.lease_until = None
        job.error_code = f"AGENT_INFRASTRUCTURE_{type(exc).__name__.upper()}"[:64]
    await db.commit()
    await db.refresh(job)
    return job
