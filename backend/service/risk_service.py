import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import MIN_EVIDENCE_CONFIDENCE, MIN_EVIDENCE_QUALITY, RULESET_VERSION
from backend.db.models import Evidence, RiskEvent, RuleTrace
from backend.service.serialization import dumps, event_dict


ACTIVE_EVENT_STATUSES = ("OPEN", "INTERVENING", "OBSERVING")


async def _active_event(db: AsyncSession, resident_id: str) -> RiskEvent | None:
    return (await db.execute(
        select(RiskEvent)
        .where(
            RiskEvent.resident_id == resident_id,
            RiskEvent.status.in_(ACTIVE_EVENT_STATUSES),
        )
        .order_by(RiskEvent.created_at.desc())
    )).scalars().first()


async def _write_trace(
    db: AsyncSession,
    *,
    resident_id: str,
    evaluated_at,
    evidence_id: str | None,
    matched_rule: str,
    previous_state: str,
    next_state: str,
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

        if trigger and (
            trigger.data_quality < MIN_EVIDENCE_QUALITY
            or trigger.confidence < MIN_EVIDENCE_CONFIDENCE
        ):
            level = existing.risk_level if existing else "GREEN"
            return level, False, existing, "R-FALL-03"

        if existing:
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
        valid = [
            row for row in rows
            if row.data_quality >= MIN_EVIDENCE_QUALITY
            and row.confidence >= MIN_EVIDENCE_CONFIDENCE
        ]
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
            recommended_action="先坐稳，扶住固定物，再慢慢起身。",
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

    await _write_trace(
        db,
        resident_id=resident_id,
        evaluated_at=evaluated_at,
        evidence_id=evidence_id,
        matched_rule=matched,
        previous_state=previous_state,
        next_state=level,
        event=event,
        event_created=created,
    )
    return {
        "risk_level": level,
        "previous_state": previous_state,
        "next_state": level,
        "event_created": created,
        "event": event_dict(event) if event else None,
        "matched_rule": matched,
        "ruleset_version": RULESET_VERSION,
        "system_evidence_id": system_evidence_id,
    }
