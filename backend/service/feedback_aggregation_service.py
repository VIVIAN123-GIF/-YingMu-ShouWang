"""Create deterministic backend-only evidence from event feedback history."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import RULESET_VERSION
from backend.db.models import Evidence, InterventionResult, Observation, RiskEvent
from backend.service.serialization import aware, dumps, loads
from backend.service.resident_response import canonical_resident_response
from contracts.v1.ruleset import load_ruleset


ruleset = load_ruleset()


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


async def _existing_evidence(db: AsyncSession, evidence_id: str) -> Evidence | None:
    return (await db.execute(
        select(Evidence).where(Evidence.evidence_id == evidence_id)
    )).scalar_one_or_none()


async def aggregate_no_response(
    db: AsyncSession,
    event: RiskEvent,
    now: datetime,
) -> Evidence | None:
    """Create no_response 60 seconds after an unanswered successful intervention."""
    interventions = (await db.execute(
        select(InterventionResult)
        .where(
            InterventionResult.event_id == event.event_id,
            InterventionResult.delivery_status == "SUCCESS",
            InterventionResult.action_type != "family_feedback",
        )
        .order_by(InterventionResult.started_at.desc())
    )).scalars().all()
    if not interventions:
        return None
    delivery = next(
        (item for item in interventions if not item.resident_response),
        None,
    )
    if delivery is None:
        return None
    delivered_at = aware(delivery.completed_at or delivery.started_at)
    if aware(now) < delivered_at + timedelta(seconds=ruleset.thresholds["no_response_seconds"]):
        return None
    has_later_response = any(
        canonical_resident_response(item.resident_response) is not None
        and aware(item.started_at) >= delivered_at
        for item in interventions
    )
    if has_later_response:
        return None

    evidence_id = _stable_id("evi-internal-no-response", event.event_id, delivery.result_id)
    existing = await _existing_evidence(db, evidence_id)
    if existing:
        return existing
    observation_id = _stable_id("obs-internal-response-wait", event.event_id, delivery.result_id)
    observation = (await db.execute(
        select(Observation).where(Observation.observation_id == observation_id)
    )).scalar_one_or_none()
    waited_seconds = max(0.0, (aware(now) - delivered_at).total_seconds())
    if observation is None:
        observation = Observation(
            schema_version="1.0",
            observation_id=observation_id,
            resident_id=event.resident_id,
            timestamp=now,
            source="feedback_aggregator",
            feature_name="resident_response_wait_s",
            feature_value=dumps(round(waited_seconds, 3)),
            unit="second",
            location=None,
            confidence=1.0,
            data_quality=1.0,
            source_mode=event.source_mode,
            asset_id=None,
            simulated=event.simulated,
            extra_metadata=dumps({"event_id": event.event_id, "intervention_result_id": delivery.result_id}),
            device_sn=None,
        )
        db.add(observation)
        await db.flush()
    evidence = Evidence(
        schema_version="1.0",
        evidence_id=evidence_id,
        observation_ids=dumps([observation_id]),
        resident_id=event.resident_id,
        timestamp=now,
        risk_domain="FALL",
        evidence_type="no_response",
        severity=1.0,
        confidence=1.0,
        data_quality=1.0,
        baseline_value=float(ruleset.thresholds["no_response_seconds"]),
        current_value=round(waited_seconds, 3),
        baseline_deviation=round(waited_seconds - ruleset.thresholds["no_response_seconds"], 3),
        time_scale="SHORT",
        location=None,
        explanation="干预成功送达后超过60秒仍未收到已坐稳或求助回应",
        adapter_version=f"feedback-aggregator-{RULESET_VERSION}",
        source_mode=event.source_mode,
        simulated=event.simulated,
    )
    db.add(evidence)
    await db.commit()
    await db.refresh(evidence)
    return evidence


async def aggregate_persistent_instability(
    db: AsyncSession,
    event: RiskEvent,
    now: datetime,
) -> Evidence | None:
    """Aggregate three source-consistent usable instability signals in 30 seconds."""
    start = max(
        aware(event.created_at),
        aware(now) - timedelta(seconds=ruleset.windows["short_seconds"]),
    )
    rows = (await db.execute(
        select(Evidence)
        .where(
            Evidence.resident_id == event.resident_id,
            Evidence.timestamp >= start,
            Evidence.timestamp <= now,
            Evidence.evidence_type.in_(("trunk_sway", "gait_instability")),
        )
        .order_by(Evidence.timestamp)
    )).scalars().all()
    usable = [
        item for item in rows
        if ruleset.usable(float(item.confidence), float(item.data_quality))
        and item.source_mode == event.source_mode
        and bool(item.simulated) == bool(event.simulated)
    ]
    if len(usable) < int(ruleset.thresholds["persistent_evidence_count"]):
        return None
    selected = usable[-int(ruleset.thresholds["persistent_evidence_count"]):]
    source_signature = {item.source_mode for item in selected}
    simulated_signature = {bool(item.simulated) for item in selected}
    if len(source_signature) != 1 or len(simulated_signature) != 1:
        return None
    source_ids = sorted(item.evidence_id for item in selected)
    evidence_id = _stable_id("evi-internal-persistent", event.event_id, *source_ids)
    existing = await _existing_evidence(db, evidence_id)
    if existing:
        return existing
    observation_ids = sorted({
        observation_id
        for item in selected
        for observation_id in loads(item.observation_ids, [])
    })
    evidence = Evidence(
        schema_version="1.0",
        evidence_id=evidence_id,
        observation_ids=dumps(observation_ids),
        resident_id=event.resident_id,
        timestamp=max(item.timestamp for item in selected),
        risk_domain="FALL",
        evidence_type="persistent_instability",
        severity=max(float(item.severity) for item in selected),
        confidence=min(float(item.confidence) for item in selected),
        data_quality=min(float(item.data_quality) for item in selected),
        baseline_value=float(ruleset.thresholds["persistent_evidence_count"]),
        current_value=float(len(selected)),
        baseline_deviation=float(len(selected) - ruleset.thresholds["persistent_evidence_count"]),
        time_scale="SHORT",
        location=selected[-1].location,
        explanation="30秒内连续出现3条质量合格且来源一致的不稳定证据",
        adapter_version=f"feedback-aggregator-{RULESET_VERSION}",
        source_mode=event.source_mode,
        simulated=event.simulated,
    )
    db.add(evidence)
    await db.commit()
    await db.refresh(evidence)
    return evidence


async def aggregate_active_event_feedback(
    db: AsyncSession,
    event: RiskEvent | None,
    now: datetime,
) -> list[Evidence]:
    if event is None or event.status not in {"OPEN", "INTERVENING", "OBSERVING"}:
        return []
    generated: list[Evidence] = []
    persistent = await aggregate_persistent_instability(db, event, now)
    if persistent is not None:
        generated.append(persistent)
    if event.status == "INTERVENING":
        no_response = await aggregate_no_response(db, event, now)
        if no_response is not None:
            generated.append(no_response)
    return generated
