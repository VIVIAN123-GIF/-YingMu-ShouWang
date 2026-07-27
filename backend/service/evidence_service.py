from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Evidence, Observation
from backend.schemas.evidence import EvidenceCreate
from backend.service.errors import ServiceError
from backend.service.risk_service import evaluate
from backend.service.rule_log_service import log_rule
from backend.service.serialization import dumps, evidence_dict


async def create_evidence(db: AsyncSession, payload: EvidenceCreate, request_id: str):
    existing = (await db.execute(select(Evidence).where(Evidence.evidence_id == payload.evidence_id))).scalar_one_or_none()
    if existing:
        if dumps(evidence_dict(existing) | {"timestamp": evidence_dict(existing)["timestamp"].isoformat()}) != dumps(payload.model_dump(mode="json")):
            raise ServiceError(409, "EVIDENCE_ID_CONFLICT", "evidence_id exists with different content")
        result = await evaluate(db, payload.resident_id, payload.timestamp, payload.evidence_id)
        return evidence_dict(existing), False, True, result

    observations = (await db.execute(select(Observation).where(
        Observation.observation_id.in_(payload.observation_ids)))).scalars().all()
    found = {row.observation_id for row in observations}
    missing = [item for item in payload.observation_ids if item not in found]
    if missing:
        raise ServiceError(409, "OBSERVATION_NOT_FOUND", f"observations do not exist: {missing}")
    if any(row.resident_id != payload.resident_id for row in observations):
        raise ServiceError(409, "RESIDENT_MISMATCH", "Evidence and Observation resident_id must match")
    if any(row.source_mode != payload.source_mode.value or row.simulated != payload.simulated for row in observations):
        raise ServiceError(409, "SOURCE_MISMATCH", "Evidence must inherit source_mode and simulated")

    data = payload.model_dump(exclude={"observation_ids"})
    row = Evidence(**data, observation_ids=dumps(payload.observation_ids))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    result = await evaluate(db, payload.resident_id, payload.timestamp, payload.evidence_id)
    log_rule({"timestamp": payload.timestamp.isoformat(), "request_id": request_id,
              "resident_id": payload.resident_id, "evidence_id": payload.evidence_id,
              "evidence_type": payload.evidence_type, "source_mode": payload.source_mode.value,
              "simulated": payload.simulated, "ruleset_version": result["ruleset_version"],
              "matched_rule": result["matched_rule"], "previous_state": "GREEN",
              "next_state": result["risk_level"],
              "event_id": result["event"]["event_id"] if result["event"] else None, "error": None})
    return evidence_dict(row), True, False, result
