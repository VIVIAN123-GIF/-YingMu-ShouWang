import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import MIN_EVIDENCE_CONFIDENCE, MIN_EVIDENCE_QUALITY, RULESET_VERSION
from backend.db.models import Evidence, RiskEvent, RuleTrace
from backend.service.serialization import aware, dumps, event_dict


class MockRiskEngine:
    async def evaluate(self, db: AsyncSession, resident_id: str, evaluated_at, trigger_evidence_id=None):
        existing = (await db.execute(select(RiskEvent).where(
            RiskEvent.resident_id == resident_id, RiskEvent.status.in_(["OPEN", "INTERVENING", "OBSERVING"])
        ).order_by(RiskEvent.created_at.desc()))).scalars().first()
        if existing:
            return "ORANGE", False, existing, "R-FALL-02"

        start = evaluated_at - timedelta(seconds=30)
        rows = (await db.execute(select(Evidence).where(
            Evidence.resident_id == resident_id, Evidence.timestamp >= start,
            Evidence.timestamp <= evaluated_at, Evidence.risk_domain == "FALL"
        ).order_by(Evidence.timestamp))).scalars().all()
        valid = [r for r in rows if r.data_quality >= MIN_EVIDENCE_QUALITY and
                 r.confidence >= MIN_EVIDENCE_CONFIDENCE]
        types = {r.evidence_type for r in valid}
        orange = {"rapid_rise", "trunk_sway"}.issubset(types) and any(r.confidence >= .8 for r in valid)
        if not orange:
            return "GREEN", False, None, "R-FALL-01"

        event_id = "event-mock-fall-001" if resident_id == "resident-mock-001" else f"event-{uuid.uuid4().hex[:16]}"
        evidence_rows = [r for r in valid if r.evidence_type in {"rapid_rise", "trunk_sway"}]
        row = RiskEvent(schema_version="1.0", event_id=event_id, resident_id=resident_id,
                        created_at=evaluated_at, updated_at=evaluated_at, primary_domain="FALL",
                        related_domains=dumps(["FALL"]), risk_level="ORANGE", risk_score=.82,
                        evidence_ids=dumps([r.evidence_id for r in evidence_rows]),
                        evidence_summary=dumps([{"evidence_id": r.evidence_id, "evidence_type": r.evidence_type,
                                                "explanation": r.explanation} for r in evidence_rows]),
                        time_horizon="IMMINENT", recommended_action="立即进行柔性语音干预并通知家属",
                        intervention_policy="fall-orange-v1", status="INTERVENING",
                        ruleset_version=RULESET_VERSION, source_mode=evidence_rows[-1].source_mode,
                        simulated=all(r.simulated for r in evidence_rows), evidences=evidence_rows)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return "ORANGE", True, row, "R-FALL-02"


engine = MockRiskEngine()


async def evaluate(db: AsyncSession, resident_id: str, evaluated_at, evidence_id=None):
    previous = "GREEN"
    level, created, event, matched = await engine.evaluate(db, resident_id, evaluated_at, evidence_id)
    trace = RuleTrace(trace_id=f"trace-{uuid.uuid4().hex}", event_id=event.event_id if event else None,
                      resident_id=resident_id, evidence_id=evidence_id, evaluated_at=evaluated_at,
                      ruleset_version=RULESET_VERSION, matched_rule=matched, previous_state=previous,
                      next_state=level, event_created=created, error=None)
    db.add(trace)
    await db.commit()
    return {"risk_level": level, "event_created": created, "event": event_dict(event) if event else None,
            "matched_rule": matched, "ruleset_version": RULESET_VERSION}
