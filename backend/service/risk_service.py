import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import MIN_EVIDENCE_CONFIDENCE, MIN_EVIDENCE_QUALITY, RULESET_VERSION
from backend.db.models import Evidence, InterventionResult, RiskEvent, RiskEventEvidence, RuleTrace
from backend.service.serialization import aware, dumps, event_dict, loads


ACTIVE_EVENT_STATUSES = ("OPEN", "INTERVENING", "OBSERVING")
DANGER_EVIDENCE_TYPES = {
    "rapid_rise", "slow_rise", "trunk_sway", "gait_instability", "relative_speed_change",
}
RECOVERY_SECONDS = 60
STABLE_POSTURE_SECONDS = 15.0


def _timestamp_after(left, right) -> bool:
    return aware(left) > aware(right)


def _timestamp_at_or_after(left, right) -> bool:
    return aware(left) >= aware(right)


def _usable(evidence: Evidence) -> bool:
    return (
        evidence.data_quality >= MIN_EVIDENCE_QUALITY
        and evidence.confidence >= MIN_EVIDENCE_CONFIDENCE
    )


async def _active_event(db: AsyncSession, resident_id: str) -> RiskEvent | None:
    return (await db.execute(
        select(RiskEvent)
        .where(
            RiskEvent.resident_id == resident_id,
            RiskEvent.status.in_(ACTIVE_EVENT_STATUSES),
        )
        .order_by(RiskEvent.created_at.desc())
    )).scalars().first()


async def _attach_evidence(db: AsyncSession, event: RiskEvent, evidence: Evidence) -> None:
    """Keep the immutable event snapshot and relational evidence link in sync."""
    evidence_ids = loads(event.evidence_ids, [])
    if evidence.evidence_id not in evidence_ids:
        evidence_ids.append(evidence.evidence_id)
        event.evidence_ids = dumps(evidence_ids)
        summaries = loads(event.evidence_summary, [])
        summaries.append({
            "evidence_id": evidence.evidence_id,
            "evidence_type": evidence.evidence_type,
            "explanation": evidence.explanation,
        })
        event.evidence_summary = dumps(summaries)
    link = (await db.execute(select(RiskEventEvidence).where(
        RiskEventEvidence.event_id == event.event_id,
        RiskEventEvidence.evidence_id == evidence.evidence_id,
    ))).scalar_one_or_none()
    if not link:
        db.add(RiskEventEvidence(event_id=event.event_id, evidence_id=evidence.evidence_id))


async def _danger_during_observation(
    db: AsyncSession,
    event: RiskEvent,
    evaluated_at,
) -> Evidence | None:
    if not event.recovery_started_at:
        return None
    rows = (await db.execute(
        select(Evidence)
        .where(
            Evidence.resident_id == event.resident_id,
            Evidence.risk_domain == "FALL",
            Evidence.timestamp > event.recovery_started_at,
            Evidence.timestamp <= evaluated_at,
        )
        .order_by(Evidence.timestamp)
    )).scalars().all()
    return next((row for row in rows if row.evidence_type in DANGER_EVIDENCE_TYPES and _usable(row)), None)


async def _resolve_event(db: AsyncSession, event: RiskEvent, evaluated_at) -> None:
    event.status = "RESOLVED"
    event.updated_at = evaluated_at
    result = (await db.execute(
        select(InterventionResult)
        .where(
            InterventionResult.event_id == event.event_id,
            InterventionResult.delivery_status == "SUCCESS",
        )
        .order_by(InterventionResult.started_at.desc())
    )).scalars().first()
    if result:
        result.resident_response = "stable"
        result.risk_after = 0.24
        result.resolved = True
        result.resolution_reason = "姿态恢复且60秒观察期内无新风险证据"
        result.completed_at = evaluated_at
    await db.commit()


async def _write_trace(
    db: AsyncSession,
    *,
    resident_id: str,
    evaluated_at,
    evidence_id: str | None,
    matched_rule: str,
    previous_state: str,
    next_state: str,
    previous_status: str | None,
    next_status: str | None,
    event: RiskEvent | None,
    event_created: bool,
) -> None:
    db.add(RuleTrace(
        trace_id=f"trace-{uuid.uuid4().hex}",
        event_id=event.event_id if event else None,
        resident_id=resident_id,
        evidence_id=evidence_id,
        evaluated_at=evaluated_at,
        ruleset_version=RULESET_VERSION,
        matched_rule=matched_rule,
        previous_state=previous_state,
        next_state=next_state,
        previous_status=previous_status,
        next_status=next_status,
        event_created=event_created,
        error=None,
    ))
    await db.commit()


class MockRiskEngine:
    async def evaluate(
        self,
        db: AsyncSession,
        resident_id: str,
        evaluated_at,
        trigger_evidence_id: str | None = None,
    ):
        existing = await _active_event(db, resident_id)
        trigger = None
        if trigger_evidence_id:
            trigger = (await db.execute(
                select(Evidence).where(Evidence.evidence_id == trigger_evidence_id)
            )).scalar_one_or_none()

        # R-FALL-03 is a gate for every evidence type, including recovery evidence.
        if trigger and not _usable(trigger):
            level = existing.risk_level if existing else "GREEN"
            return level, False, existing, "R-FALL-03"

        if existing:
            if (
                existing.status == "INTERVENING"
                and trigger
                and trigger.evidence_type == "posture_recovered"
                and isinstance(trigger.current_value, (int, float))
                and float(trigger.current_value) >= STABLE_POSTURE_SECONDS
                and _timestamp_after(trigger.timestamp, existing.created_at)
            ):
                await _attach_evidence(db, existing, trigger)
                existing.status = "OBSERVING"
                existing.recovery_started_at = trigger.timestamp
                existing.updated_at = trigger.timestamp
                await db.commit()
                return "ORANGE", False, existing, "R-FALL-04"

            if existing.status == "OBSERVING":
                danger = None
                if (
                    trigger
                    and trigger.evidence_type in DANGER_EVIDENCE_TYPES
                    and existing.recovery_started_at
                    and _timestamp_after(trigger.timestamp, existing.recovery_started_at)
                ):
                    danger = trigger
                elif not trigger:
                    danger = await _danger_during_observation(db, existing, evaluated_at)
                if danger:
                    await _attach_evidence(db, existing, danger)
                    existing.status = "INTERVENING"
                    existing.recovery_started_at = None
                    existing.updated_at = danger.timestamp if trigger else evaluated_at
                    await db.commit()
                    return "ORANGE", False, existing, "R-FALL-06"
                if (
                    not trigger
                    and existing.recovery_started_at
                    and _timestamp_at_or_after(
                        evaluated_at, aware(existing.recovery_started_at) + timedelta(seconds=RECOVERY_SECONDS)
                    )
                ):
                    await _resolve_event(db, existing, evaluated_at)
                    return "GREEN", False, existing, "R-FALL-05"

            return existing.risk_level, False, existing, "R-FALL-02"

        start = evaluated_at - timedelta(seconds=30)
        rows = (await db.execute(
            select(Evidence)
            .where(
                Evidence.resident_id == resident_id,
                Evidence.timestamp >= start,
                Evidence.timestamp <= evaluated_at,
                Evidence.risk_domain == "FALL",
            )
            .order_by(Evidence.timestamp)
        )).scalars().all()
        valid = [row for row in rows if _usable(row)]
        types = {row.evidence_type for row in valid}
        orange = (
            {"rapid_rise", "trunk_sway"}.issubset(types)
            and any(row.confidence >= 0.80 for row in valid)
        )
        if not orange:
            return "GREEN", False, None, "R-FALL-01"

        event_id = (
            "event-mock-fall-001"
            if resident_id == "resident-mock-001"
            else f"event-{uuid.uuid4().hex[:16]}"
        )
        evidence_rows = [
            row for row in valid
            if row.evidence_type in {"rapid_rise", "trunk_sway"}
        ]
        event = RiskEvent(
            schema_version="1.0",
            event_id=event_id,
            resident_id=resident_id,
            created_at=evaluated_at,
            updated_at=evaluated_at,
            primary_domain="FALL",
            related_domains=dumps([]),
            risk_level="ORANGE",
            risk_score=0.82,
            evidence_ids=dumps([row.evidence_id for row in evidence_rows]),
            evidence_summary=dumps([
                {
                    "evidence_id": row.evidence_id,
                    "evidence_type": row.evidence_type,
                    "explanation": row.explanation,
                }
                for row in evidence_rows
            ]),
            time_horizon="IMMINENT",
            recommended_action="先坐稳，扶住固定物，再慢慢起身",
            intervention_policy="fall-orange-gentle-v1",
            status="INTERVENING",
            ruleset_version=RULESET_VERSION,
            source_mode=evidence_rows[-1].source_mode,
            simulated=all(row.simulated for row in evidence_rows),
            evidences=evidence_rows,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return "ORANGE", True, event, "R-FALL-02"


engine = MockRiskEngine()


async def evaluate(
    db: AsyncSession,
    resident_id: str,
    evaluated_at,
    evidence_id: str | None = None,
    *,
    duplicate: bool = False,
    system_evidence_id: str | None = None,
):
    previous_event = await _active_event(db, resident_id)
    previous_state = previous_event.risk_level if previous_event else "GREEN"
    previous_status = previous_event.status if previous_event else None

    if duplicate:
        level = previous_state
        event = previous_event
        created = False
        matched = "R-SYSTEM-01"
    else:
        level, created, event, matched = await engine.evaluate(
            db,
            resident_id,
            evaluated_at,
            evidence_id,
        )

    next_status = event.status if event else None
    await _write_trace(
        db,
        resident_id=resident_id,
        evaluated_at=evaluated_at,
        evidence_id=evidence_id,
        matched_rule=matched,
        previous_state=previous_state,
        next_state=level,
        previous_status=previous_status,
        next_status=next_status,
        event=event,
        event_created=created,
    )
    return {
        "risk_level": level,
        "previous_state": previous_state,
        "next_state": level,
        "previous_status": previous_status,
        "next_status": next_status,
        "event_created": created,
        "event": event_dict(event) if event else None,
        "matched_rule": matched,
        "ruleset_version": RULESET_VERSION,
        "system_evidence_id": system_evidence_id,
    }
