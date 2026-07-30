from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import MIN_EVIDENCE_CONFIDENCE, MIN_EVIDENCE_QUALITY, RULESET_VERSION
from backend.db.models import Evidence, Observation
from backend.schemas.evidence import EvidenceCreate
from backend.service.errors import ServiceError
from backend.service.risk_service import evaluate
from backend.service.rule_log_service import log_rule
from backend.service.serialization import dumps, evidence_dict


def _log_evaluation(payload: EvidenceCreate, request_id: str, result: dict) -> None:
    log_rule({
        "timestamp": payload.timestamp.isoformat(),
        "request_id": request_id,
        "resident_id": payload.resident_id,
        "evidence_id": payload.evidence_id,
        "evidence_type": payload.evidence_type,
        "source_mode": payload.source_mode.value,
        "simulated": payload.simulated,
        "ruleset_version": result["ruleset_version"],
        "matched_rule": result["matched_rule"],
        "previous_state": result["previous_state"],
        "next_state": result["next_state"],
        "event_id": result["event"]["event_id"] if result["event"] else None,
        "error": None,
    })


async def _create_quality_evidence(
    db: AsyncSession,
    payload: EvidenceCreate,
) -> str | None:
    if (
        payload.data_quality >= MIN_EVIDENCE_QUALITY
        and payload.confidence >= MIN_EVIDENCE_CONFIDENCE
    ):
        return None

    evidence_id = f"sys-quality-{payload.evidence_id}"
    existing = (await db.execute(
        select(Evidence).where(Evidence.evidence_id == evidence_id)
    )).scalar_one_or_none()
    if existing:
        return evidence_id

    db.add(Evidence(
        schema_version="1.0",
        evidence_id=evidence_id,
        observation_ids=dumps(payload.observation_ids),
        resident_id=payload.resident_id,
        timestamp=payload.timestamp,
        risk_domain="SYSTEM",
        evidence_type="quality_gate_failed",
        severity=0.0,
        confidence=1.0,
        data_quality=payload.data_quality,
        baseline_value=None,
        current_value=payload.data_quality,
        baseline_deviation=None,
        time_scale=payload.time_scale,
        location=payload.location,
        explanation="数据质量或置信度低于工程门槛，本条证据不参与风险升级",
        adapter_version=RULESET_VERSION,
        source_mode=payload.source_mode.value,
        simulated=payload.simulated,
    ))
    await db.commit()
    return evidence_id


async def create_evidence(
    db: AsyncSession,
    payload: EvidenceCreate,
    request_id: str,
):
    existing = (await db.execute(
        select(Evidence).where(Evidence.evidence_id == payload.evidence_id)
    )).scalar_one_or_none()
    if existing:
        existing_payload = evidence_dict(existing)
        existing_payload["timestamp"] = existing_payload["timestamp"].isoformat()
        if dumps(existing_payload) != dumps(payload.model_dump(mode="json")):
            raise ServiceError(
                409,
                "EVIDENCE_ID_CONFLICT",
                "evidence_id exists with different content",
            )
        result = await evaluate(
            db,
            payload.resident_id,
            payload.timestamp,
            payload.evidence_id,
            duplicate=True,
        )
        _log_evaluation(payload, request_id, result)
        return evidence_dict(existing), False, True, result

    observations = (await db.execute(
        select(Observation).where(
            Observation.observation_id.in_(payload.observation_ids)
        )
    )).scalars().all()
    found = {row.observation_id for row in observations}
    missing = [item for item in payload.observation_ids if item not in found]
    if missing:
        raise ServiceError(
            409,
            "OBSERVATION_NOT_FOUND",
            f"observations do not exist: {missing}",
        )
    if any(row.resident_id != payload.resident_id for row in observations):
        raise ServiceError(
            409,
            "RESIDENT_MISMATCH",
            "Evidence and Observation resident_id must match",
        )
    if any(
        row.source_mode != payload.source_mode.value
        or row.simulated != payload.simulated
        for row in observations
    ):
        raise ServiceError(
            409,
            "SOURCE_MISMATCH",
            "Evidence must inherit source_mode and simulated",
        )

    data = payload.model_dump(exclude={"observation_ids"})
    row = Evidence(**data, observation_ids=dumps(payload.observation_ids))
    db.add(row)
    await db.commit()
    await db.refresh(row)

    system_evidence_id = await _create_quality_evidence(db, payload)
    result = await evaluate(
        db,
        payload.resident_id,
        payload.timestamp,
        payload.evidence_id,
        system_evidence_id=system_evidence_id,
    )
    _log_evaluation(payload, request_id, result)
    return evidence_dict(row), True, False, result
