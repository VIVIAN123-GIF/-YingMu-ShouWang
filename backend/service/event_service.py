from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Evidence, InterventionResult, Observation, RiskEvent, RuleTrace
from backend.service.errors import ServiceError
from backend.service.serialization import aware, event_dict, evidence_dict, loads, observation_dict


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
                   "event_created": r.event_created, "error": r.error} for r in traces]
    intervention_data = [{column.name: getattr(row, column.name) for column in row.__table__.columns
                          if column.name not in {"id", "create_time"}} for row in interventions]
    return {"event": event_dict(event), "evidence": [evidence_dict(r) for r in evidences],
            "observations": [observation_dict(r) for r in observations],
            "rule_traces": trace_data, "interventions": intervention_data}
