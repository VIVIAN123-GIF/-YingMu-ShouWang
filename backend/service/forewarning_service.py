"""Persistent, auditable v1.3-min engineering forewarning evaluation."""

from __future__ import annotations

import hashlib
import statistics
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Evidence, ForewarningSnapshot as SnapshotRow, Observation
from backend.service.baseline_service import memory_store
from backend.service.serialization import aware, dumps, loads
from contracts.v1.forewarning import (
    ForewarningComponents,
    ForewarningFactor,
    ForewarningHorizon,
    ForewarningSnapshot,
)
from contracts.v1.ruleset import load_forewarning_ruleset


RULESET = load_forewarning_ruleset()
HUMAN_TYPES = {
    "rapid_rise", "slow_rise", "trunk_sway", "gait_instability",
    "relative_speed_change", "post_rise_lateral_drift", "support_base_change",
    "compensatory_step", "sit_to_stand_transition", "persistent_instability",
}
PRECURSOR_TYPES = HUMAN_TYPES - {"sit_to_stand_transition"}
QUALITY_TYPES = {"assessment_indeterminate", "tracking_lost", "camera_occlusion", "quality_gate_failed"}
ENVIRONMENT_TYPES = {"low_illumination", "low_light"}
INTERACTION_FEATURES = {
    "danger_zone_dwell_s", "trajectory_intersects_obstacle", "support_zone_distance_norm",
}
FEATURE_TO_BASELINE = {
    "rise_duration_s": "rise_duration",
    "sit_to_stand_duration": "rise_duration",
    "trunk_sway_angle_deg": "trunk_sway",
    "trunk_sway_angle": "trunk_sway",
    "step_speed_norm_s": "relative_gait_speed",
    "relative_gait_speed": "relative_gait_speed",
    "post_rise_pelvis_lateral_excursion_norm": "pelvis_lateral_excursion",
    "post_rise_support_width_change_norm": "support_width_change",
    "step_asymmetry_ratio": "step_asymmetry",
    "turn_angular_velocity_deg_s": "turn_angular_velocity",
}


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _clamp(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _stable_id(
    resident_id: str,
    evaluated_at,
    source_mode: str,
    simulated: bool,
    evidence_ids: list[str],
    observation_ids: list[str],
) -> str:
    identities = evidence_ids or observation_ids
    payload = "|".join([
        resident_id,
        aware(evaluated_at).isoformat(),
        source_mode,
        str(simulated),
        *sorted(identities),
    ])
    return "forewarning-" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


async def _resolve_source_cohort(
    db: AsyncSession,
    resident_id: str,
    evaluated_at,
    source_mode: Any | None,
    simulated: bool | None,
) -> tuple[str, bool]:
    resolved_mode = _enum_value(source_mode) if source_mode is not None else None
    if resolved_mode is not None and simulated is not None:
        return resolved_mode, bool(simulated)

    evidence_filters = [
        Evidence.resident_id == resident_id,
        Evidence.timestamp <= evaluated_at,
    ]
    if resolved_mode is not None:
        evidence_filters.append(Evidence.source_mode == resolved_mode)
    if simulated is not None:
        evidence_filters.append(Evidence.simulated.is_(bool(simulated)))
    anchor = (await db.execute(
        select(Evidence)
        .where(*evidence_filters)
        .order_by(Evidence.timestamp.desc(), Evidence.id.desc())
    )).scalars().first()

    if anchor is None:
        observation_filters = [
            Observation.resident_id == resident_id,
            Observation.timestamp <= evaluated_at,
        ]
        if resolved_mode is not None:
            observation_filters.append(Observation.source_mode == resolved_mode)
        if simulated is not None:
            observation_filters.append(Observation.simulated.is_(bool(simulated)))
        anchor = (await db.execute(
            select(Observation)
            .where(*observation_filters)
            .order_by(Observation.timestamp.desc(), Observation.id.desc())
        )).scalars().first()

    if resolved_mode is None:
        resolved_mode = _enum_value(anchor.source_mode) if anchor is not None else "MOCK"
    if simulated is None:
        simulated = bool(anchor.simulated) if anchor is not None else True
    return resolved_mode, bool(simulated)


def _mad_deviation(current: float, center: float, mad: float) -> float:
    scale = max(1.4826 * mad, abs(center) * 0.1, 1e-6)
    return _clamp(abs(current - center) / scale)


def _attention(index: float, status: str) -> str:
    if status == "INSUFFICIENT":
        return "UNKNOWN"
    if index >= 0.7:
        return "ORANGE"
    if index >= 0.4:
        return "YELLOW"
    return "GREEN"


def _recommended(index: float, status: str, reasons: list[str]) -> str:
    if status == "INSUFFICIENT":
        return "数据不足，先改善机位、补光或完成一次合格观测，再进行人工复核。"
    if reasons:
        return "当前为降级工程观察，保持低打扰监测并等待第二条独立证据。"
    if index >= 0.7:
        return "执行低打扰提醒并进入恢复观察；是否创建事件仍由确定性规则裁决。"
    if index >= 0.4:
        return "保持观察，等待第二条独立人体或人-环境交互证据。"
    return "记录为当前工程观察范围内波动，不主动打扰。"


def _snapshot_dict(row: SnapshotRow) -> dict[str, Any]:
    components = loads(row.components_payload, {})
    factors = loads(row.factors_payload, [])
    degradation = loads(row.degradation_payload, [])
    status = row.assessment_status
    return {
        "schema_version": "forewarning-snapshot/1.0",
        "snapshot_id": row.snapshot_id,
        "resident_id": row.resident_id,
        "evaluated_at": aware(row.evaluated_at),
        "phase": row.phase,
        "assessment_status": status,
        "confidence_level": row.confidence_level,
        "baseline_status": row.baseline_status,
        "components": components,
        "instant": {"window_seconds": int(RULESET.windows["instant_seconds"]), "engineering_index": row.instant_index, "attention_level": _attention(row.instant_index, status)},
        "short_30s": {"window_seconds": 30, "engineering_index": row.short_30s_index, "attention_level": _attention(row.short_30s_index, status)},
        "trend_3min": {"window_seconds": 180, "engineering_index": row.trend_3min_index, "attention_level": _attention(row.trend_3min_index, status)},
        "dominant_factors": factors,
        "degradation_reasons": degradation,
        "evidence_ids": loads(row.evidence_ids, []),
        "observation_ids": loads(row.observation_ids, []),
        "scene_config_id": row.scene_config_id,
        "event_id": row.event_id,
        "intervention_result_id": row.intervention_result_id,
        "recommended_action": row.recommended_action,
        "ruleset_version": row.ruleset_version,
        "source_mode": row.source_mode,
        "simulated": row.simulated,
    }


def contract_from_row(row: SnapshotRow) -> ForewarningSnapshot:
    return ForewarningSnapshot.model_validate(_snapshot_dict(row))


def legacy_pre_fall_summary(snapshot: ForewarningSnapshot) -> dict[str, Any]:
    level = max(
        (snapshot.instant, snapshot.short_30s, snapshot.trend_3min),
        key=lambda item: item.engineering_index,
    ).attention_level
    risk_level = level
    factor_map = {
        "human_instability": "fall_precursor_evidence",
        "personal_baseline_deviation": "personal_baseline_deviation",
        "environment_context": "environment_interaction_risk",
        "human_environment_interaction": "environment_interaction_risk",
        "data_quality_downgrade": "data_quality_downgrade",
    }
    factors = []
    for item in snapshot.dominant_factors:
        mapped = factor_map[item.factor]
        if mapped not in factors:
            factors.append(mapped)
    if not factors:
        factors = ["data_quality_downgrade"] if snapshot.assessment_status == "INSUFFICIENT" else ["normal_fluctuation"]
    delta = snapshot.trend_3min.engineering_index - snapshot.instant.engineering_index
    return {
        "as_of": snapshot.evaluated_at.isoformat(),
        "risk_level": risk_level,
        "assessment_status": snapshot.assessment_status,
        "confidence_level": snapshot.confidence_level,
        "baseline_status": snapshot.baseline_status,
        "snapshot_id": snapshot.snapshot_id,
        "instant_risk": snapshot.instant.engineering_index,
        "risk_30s": snapshot.short_30s.engineering_index,
        "trend_3min": snapshot.trend_3min.engineering_index,
        "trend_direction": "RISING" if delta >= 0.08 else "FALLING" if delta <= -0.08 else "STABLE",
        "human_risk": snapshot.components.human_risk,
        "personal_deviation": snapshot.components.personal_deviation or 0.0,
        "environment_risk": snapshot.components.environment_risk,
        "interaction_risk": snapshot.components.interaction_risk,
        "quality_penalty": 1.0 if snapshot.assessment_status == "INSUFFICIENT" else 0.0,
        "dominant_factors": factors,
        "degradation_reasons": snapshot.degradation_reasons,
        "evidence_ids": snapshot.evidence_ids,
        "recommended_intervention": snapshot.recommended_action,
        "metric_semantics": "ENGINEERING_INDEX_NOT_PROBABILITY",
    }


async def evaluate_forewarning(
    db: AsyncSession,
    resident_id: str,
    evaluated_at,
    *,
    phase: str = "PERIODIC",
    event_id: str | None = None,
    intervention_result_id: str | None = None,
    source_mode: Any | None = None,
    simulated: bool | None = None,
    asset_id: str | None = None,
) -> ForewarningSnapshot:
    evaluated_at = aware(evaluated_at)
    source_mode, simulated = await _resolve_source_cohort(
        db, resident_id, evaluated_at, source_mode, simulated,
    )
    trend_start = evaluated_at - timedelta(seconds=int(RULESET.windows["trend_seconds"]))
    evidences = (await db.execute(
        select(Evidence).where(
            Evidence.resident_id == resident_id,
            Evidence.timestamp >= trend_start,
            Evidence.timestamp <= evaluated_at,
            Evidence.source_mode == source_mode,
            Evidence.simulated.is_(simulated),
        ).order_by(Evidence.timestamp)
    )).scalars().all()
    evidence_ids = [item.evidence_id for item in evidences]
    linked_ids = {
        observation_id
        for evidence in evidences
        for observation_id in loads(evidence.observation_ids, [])
    }
    observations = (await db.execute(
        select(Observation).where(
            Observation.observation_id.in_(linked_ids),
            Observation.source_mode == source_mode,
            Observation.simulated.is_(simulated),
        )
    )).scalars().all() if linked_ids else []
    if not observations:
        observation_filters = [
            Observation.resident_id == resident_id,
            Observation.timestamp >= trend_start,
            Observation.timestamp <= evaluated_at,
            Observation.source_mode == source_mode,
            Observation.simulated.is_(simulated),
        ]
        if asset_id is not None:
            observation_filters.append(Observation.asset_id == asset_id)
        observations = (await db.execute(
            select(Observation).where(*observation_filters).order_by(Observation.timestamp)
        )).scalars().all()

    instant_start = evaluated_at - timedelta(seconds=int(RULESET.windows["instant_seconds"]))
    short_start = evaluated_at - timedelta(seconds=30)
    usable = [
        item for item in evidences
        if RULESET.usable(float(item.confidence), float(item.data_quality))
    ]
    human = [item for item in usable if _enum_value(item.risk_domain) == "FALL" and item.evidence_type in HUMAN_TYPES]
    instant_human = [item for item in human if aware(item.timestamp) >= instant_start]
    short_human = [item for item in human if aware(item.timestamp) >= short_start]
    precursors = [item for item in instant_human if item.evidence_type in PRECURSOR_TYPES]
    human_risk = max((float(item.severity) for item in precursors), default=0.0)
    signal_types = {item.evidence_type for item in precursors}
    if len(signal_types) >= 2:
        human_risk = _clamp(human_risk + 0.12)

    instant_usable = [item for item in usable if aware(item.timestamp) >= instant_start]
    environment = [item for item in instant_usable if item.evidence_type in ENVIRONMENT_TYPES]
    environment_risk = max((float(item.severity) for item in environment), default=0.0)
    interaction_observations = [
        item for item in observations
        if item.feature_name in INTERACTION_FEATURES and aware(item.timestamp) >= instant_start
    ]
    interaction_evidence = [
        item for item in instant_usable
        if item.evidence_type == "high_risk_zone_entry"
        and set(loads(item.observation_ids, [])) & {row.observation_id for row in interaction_observations}
    ]
    interaction_risk = max((float(item.severity) for item in interaction_evidence), default=0.0) if precursors else 0.0

    baseline = await memory_store.baseline(db, resident_id, evaluated_at)
    baseline_status = baseline["overall_status"]
    current_by_metric: dict[str, float] = {}
    for observation in observations:
        metric = FEATURE_TO_BASELINE.get(observation.feature_name)
        value = loads(observation.feature_value, observation.feature_value)
        if metric and isinstance(value, (int, float)) and not isinstance(value, bool):
            current_by_metric[metric] = float(value)
    deviations: list[float] = []
    if baseline_status != "INSUFFICIENT":
        for metric, current in current_by_metric.items():
            stats = baseline["baselines"].get(metric)
            if not stats or stats["median"] is None:
                continue
            center = float(stats["median"])
            mad = float(stats["mad"] or 0.0)
            deviations.append(_mad_deviation(current, center, mad))
    personal = max(deviations, default=None)

    reasons: list[str] = []
    quality_evidence = [item for item in evidences if item.evidence_type in QUALITY_TYPES and aware(item.timestamp) >= short_start]
    if quality_evidence:
        reasons.append("QUALITY_GATE_FAILED")
    scene_ids = sorted({
        metadata.get("scene_config_id")
        for item in observations
        if (metadata := loads(item.extra_metadata, {})).get("scene_config_id")
        and item.source == "trajectory_adapter"
    })
    if not scene_ids:
        reasons.append("SCENE_CONTEXT_MISSING")
    if baseline_status == "INSUFFICIENT":
        reasons.append("PERSONAL_BASELINE_INSUFFICIENT")
    if not human:
        reasons.append("HUMAN_EVIDENCE_INSUFFICIENT")

    assessment_status = "INSUFFICIENT" if quality_evidence or not human else ("PARTIAL" if reasons else "VALID")
    weights = (RULESET.forewarning_weights or {})[baseline_status]
    components = {
        "human_risk": _clamp(human_risk),
        "personal_deviation": personal,
        "environment_risk": _clamp(environment_risk),
        "interaction_risk": _clamp(interaction_risk),
    }
    instant_index = _clamp(sum(weights[name] * float(value or 0.0) for name, value in components.items()))
    recent_peak = max((float(item.severity) for item in short_human if item.evidence_type in PRECURSOR_TYPES), default=0.0)
    short_index = _clamp(0.7 * instant_index + 0.3 * recent_peak)
    trend_values = [float(item.severity) for item in human if item.evidence_type in PRECURSOR_TYPES]
    trend_mean = statistics.fmean(trend_values) if trend_values else 0.0
    recurrence = min(len(trend_values) / 4.0, 1.0)
    trend_index = _clamp(0.5 * short_index + 0.3 * trend_mean + 0.2 * recurrence)

    factor_specs = [
        ("human_instability", weights["human_risk"] * components["human_risk"], [item.evidence_id for item in precursors]),
        ("personal_baseline_deviation", weights["personal_deviation"] * float(personal or 0.0), []),
        ("environment_context", weights["environment_risk"] * components["environment_risk"], [item.evidence_id for item in environment]),
        ("human_environment_interaction", weights["interaction_risk"] * components["interaction_risk"], [item.evidence_id for item in interaction_evidence] if precursors else []),
    ]
    factors = [
        ForewarningFactor(factor=name, contribution=round(_clamp(contribution), 4), evidence_ids=ids)
        for name, contribution, ids in factor_specs if contribution > 0
    ]
    if reasons:
        factors.append(ForewarningFactor(factor="data_quality_downgrade", contribution=0.0, evidence_ids=[item.evidence_id for item in quality_evidence]))
    factors.sort(key=lambda item: item.contribution, reverse=True)

    qualities = [float(item.data_quality) for item in usable]
    confidence_level = "LOW" if assessment_status == "INSUFFICIENT" else (
        "HIGH" if qualities and min(qualities) >= 0.85 and baseline_status == "STABLE" and scene_ids else "MEDIUM"
    )
    observation_ids = [item.observation_id for item in observations]
    snapshot_id = _stable_id(
        resident_id,
        evaluated_at,
        source_mode,
        simulated,
        evidence_ids,
        observation_ids,
    )
    recommended = _recommended(max(instant_index, short_index, trend_index), assessment_status, reasons)
    contract = ForewarningSnapshot(
        schema_version="forewarning-snapshot/1.0", snapshot_id=snapshot_id,
        resident_id=resident_id, evaluated_at=evaluated_at, phase=phase,
        assessment_status=assessment_status, confidence_level=confidence_level,
        baseline_status=baseline_status, components=ForewarningComponents(**components),
        instant=ForewarningHorizon(window_seconds=int(RULESET.windows["instant_seconds"]), engineering_index=round(instant_index, 4), attention_level=_attention(instant_index, assessment_status)),
        short_30s=ForewarningHorizon(window_seconds=30, engineering_index=round(short_index, 4), attention_level=_attention(short_index, assessment_status)),
        trend_3min=ForewarningHorizon(window_seconds=180, engineering_index=round(trend_index, 4), attention_level=_attention(trend_index, assessment_status)),
        dominant_factors=factors[:5], degradation_reasons=sorted(set(reasons)),
        evidence_ids=evidence_ids, observation_ids=observation_ids,
        scene_config_id=scene_ids[-1] if scene_ids else None, event_id=event_id,
        intervention_result_id=intervention_result_id, recommended_action=recommended,
        ruleset_version=RULESET.version, source_mode=source_mode, simulated=simulated,
    )
    existing = (await db.execute(
        select(SnapshotRow).where(SnapshotRow.snapshot_id == snapshot_id)
    )).scalar_one_or_none()
    payload = contract.model_dump(mode="json")
    if existing is None:
        existing = SnapshotRow(snapshot_id=snapshot_id, resident_id=resident_id, evaluated_at=evaluated_at)
        db.add(existing)
    existing.phase = phase
    existing.assessment_status = assessment_status
    existing.confidence_level = confidence_level
    existing.baseline_status = baseline_status
    existing.instant_index = instant_index
    existing.short_30s_index = short_index
    existing.trend_3min_index = trend_index
    existing.components_payload = dumps(payload["components"])
    existing.factors_payload = dumps(payload["dominant_factors"])
    existing.degradation_payload = dumps(payload["degradation_reasons"])
    existing.evidence_ids = dumps(evidence_ids)
    existing.observation_ids = dumps(payload["observation_ids"])
    existing.scene_config_id = contract.scene_config_id
    existing.event_id = event_id
    existing.intervention_result_id = intervention_result_id
    existing.recommended_action = recommended
    existing.ruleset_version = RULESET.version
    existing.source_mode = source_mode
    existing.simulated = simulated
    await db.flush()
    return contract


async def latest_forewarning(db: AsyncSession, resident_id: str) -> ForewarningSnapshot | None:
    row = (await db.execute(
        select(SnapshotRow).where(SnapshotRow.resident_id == resident_id).order_by(SnapshotRow.evaluated_at.desc(), SnapshotRow.id.desc())
    )).scalars().first()
    return contract_from_row(row) if row else None


async def list_forewarning(
    db: AsyncSession, resident_id: str, *, from_time=None, to_time=None, limit: int = 100,
) -> list[ForewarningSnapshot]:
    query = select(SnapshotRow).where(SnapshotRow.resident_id == resident_id)
    if from_time is not None:
        query = query.where(SnapshotRow.evaluated_at >= aware(from_time))
    if to_time is not None:
        query = query.where(SnapshotRow.evaluated_at <= aware(to_time))
    rows = (await db.execute(query.order_by(SnapshotRow.evaluated_at.desc()).limit(limit))).scalars().all()
    return [contract_from_row(row) for row in rows]


async def event_forewarning(db: AsyncSession, event_id: str) -> list[ForewarningSnapshot]:
    rows = (await db.execute(
        select(SnapshotRow).where(SnapshotRow.event_id == event_id).order_by(SnapshotRow.evaluated_at)
    )).scalars().all()
    return [contract_from_row(row) for row in rows]


async def link_snapshot_event(db: AsyncSession, snapshot_id: str, event_id: str, phase: str = "PRE_INTERVENTION") -> None:
    row = (await db.execute(select(SnapshotRow).where(SnapshotRow.snapshot_id == snapshot_id))).scalar_one_or_none()
    if row:
        row.event_id = event_id
        row.phase = phase
        await db.flush()


async def link_snapshot_closure(
    db: AsyncSession,
    snapshot_id: str,
    event_id: str,
    *,
    phase: str,
    intervention_result_id: str | None = None,
) -> ForewarningSnapshot | None:
    row = (await db.execute(select(SnapshotRow).where(SnapshotRow.snapshot_id == snapshot_id))).scalar_one_or_none()
    if row is None:
        return None
    row.event_id = event_id
    row.phase = phase
    row.intervention_result_id = intervention_result_id
    await db.flush()
    return contract_from_row(row)
