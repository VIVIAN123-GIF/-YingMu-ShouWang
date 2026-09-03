"""Read-only projection for comparing genuine live-device runs."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    AlarmProcessingTask,
    Asset,
    Evidence,
    ForewarningSnapshot as SnapshotRow,
    InterventionResult,
    Observation,
    RiskEvent,
    RiskEventEvidence,
    RuleTrace,
)
from backend.service.alarm_task_service import task_dict
from backend.service.forewarning_service import contract_from_row
from backend.service.serialization import (
    aware,
    event_dict,
    evidence_dict,
    intervention_dict,
    loads,
    observation_dict,
)


RISK_ORDER = {"UNKNOWN": 0, "GREEN": 1, "YELLOW": 2, "ORANGE": 3, "RED": 4}
METRIC_FEATURES = {
    "rapid_rise": {"rise_duration_s", "sit_to_stand_duration"},
    "trunk_sway": {"trunk_sway_angle", "trunk_sway_angle_deg", "trunk_sway_ratio"},
}


def _opaque_ref(prefix: str, value: str | None) -> str:
    if not value:
        return f"{prefix}-unavailable"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _metric(
    metric_name: str,
    observations: list[Observation],
    evidences: list[Evidence],
) -> dict[str, Any]:
    evidence = next(
        (item for item in reversed(evidences) if item.evidence_type == metric_name),
        None,
    )
    linked_ids = set(loads(evidence.observation_ids, [])) if evidence else set()
    observation = next(
        (
            item
            for item in reversed(observations)
            if item.observation_id in linked_ids
            or item.feature_name in METRIC_FEATURES[metric_name]
        ),
        None,
    )
    raw_value = loads(observation.feature_value, observation.feature_value) if observation else None
    return {
        "detected": evidence is not None,
        "value": evidence.current_value if evidence and evidence.current_value is not None else raw_value,
        "unit": observation.unit if observation else None,
        "data_quality": (
            float(evidence.data_quality)
            if evidence is not None
            else float(observation.data_quality) if observation is not None else None
        ),
        "evidence_id": evidence.evidence_id if evidence else None,
        "observation_id": observation.observation_id if observation else None,
    }


def _snapshot_score(snapshot) -> float:
    return max(
        snapshot.instant.engineering_index,
        snapshot.short_30s.engineering_index,
        snapshot.trend_3min.engineering_index,
    )


def _snapshot_level(snapshot) -> str:
    horizons = (snapshot.instant, snapshot.short_30s, snapshot.trend_3min)
    return max(horizons, key=lambda item: item.engineering_index).attention_level


def _peak_level(event: RiskEvent | None, traces: list[dict[str, Any]], snapshots: list) -> str:
    levels = [
        _enum_value(event.risk_level) if event is not None else "UNKNOWN",
        *[str(item.get("next_state") or "UNKNOWN") for item in traces],
        *[_snapshot_level(item) for item in snapshots],
    ]
    return max(levels, key=lambda item: RISK_ORDER.get(item, 0))


async def _run_projection(
    db: AsyncSession,
    task: AlarmProcessingTask,
    asset: Asset,
) -> dict[str, Any]:
    observations = (await db.execute(
        select(Observation)
        .where(
            Observation.asset_id == asset.asset_id,
            Observation.source_mode == "LIVE_DEVICE",
            Observation.simulated.is_(False),
        )
        .order_by(Observation.timestamp, Observation.id)
    )).scalars().all()
    observation_ids = {item.observation_id for item in observations}

    evidence_candidates = (await db.execute(
        select(Evidence).where(
            Evidence.resident_id == task.resident_id,
            Evidence.source_mode == "LIVE_DEVICE",
            Evidence.simulated.is_(False),
        ).order_by(Evidence.timestamp, Evidence.id)
    )).scalars().all()
    evidences = [
        item
        for item in evidence_candidates
        if observation_ids.intersection(loads(item.observation_ids, []))
    ]
    evidence_ids = {item.evidence_id for item in evidences}

    summary = loads(task.algorithm_summary, {})
    snapshot_id = summary.get("forewarning_snapshot_id") if isinstance(summary, dict) else None
    run_snapshot = (await db.execute(
        select(SnapshotRow).where(SnapshotRow.snapshot_id == snapshot_id)
    )).scalar_one_or_none() if snapshot_id else None

    linked_event_ids: set[str] = set()
    if evidence_ids:
        links = (await db.execute(
            select(RiskEventEvidence).where(RiskEventEvidence.evidence_id.in_(evidence_ids))
        )).scalars().all()
        linked_event_ids.update(item.event_id for item in links)
    if run_snapshot is not None and run_snapshot.event_id:
        linked_event_ids.add(run_snapshot.event_id)

    event = None
    if linked_event_ids:
        event = (await db.execute(
            select(RiskEvent)
            .where(
                RiskEvent.event_id.in_(linked_event_ids),
                RiskEvent.resident_id == task.resident_id,
                RiskEvent.source_mode == "LIVE_DEVICE",
                RiskEvent.simulated.is_(False),
            )
            .order_by(RiskEvent.created_at.desc(), RiskEvent.id.desc())
        )).scalars().first()

    snapshot_scope = SnapshotRow.snapshot_id == snapshot_id if snapshot_id else None
    if event is not None:
        snapshot_scope = SnapshotRow.event_id == event.event_id
        if snapshot_id:
            snapshot_scope = or_(snapshot_scope, SnapshotRow.snapshot_id == snapshot_id)
    snapshot_query = select(SnapshotRow).where(
        snapshot_scope,
        SnapshotRow.resident_id == task.resident_id,
        SnapshotRow.source_mode == "LIVE_DEVICE",
        SnapshotRow.simulated.is_(False),
    ) if snapshot_scope is not None else None
    snapshot_rows = (await db.execute(
        snapshot_query.order_by(SnapshotRow.evaluated_at, SnapshotRow.id)
    )).scalars().all() if snapshot_query is not None else []
    snapshots = [contract_from_row(item) for item in snapshot_rows]

    trace_rows: list[RuleTrace] = []
    intervention_rows: list[InterventionResult] = []
    if event is not None:
        trace_rows = (await db.execute(
            select(RuleTrace)
            .where(
                RuleTrace.event_id == event.event_id,
                RuleTrace.resident_id == task.resident_id,
            )
            .order_by(RuleTrace.evaluated_at, RuleTrace.id)
        )).scalars().all()
        intervention_rows = (await db.execute(
            select(InterventionResult)
            .where(
                InterventionResult.event_id == event.event_id,
                InterventionResult.source_mode == "LIVE_DEVICE",
                InterventionResult.simulated.is_(False),
            )
            .order_by(InterventionResult.started_at, InterventionResult.id)
        )).scalars().all()
    elif evidence_ids:
        trace_rows = (await db.execute(
            select(RuleTrace)
            .where(
                RuleTrace.evidence_id.in_(evidence_ids),
                RuleTrace.resident_id == task.resident_id,
            )
            .order_by(RuleTrace.evaluated_at, RuleTrace.id)
        )).scalars().all()

    traces = [
        loads(row.trace_payload, None)
        or {
            "trace_id": row.trace_id,
            "event_id": row.event_id,
            "evidence_id": row.evidence_id,
            "evaluated_at": aware(row.evaluated_at).isoformat(),
            "ruleset_version": row.ruleset_version,
            "matched_rule": row.matched_rule,
            "previous_state": row.previous_state,
            "next_state": row.next_state,
            "previous_status": row.previous_status,
            "next_status": row.next_status,
            "event_created": row.event_created,
            "error": row.error,
        }
        for row in trace_rows
    ]
    peak_score = max(
        [float(event.risk_score) if event is not None else 0.0]
        + [_snapshot_score(item) for item in snapshots]
    )
    current_snapshot = snapshots[-1] if snapshots else None
    current_level = (
        _enum_value(event.risk_level)
        if event is not None
        else _snapshot_level(current_snapshot) if current_snapshot is not None else "UNKNOWN"
    )
    current_score = (
        float(event.risk_score)
        if event is not None
        else _snapshot_score(current_snapshot) if current_snapshot is not None else 0.0
    )
    qualities = [float(item.data_quality) for item in observations] or [
        float(item.data_quality) for item in evidences
    ]
    scene_id = current_snapshot.scene_config_id if current_snapshot is not None else next(
        (
            metadata.get("scene_config_id")
            for item in reversed(observations)
            if (metadata := loads(item.extra_metadata, {})).get("scene_config_id")
        ),
        None,
    )
    public_task = task_dict(task)
    return {
        "schema_version": "field-run/1.0",
        "run_id": task.task_id,
        "resident_id": task.resident_id,
        "captured_at": aware(asset.captured_at),
        "source_mode": "LIVE_DEVICE",
        "simulated": False,
        "device_ref": _opaque_ref("device", asset.device_ref or task.device_sn),
        "device_model": asset.device_model,
        "camera_position_id": asset.camera_position_id,
        "authorization_ref": _opaque_ref("authorization", asset.authorization_record_id),
        "scene_config_id": scene_id,
        "task_status": task.status,
        "task_result": public_task,
        "risk_level": _peak_level(event, traces, snapshots),
        "risk_score": round(min(max(peak_score, 0.0), 1.0), 4),
        "current_risk_level": current_level,
        "current_risk_score": round(min(max(current_score, 0.0), 1.0), 4),
        "data_quality": min(qualities) if qualities else None,
        "metrics": {
            name: _metric(name, observations, evidences)
            for name in ("rapid_rise", "trunk_sway")
        },
        "event": (
            {
                "event_id": event.event_id,
                "risk_level": _enum_value(event.risk_level),
                "risk_score": event.risk_score,
                "status": _enum_value(event.status),
                "recommended_action": event.recommended_action,
                "ruleset_version": event.ruleset_version,
            }
            if event is not None
            else None
        ),
        "evidences": [evidence_dict(item) for item in evidences],
        "observations": [observation_dict(item) for item in observations],
        "rule_traces": traces,
        "interventions": [intervention_dict(item) for item in intervention_rows],
        "forewarning_snapshots": snapshots,
    }


async def list_live_field_runs(
    db: AsyncSession,
    resident_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(AlarmProcessingTask, Asset)
        .join(Asset, Asset.asset_id == AlarmProcessingTask.capture_asset_id)
        .where(
            AlarmProcessingTask.resident_id == resident_id,
            Asset.source_mode == "LIVE_DEVICE",
            Asset.simulated.is_(False),
            Asset.device_model == "EZVIZ_C6C",
            Asset.camera_position_id.is_not(None),
            Asset.authorization_status == "AUTHORIZED",
            Asset.authorization_record_id.is_not(None),
        )
        .order_by(AlarmProcessingTask.create_time.desc(), AlarmProcessingTask.id.desc())
        .limit(limit)
    )).all()
    return [await _run_projection(db, task, asset) for task, asset in rows]
