import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Evidence, InterventionResult, Observation, RiskEvent, RuleTrace
from backend.service.errors import ServiceError
from backend.schemas.intervention_result import FamilyFeedbackCreate, InterventionResultCreate
from backend.config import ENV_MODE, EZVIZ_DEVICE_SERIAL, EZVIZ_VOICE_VERIFIED
from backend.utils.ezviz_api import EzvizAPI
from backend.service.serialization import (aware, event_dict, evidence_dict, intervention_dict,
                                           loads, observation_dict)


async def list_events(db: AsyncSession, resident_id: str | None = None):
    query = select(RiskEvent).order_by(RiskEvent.created_at.desc())
    if resident_id:
        query = query.where(RiskEvent.resident_id == resident_id)
    rows = (await db.execute(query)).scalars().all()
    return [event_dict(row) for row in rows]


async def create_intervention_result(db: AsyncSession, event_id: str,
                                     payload: InterventionResultCreate):
    if payload.event_id != event_id:
        raise ServiceError(409, "EVENT_ID_MISMATCH", "path and payload event_id must match")
    event = (await db.execute(select(RiskEvent).where(RiskEvent.event_id == event_id))).scalar_one_or_none()
    if not event:
        raise ServiceError(404, "EVENT_NOT_FOUND", "risk event does not exist")
    existing = (await db.execute(select(InterventionResult).where(
        InterventionResult.result_id == payload.result_id))).scalar_one_or_none()
    if existing:
        if intervention_dict(existing) != payload.model_dump():
            raise ServiceError(409, "RESULT_ID_CONFLICT", "result_id exists with different content")
        return intervention_dict(existing), True
    if payload.resolved:
        raise ServiceError(
            409,
            "RESULT_RESOLUTION_FORBIDDEN",
            "resolved may only be set by the recovery state machine",
        )
    row = InterventionResult(**payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return intervention_dict(row), False


async def record_feedback(db: AsyncSession, event_id: str, payload: FamilyFeedbackCreate):
    event = (await db.execute(select(RiskEvent).where(RiskEvent.event_id == event_id))).scalar_one_or_none()
    if not event:
        raise ServiceError(404, "EVENT_NOT_FOUND", "risk event does not exist")
    existing = (await db.execute(select(InterventionResult).where(
        InterventionResult.result_id == payload.feedback_id))).scalar_one_or_none()
    if existing:
        if (existing.event_id != event_id or existing.action_type != "family_feedback"
                or existing.family_feedback != payload.value or existing.operator != payload.operator):
            raise ServiceError(409, "FEEDBACK_ID_CONFLICT",
                               "feedback_id exists with different content")
        return intervention_dict(existing), True
    now = datetime.now(timezone(timedelta(hours=8)))
    result = InterventionResultCreate(
        result_id=payload.feedback_id, event_id=event_id, started_at=now, completed_at=now,
        action_type="family_feedback", tool_name="family_feedback", delivery_status="SUCCESS",
        resident_response=None, family_feedback=payload.value, risk_after=None, resolved=False,
        resolution_reason=None, operator=payload.operator, source_mode=event.source_mode,
        simulated=event.simulated)
    return await create_intervention_result(db, event_id, result)


async def intervene(db: AsyncSession, event_id: str):
    event = (await db.execute(select(RiskEvent).where(RiskEvent.event_id == event_id))).scalar_one_or_none()
    if not event:
        raise ServiceError(404, "EVENT_NOT_FOUND", "risk event does not exist")
    if event.status not in {"OPEN", "INTERVENING"}:
        raise ServiceError(409, "EVENT_NOT_INTERVENABLE", "event is not open for intervention")
    now = datetime.now(timezone(timedelta(hours=8)))
    delivery_status, tool_name, reason = "SUCCESS", "mock_voice", "Declared Mock fallback"
    if ENV_MODE == "live" and EZVIZ_VOICE_VERIFIED:
        try:
            await EzvizAPI.voice_broadcast(EZVIZ_DEVICE_SERIAL, "请先坐稳并注意安全")
            tool_name, reason = "ezviz_voice", None
        except Exception:
            delivery_status, tool_name = "FAILED", "ezviz_voice"
            reason = "Verified Ezviz tool call failed; event retained for retry or fallback"
    elif ENV_MODE == "live":
        delivery_status, tool_name = "FAILED", "ezviz_voice"
        reason = "Ezviz voice capability has not been verified; live call was not attempted"
    payload = InterventionResultCreate(
        result_id=f"result-{uuid.uuid4().hex}", event_id=event_id, started_at=now,
        completed_at=now, action_type="voice", tool_name=tool_name,
        delivery_status=delivery_status, resident_response=None, family_feedback=None,
        risk_after=None, resolved=False, resolution_reason=reason, operator="system",
        source_mode=event.source_mode, simulated=event.simulated)
    result, _ = await create_intervention_result(db, event_id, payload)
    return result


async def event_detail(db: AsyncSession, event_id: str):
    event = (await db.execute(select(RiskEvent).where(RiskEvent.event_id == event_id))).scalar_one_or_none()
    if not event:
        raise ServiceError(404, "EVENT_NOT_FOUND", "risk event does not exist")
    evidence_ids = loads(event.evidence_ids, [])
    evidences = (await db.execute(select(Evidence).where(Evidence.evidence_id.in_(evidence_ids)))).scalars().all()
    observation_ids = sorted({oid for row in evidences for oid in loads(row.observation_ids, [])})
    observations = (await db.execute(select(Observation).where(
        Observation.observation_id.in_(observation_ids)))).scalars().all()
    traces = (await db.execute(select(RuleTrace).where(RuleTrace.resident_id == event.resident_id)
                               .order_by(RuleTrace.evaluated_at))).scalars().all()
    interventions = (await db.execute(select(InterventionResult).where(
        InterventionResult.event_id == event_id))).scalars().all()
    trace_data = [{"trace_id": r.trace_id, "event_id": r.event_id, "resident_id": r.resident_id,
                   "evidence_id": r.evidence_id, "evaluated_at": aware(r.evaluated_at).isoformat(),
                   "ruleset_version": r.ruleset_version, "matched_rule": r.matched_rule,
                   "previous_state": r.previous_state, "next_state": r.next_state,
                   "previous_status": r.previous_status, "next_status": r.next_status,
                   "event_created": r.event_created, "error": r.error} for r in traces]
    intervention_data = [intervention_dict(row) for row in interventions]
    return {**event_dict(event), "evidences": [evidence_dict(r) for r in evidences],
            "observations": [observation_dict(r) for r in observations],
            "rule_traces": trace_data, "interventions": intervention_data}
