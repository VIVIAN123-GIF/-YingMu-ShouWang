import uuid
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import RULESET_VERSION
from backend.db.models import Evidence, InterventionResult, Observation, RiskEvent, RiskEventEvidence, RuleTrace
from backend.service.feedback_aggregation_service import aggregate_active_event_feedback
from backend.service.serialization import aware, dumps, event_dict, loads
from contracts.v1.decision import (
    FallDecisionPolicy,
    FraudDecisionPolicy,
    MentalDecisionPolicy,
    quality_snapshot,
)
from contracts.v1.ruleset import load_ruleset_version


ACTIVE_EVENT_STATUSES = ("OPEN", "INTERVENING", "OBSERVING")
FRAUD_VERIFICATION_WINDOW_SECONDS = 30 * 60
ruleset = load_ruleset_version(RULESET_VERSION)
policies = {
    "FALL": FallDecisionPolicy(ruleset),
    "MENTAL": MentalDecisionPolicy(ruleset),
    "FRAUD": FraudDecisionPolicy(ruleset),
}
policy = policies["FALL"]  # Backward-compatible import for existing integrations.
logger = logging.getLogger("backend.risk_service")

REVIEW_RULES = ("R-FALL-08", "R-FALL-09", "R-FALL-10", "R-FALL-11", "R-FALL-12", "R-FALL-13")


async def list_risk_reviews(
    db: AsyncSession,
    *,
    resident_id: str | None = None,
    limit: int = 20,
) -> list[dict]:
    query = (
        select(RuleTrace, Evidence)
        .join(Evidence, Evidence.evidence_id == RuleTrace.evidence_id)
        .where(
            RuleTrace.event_created.is_(False),
            RuleTrace.matched_rule.in_(REVIEW_RULES),
            RuleTrace.next_state.in_(("UNKNOWN", "YELLOW")),
        )
        .order_by(RuleTrace.evaluated_at.desc(), RuleTrace.id.desc())
        .limit(limit)
    )
    if resident_id:
        query = query.where(RuleTrace.resident_id == resident_id)
    rows = (await db.execute(query)).all()
    return [
        {
            "schema_version": "risk-review/1.0",
            "trace_id": trace.trace_id,
            "resident_id": trace.resident_id,
            "evidence_id": evidence.evidence_id,
            "evidence_type": evidence.evidence_type,
            "explanation": evidence.explanation,
            "evaluated_at": aware(trace.evaluated_at),
            "risk_level": trace.next_state,
            "matched_rule": trace.matched_rule,
            "ruleset_version": trace.ruleset_version,
            "source_mode": getattr(evidence.source_mode, "value", evidence.source_mode),
            "simulated": evidence.simulated,
            "review_required": True,
        }
        for trace, evidence in rows
    ]


async def _enqueue_explanation_safely(db: AsyncSession, event_id: str) -> None:
    try:
        from backend.service.agent_explanation_job_service import enqueue_event_explanation
        await enqueue_event_explanation(db, event_id)
    except Exception as exc:
        await db.rollback()
        logger.error(
            "agent_explanation_enqueue_failed event_id=%s error_code=%s",
            event_id,
            type(exc).__name__,
        )


async def _active_event(
    db: AsyncSession,
    resident_id: str,
    risk_domain: str = "FALL",
) -> RiskEvent | None:
    return (await db.execute(
        select(RiskEvent)
        .where(
            RiskEvent.resident_id == resident_id,
            RiskEvent.primary_domain == risk_domain,
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


async def _resolve_event(
    db: AsyncSession,
    event: RiskEvent,
    evaluated_at,
    *,
    status: str = "RESOLVED",
    risk_after: float | None = None,
) -> None:
    event.status = status
    event.risk_level = "GREEN"
    event.risk_score = 0.0
    event.updated_at = evaluated_at
    if event.primary_domain != "FALL":
        await db.commit()
        return
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
        result.risk_after = round(float(risk_after), 4) if risk_after is not None else 0.24
        result.resolved = True
        result.resolution_reason = "姿态恢复且60秒观察期内无新风险证据"
        result.completed_at = evaluated_at
    await db.commit()


async def _context(
    db: AsyncSession,
    resident_id: str,
    evaluated_at,
    risk_domain: str = "FALL",
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
    short_rows = [item for item in all_rows if aware(item.timestamp) >= aware(short_start)]
    if risk_domain == "MENTAL":
        recent = [item for item in all_rows if item.risk_domain == "MENTAL"]
    elif risk_domain == "FRAUD":
        fraud_start = evaluated_at - timedelta(seconds=FRAUD_VERIFICATION_WINDOW_SECONDS)
        recent = [
            item for item in all_rows
            if item.risk_domain == "FRAUD" and aware(item.timestamp) >= aware(fraud_start)
        ]
    else:
        recent = [item for item in short_rows if item.risk_domain == "FALL"]
    medium = [item for item in all_rows if aware(item.timestamp) >= aware(medium_start)]
    usable_fall = [
        item for item in recent
        if ruleset.usable(float(item.confidence), float(item.data_quality))
    ]
    usable_system = [
        item for item in short_rows
        if item.risk_domain == "SYSTEM"
        and ruleset.usable(float(item.confidence), float(item.data_quality))
    ] if usable_fall and risk_domain == "FALL" else []
    environment = [
        item for item in usable_system
        if item.evidence_type in {"high_risk_zone_entry", "obstacle_occupancy"}
    ]
    contributions = {
        "night": ruleset.context_factors["night"] if evaluated_at.hour >= 22 or evaluated_at.hour < 6 else 0.0,
        "low_light": ruleset.context_factors["low_light"] if any(
            item.evidence_type in {"low_illumination", "low_light"} for item in usable_system
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
        "high_risk_zone": ruleset.context_factors["high_risk_zone"] if any(
            item.evidence_type == "high_risk_zone_entry" for item in environment
        ) else 0.0,
        "obstacle_interaction": ruleset.context_factors["obstacle_interaction"] if any(
            item.evidence_type == "obstacle_occupancy" for item in environment
        ) else 0.0,
    }
    context_score = round(min(sum(contributions.values()), 1.0), 4)
    observation_ids = sorted({
        observation_id for item in environment for observation_id in loads(item.observation_ids, [])
    })
    observations = (await db.execute(
        select(Observation).where(Observation.observation_id.in_(observation_ids))
    )).scalars().all() if observation_ids else []
    scene_config_ids = sorted({
        metadata.get("scene_config_id")
        for observation in observations
        if (metadata := loads(observation.extra_metadata, {})).get("scene_config_id")
    })
    context_snapshot = {
        "policy_version": ruleset.context_policy_version,
        "evaluation_domain": risk_domain,
        "effective_evidence_window_seconds": (
            FRAUD_VERIFICATION_WINDOW_SECONDS if risk_domain == "FRAUD" else None
        ),
        "contributions": contributions,
        "context_score": context_score,
        "environment_evidence_ids": [item.evidence_id for item in environment],
        "scene_config_ids": scene_config_ids,
    }
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
            InterventionResult.action_type.notin_(("family_feedback", "resident_response")),
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
    risk_domain: str | None = None,
):
    trigger = None
    if evidence_id:
        trigger = (await db.execute(select(Evidence).where(
            Evidence.evidence_id == evidence_id
        ))).scalar_one_or_none()
    selected_domain = risk_domain or (trigger.risk_domain if trigger is not None else "FALL")
    selected_domain = getattr(selected_domain, "value", selected_domain)
    if selected_domain not in policies:
        selected_domain = "FALL"
    existing = await _active_event(db, resident_id, selected_domain)
    forewarning = None
    if selected_domain == "FALL" and not duplicate:
        from backend.service.forewarning_service import evaluate_forewarning
        forewarning = await evaluate_forewarning(
            db,
            resident_id,
            evaluated_at,
            phase="PERIODIC",
            event_id=existing.event_id if existing else None,
            source_mode=trigger.source_mode if trigger is not None else (
                existing.source_mode if existing is not None else None
            ),
            simulated=trigger.simulated if trigger is not None else (
                existing.simulated if existing is not None else None
            ),
        )
    previous_state = existing.risk_level if existing else "GREEN"
    previous_status = existing.status if existing else None
    if not duplicate and selected_domain == "FALL":
        await aggregate_active_event_feedback(db, existing, evaluated_at)
    recent, context_snapshot, baseline_snapshot = await _context(
        db, resident_id, evaluated_at, selected_domain
    )
    if forewarning is not None:
        context_snapshot["forewarning_snapshot"] = {
            "snapshot_id": forewarning.snapshot_id,
            "assessment_status": forewarning.assessment_status,
            "confidence_level": forewarning.confidence_level,
            "components": forewarning.components.model_dump(mode="json"),
            "instant_index": forewarning.instant.engineering_index,
            "short_30s_index": forewarning.short_30s.engineering_index,
            "trend_3min_index": forewarning.trend_3min.engineering_index,
        }
    attempts, latest_intervention_at = (
        await _intervention_state(db, existing)
        if selected_domain == "FALL"
        else (0, None)
    )

    if duplicate:
        from contracts.v1.decision import Decision
        decision = Decision(
            "R-SYSTEM-01", previous_state, previous_status, "NONE",
            "same evidence_id and payload is an idempotent replay",
        )
    else:
        decision = policies[selected_domain].evaluate(
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
        event_id = (
            "event-mock-fall-001"
            if selected_domain == "FALL" and resident_id == "resident-mock-001"
            else f"event-{uuid.uuid4().hex[:16]}"
        )
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
        if selected_domain == "MENTAL":
            event.primary_domain = "MENTAL"
            event.risk_level = decision.risk_level
            event.risk_score = float(decision.score or 0.0)
            event.time_horizon = "TREND"
            event.recommended_action = (
                "Review routine changes and arrange a non-clinical family check-in."
            )
            event.intervention_policy = "mental-trend-care-v1"
            event.status = decision.next_status
        elif selected_domain == "FRAUD":
            event.primary_domain = "FRAUD"
            event.risk_level = decision.risk_level
            event.risk_score = float(decision.score or 0.0)
            event.time_horizon = "TODAY"
            event.recommended_action = (
                "Verify visitor identity and transaction intent with an authorized contact."
            )
            event.intervention_policy = "fraud-human-verification-v1"
            event.status = decision.next_status
        db.add(event)
        await db.commit()
        await db.refresh(event)
        created = True
    elif event is not None and decision.action == "ATTACH_EVIDENCE":
        if trigger:
            await _attach_evidence(db, event, trigger)
            event.updated_at = trigger.timestamp
        event.risk_level = decision.risk_level
        event.risk_score = max(float(event.risk_score), float(decision.score or 0.0))
        await db.commit()
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
        if trigger:
            await _attach_evidence(db, event, trigger)
        intervention = (await db.execute(
            select(InterventionResult)
            .where(
                InterventionResult.event_id == event.event_id,
                InterventionResult.delivery_status == "SUCCESS",
                InterventionResult.action_type != "family_feedback",
            )
            .order_by(InterventionResult.started_at.desc())
        )).scalars().first()
        from backend.service.forewarning_service import evaluate_forewarning
        forewarning = await evaluate_forewarning(
            db,
            resident_id,
            evaluated_at,
            phase="POST_INTERVENTION",
            event_id=event.event_id,
            intervention_result_id=intervention.result_id if intervention else None,
            source_mode=event.source_mode,
            simulated=event.simulated,
        )
        await _resolve_event(
            db, event, evaluated_at, status=decision.next_status or "RESOLVED",
            risk_after=None if event.source_mode == "MOCK" else max(
                forewarning.instant.engineering_index,
                forewarning.short_30s.engineering_index,
                forewarning.trend_3min.engineering_index,
            ) if forewarning is not None else None,
        )
    elif event is not None and decision.action == "UPGRADE_EVENT":
        for evidence in recent:
            if evidence.evidence_id in decision.evidence_ids:
                await _attach_evidence(db, event, evidence)
        event.risk_level = decision.risk_level
        event.risk_score = max(float(event.risk_score), float(decision.score or 0.0))
        event.status = decision.next_status
        event.updated_at = evaluated_at
        await db.commit()
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

    if event is not None and forewarning is not None:
        from backend.service.forewarning_service import link_snapshot_closure
        intervention = (await db.execute(
            select(InterventionResult)
            .where(InterventionResult.event_id == event.event_id)
            .order_by(InterventionResult.started_at.desc())
        )).scalars().first()
        phase = "PRE_INTERVENTION" if created else forewarning.phase
        linked = await link_snapshot_closure(
            db,
            forewarning.snapshot_id,
            event.event_id,
            phase=phase,
            intervention_result_id=intervention.result_id if intervention and phase == "POST_INTERVENTION" else None,
        )
        forewarning = linked or forewarning

    next_state = decision.risk_level
    next_status = event.status if event else decision.next_status
    trace = await _write_trace(
        db, resident_id=resident_id, evaluated_at=evaluated_at, evidence_id=evidence_id,
        previous_state=previous_state, previous_status=previous_status,
        next_state=next_state, next_status=next_status, event=event,
        event_created=created, decision=decision, recent=recent,
        context_snapshot=context_snapshot, baseline_snapshot=baseline_snapshot,
    )
    event_payload = event_dict(event) if event else None
    if event is not None and (created or decision.action in {"ESCALATE", "RESOLVE"}):
        await _enqueue_explanation_safely(db, event.event_id)
    return {
        "risk_level": next_state,
        "previous_state": previous_state,
        "next_state": next_state,
        "previous_status": previous_status,
        "next_status": next_status,
        "event_created": created,
        "event": event_payload,
        "matched_rule": decision.matched_rule,
        "ruleset_version": RULESET_VERSION,
        "system_evidence_id": system_evidence_id,
        "forewarning_snapshot": forewarning.model_dump(mode="json") if forewarning else None,
        "trace": trace,
    }
