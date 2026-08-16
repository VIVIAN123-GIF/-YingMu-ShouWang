"""Advance at most one due risk-state transition without wall-clock sleeps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import InterventionResult, RiskEvent
from backend.service.risk_service import evaluate, ruleset
from backend.service.serialization import aware


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _is_due(db: AsyncSession, event: RiskEvent, now: datetime) -> bool:
    comparable_now = aware(now)
    if event.status == "OBSERVING" and event.recovery_started_at:
        return comparable_now >= aware(event.recovery_started_at) + timedelta(
            seconds=ruleset.thresholds["observation_seconds"]
        )
    if event.status != "INTERVENING":
        return False
    rows = (await db.execute(
        select(InterventionResult)
        .where(
            InterventionResult.event_id == event.event_id,
            InterventionResult.delivery_status == "SUCCESS",
            InterventionResult.action_type != "family_feedback",
        )
        .order_by(InterventionResult.started_at.desc())
    )).scalars().all()
    delivery = next((item for item in rows if not item.resident_response), None)
    if delivery is None:
        return False
    delivered_at = aware(delivery.completed_at or delivery.started_at)
    if any(
        item.resident_response
        and item.resident_response.upper() in {"STABLE", "HELP"}
        and aware(item.started_at) >= delivered_at
        for item in rows
    ):
        return False
    return comparable_now >= delivered_at + timedelta(
        seconds=ruleset.thresholds["no_response_seconds"]
    )


async def advance_one_due_event(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict | None:
    current = now or utcnow_naive()
    events = (await db.execute(
        select(RiskEvent)
        .where(RiskEvent.status.in_(("INTERVENING", "OBSERVING")))
        .order_by(RiskEvent.updated_at)
    )).scalars().all()
    for event in events:
        if await _is_due(db, event, current):
            return await evaluate(db, event.resident_id, current)
    return None
