import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import RULESET_VERSION
from backend.db.models import Evidence, InterventionResult, RiskEvent, RiskEventEvidence, RuleTrace
from backend.service.serialization import aware, dumps, event_dict, loads
from contracts.v1.decision import FallDecisionPolicy, quality_snapshot
from contracts.v1.ruleset import load_ruleset


ACTIVE_EVENT_STATUSES = ("OPEN", "INTERVENING", "OBSERVING")
ruleset = load_ruleset()
policy = FallDecisionPolicy(ruleset)


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


async def _resolve_event(db: AsyncSession, event: RiskEvent, evaluated_at) -> None:
    event.status = "RESOLVED"
    event.updated_at = evaluated_at
    result = (await db.execute(
        select(InterventionResult)
        .where(
            InterventionResult.event_id == event.event_id,
            InterventionResult.delivery_status == "SUCCESS",
            InterventionResult.action_type != "family_feedback",
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


async def _context(
    db: AsyncSession,
    resident_id: str,
    evaluated_at,
) -> tuple[list[Evidence], dict, dict]:
    short_start = evaluated_at - timedelta(seconds=ruleset.windows["short_seconds"])
    medium_start = evaluated_at - timedelta(hours=ruleset.windows["medium_hours"])
    long_start = evaluated_at - timedelta(days=ruleset.windows["long_days"])
    all_rows = (await db.execute(
        select(Evidence)
        .where(
            Evidence.resident_id == resident_id,
            Evidence.timestamp >= long_start,
            Evidence.timestamp <= evaluated_at,
        )
        .order_by(Evidence.timestamp)
    )).scalars().all()
    recent = [item for item in all_rows if aware(item.timestamp) >= aware(short_start) and item.risk_domain == "FALL"]
    medium = [item for item in all_rows if aware(item.timestamp) >= aware(medium_start)]
    contributions = {
        "night": ruleset.context_factors["night"] if evaluated_at.hour >= 22 or evaluated_at.hour < 6 else 0.0,
        "low_light": ruleset.context_factors["low_light"] if any(
            item.evidence_type == "low_illumination" for item in medium
        ) else 0.0,
        "repeated_daily_abnormality": ruleset.context_factors["repeated_daily_abnormality"] if sum(
            item.evidence_type == "rapid_rise" for item in medium
        ) >= 2 else 0.0,
        "yellow_state": 0.0,
        "long_term_deviation": ruleset.context_factors["long_term_deviation"] if any(
            item.time_scale == "LONG"
            and item.baseline_deviation is not None
            and abs(float(item.baseline_deviation)) >= 2
            for item in all_rows
        ) else 0.0,
    }
    context_score = round(min(sum(contributions.values()), 1.0), 4)
    context_snapshot = {"contributions": contributions, "context_score": context_score}
    try:
        from backend.service.baseline_service import memory_store
        baseline_response = await memory_store.baseline(db, resident_id, evaluated_at)
        baseline_snapshot = {
            "overall_status": baseline_response.get("overall_status"),
            "provenance": baseline_response.get("provenance"),
            "baselines": baseline_response.get("baselines", {}),
        }
    except Exception as error:  # A missing baseline must never suppress safety evaluation.
        baseline_snapshot = {"overall_status": "UNAVAILABLE", "error": type(error).__name__, "baselines": {}}
    return recent, context_snapshot, baseline_snapshot


async def _intervention_state(db: AsyncSession, event: RiskEvent | None):
    if event is None:
        return 0, None
    rows = (await db.execute(
        select(InterventionResult)
        .where(
            InterventionResult.event_id == event.event_id,
            InterventionResult.action_type != "family_feedback",
        )
        .order_by(InterventionResult.started_at)
    )).scalars().all()
    return len(rows), aware(rows[-1].started_at) if rows else None


async def _write_trace(
    db: AsyncSession,
    *,
    resident_id: str,
    evaluated_at,
    evidence_id: str | None,
    previous_state: str,
    previous_status: str | None,
    next_state: str,
    next_status: str | None,
    event: RiskEvent | None,
    event_created: bool,
    decision,
    recent: list[Evidence],
    context_snapshot: dict,
    baseline_snapshot: dict,
) -> dict:
    trace_id = f"trace-{uuid.uuid4().hex}"
    payload = {
        "trace_id": trace_id,
        "event_id": event.event_id if event else None,
        "resident_id": resident_id,
        "evidence_id": evidence_id,
        "evaluated_at": aware(evaluated_at).isoformat(),
        "ruleset_version": RULESET_VERSION,
        "matched_rule": decision.matched_rule,
        "previous_state": previous_state,
        "next_state": next_state,
        "previous_status": previous_status,
        "next_status": next_status,
        "event_created": event_created,
        "reason": decision.reason,
        "not_matched": decision.not_matched,
        "queried_windows": dict(ruleset.windows),
        "thresholds": dict(ruleset.thresholds),
        "quality_snapshot": quality_snapshot(recent, ruleset),
        "baseline_snapshot": baseline_snapshot,
        "context_snapshot": context_snapshot,
        "score_components": decision.score_components,
        "error": None,
    }
    db.add(RuleTrace(
        trace_id=trace_id,
        event_id=payload["event_id"],
        resident_id=resident_id,
        evidence_id=evidence_id,
        evaluated_at=evaluated_at,
        ruleset_version=RULESET_VERSION,
        matched_rule=decision.matched_rule,
        previous_state=previous_state,
        next_state=next_state,
        previous_status=previous_status,
        next_status=next_status,
        event_created=event_created,
        error=None,
        trace_payload=dumps(payload),
    ))
    await db.commit()
    return payload


async def evaluate(
    db: AsyncSession,
    resident_id: str,
    evaluated_at,
    evidence_id: str | None = None,
    *,
    duplicate: bool = False,
    system_evidence_id: str | None = None,
):
    existing = await _active_event(db, resident_id)
    previous_state = existing.risk_level if existing else "GREEN"
    previous_status = existing.status if existing else None
    trigger = None
    if evidence_id:
        trigger = (await db.execute(select(Evidence).where(
            Evidence.evidence_id == evidence_id
        ))).scalar_one_or_none()
    recent, context_snapshot, baseline_snapshot = await _context(db, resident_id, evaluated_at)
    attempts, latest_intervention_at = await _intervention_state(db, existing)

    if duplicate:
        from contracts.v1.decision import Decision
        decision = Decision(
            "R-SYSTEM-01", previous_state, previous_status, "NONE",
            "same evidence_id and payload is an idempotent replay",
        )
    else:
        decision = policy.evaluate(
            now=evaluated_at,
            previous_state=previous_state,
            active_status=previous_status,
            active_created_at=aware(existing.created_at) if existing else None,
            recovery_started_at=aware(existing.recovery_started_at) if existing and existing.recovery_started_at else None,
            recent=recent,
            trigger=trigger,
            context_score=context_snapshot["context_score"],
            intervention_attempts=attempts,
            latest_intervention_at=latest_intervention_at,
        )

    event = existing
    created = False
    if decision.action == "CREATE_EVENT":
        selected = [item for item in recent if item.evidence_id in decision.evidence_ids]
        selected.sort(key=lambda item: item.timestamp)
        event_id = "event-mock-fall-001" if resident_id == "resident-mock-001" else f"event-{uuid.uuid4().hex[:16]}"
        event = RiskEvent(
            schema_version="1.0", event_id=event_id, resident_id=resident_id,
            created_at=evaluated_at, updated_at=evaluated_at, primary_domain="FALL",
            related_domains=dumps([]), risk_level="ORANGE", risk_score=decision.score,
            evidence_ids=dumps([item.evidence_id for item in selected]),
            evidence_summary=dumps([{
                "evidence_id": item.evidence_id,
                "evidence_type": item.evidence_type,
                "explanation": item.explanation,
            } for item in selected]),
            time_horizon="IMMINENT", recommended_action="先坐稳，扶住固定物，再慢慢起身",
            intervention_policy="fall-orange-gentle-v1", status="INTERVENING",
            ruleset_version=RULESET_VERSION, source_mode=selected[-1].source_mode,
            simulated=any(item.simulated for item in selected), evidences=selected,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        created = True
    elif event is not None and decision.action == "BEGIN_OBSERVING":
        if trigger:
            await _attach_evidence(db, event, trigger)
        event.status = "OBSERVING"
        event.recovery_started_at = trigger.timestamp
        event.updated_at = trigger.timestamp
        await db.commit()
    elif event is not None and decision.action == "RESTART_INTERVENTION":
        hazard_id = decision.evidence_ids[0] if decision.evidence_ids else None
        hazard = next((item for item in recent if item.evidence_id == hazard_id), trigger)
        if hazard:
            await _attach_evidence(db, event, hazard)
            event.updated_at = hazard.timestamp
        event.status = "INTERVENING"
        event.recovery_started_at = None
        await db.commit()
    elif event is not None and decision.action == "RESOLVE":
        await _resolve_event(db, event, evaluated_at)
    elif event is not None and decision.action == "ESCALATE":
        hazard_id = decision.evidence_ids[0] if decision.evidence_ids else None
        hazard = next((item for item in recent if item.evidence_id == hazard_id), trigger)
        if hazard:
            await _attach_evidence(db, event, hazard)
            event.updated_at = hazard.timestamp
        event.risk_level = "RED"
        event.risk_score = max(event.risk_score, decision.score or ruleset.thresholds["red_score"])
        event.status = "ESCALATED"
        event.recommended_action = "通知家属并转人工接管，不自动拨打120"
        event.intervention_policy = "fall-red-human-handoff-v1"
        await db.commit()

    next_state = decision.risk_level
    next_status = event.status if event else decision.next_status
    trace = await _write_trace(
        db, resident_id=resident_id, evaluated_at=evaluated_at, evidence_id=evidence_id,
        previous_state=previous_state, previous_status=previous_status,
        next_state=next_state, next_status=next_status, event=event,
        event_created=created, decision=decision, recent=recent,
        context_snapshot=context_snapshot, baseline_snapshot=baseline_snapshot,
    )
    return {
        "risk_level": next_state,
        "previous_state": previous_state,
        "next_state": next_state,
        "previous_status": previous_status,
        "next_status": next_status,
        "event_created": created,
        "event": event_dict(event) if event else None,
        "matched_rule": decision.matched_rule,
        "ruleset_version": RULESET_VERSION,
        "system_evidence_id": system_evidence_id,
        "trace": trace,
    }
