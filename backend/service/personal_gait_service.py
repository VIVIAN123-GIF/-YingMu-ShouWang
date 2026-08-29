"""Create baseline-aware gait trend Evidence after raw observations are durable."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import RULESET_VERSION
from backend.db.models import Observation as ObservationRow
from backend.service.baseline_service import memory_store
from backend.service.serialization import loads
from contracts.v1.memory import assess_relative_gait_speed
from contracts.v1.models import Evidence, Observation, RiskDomain, TimeScale
from contracts.v1.ruleset import load_ruleset_version


def _stable_id(*parts: object) -> str:
    value = "|".join(str(part) for part in parts)
    return f"evi-personal-speed-{hashlib.sha1(value.encode('utf-8')).hexdigest()[:16]}"


async def _has_persistent_v15_deviation(
    db: AsyncSession, observation: Observation, stats: dict[str, object], ruleset,
) -> tuple[bool, int]:
    """Require an abnormal prior activity window in the v1.5 trend horizon."""
    metadata = dict(observation.metadata or {})
    context = metadata.get("activity_context")
    start = observation.timestamp - timedelta(seconds=int(ruleset.windows["trend_seconds"]))
    rows = (await db.execute(
        select(ObservationRow).where(
            ObservationRow.resident_id == observation.resident_id,
            ObservationRow.feature_name == "step_speed_norm_s",
            ObservationRow.source == "gait_adapter_v15",
            ObservationRow.timestamp >= start,
            ObservationRow.timestamp <= observation.timestamp,
            ObservationRow.observation_id != observation.observation_id,
        ).order_by(ObservationRow.timestamp)
    )).scalars().all()
    abnormal_windows: set[tuple[object, object]] = set()
    for row in rows:
        row_metadata = loads(row.extra_metadata, {})
        if row_metadata.get("activity_context") != context:
            continue
        value = loads(row.feature_value, row.feature_value)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        prior = assess_relative_gait_speed(float(value), stats, ruleset)
        if prior["status"] == "EVIDENCE":
            abnormal_windows.add((row.asset_id, row.timestamp))
    required = int(ruleset.windows["trend_persistence_windows"])
    observed = 1 + len(abnormal_windows)
    return observed >= required, observed


async def relative_speed_evidence(
    db: AsyncSession, observations: Iterable[Observation],
) -> tuple[list[Evidence], dict[str, object]]:
    selected = [
        item for item in observations
        if item.feature_name == "step_speed_norm_s"
        and item.source in {"gait_adapter_v14", "gait_adapter_v15"}
        and isinstance(item.feature_value, (int, float))
    ]
    if not selected:
        return [], {"status": "NOT_APPLICABLE", "reason": "NO_V14_OR_V15_SPEED_OBSERVATION"}
    ruleset = load_ruleset_version(RULESET_VERSION)
    if ruleset.version not in {"ruleset-v1.4", "ruleset-v1.5"}:
        return [], {"status": "DISABLED", "reason": "ACTIVE_RULESET_IS_NOT_V14_OR_V15"}
    generated: list[Evidence] = []
    decisions: list[dict[str, object]] = []
    for observation in selected:
        baseline = await memory_store.baseline(db, observation.resident_id, observation.timestamp)
        metadata = dict(getattr(observation, "metadata", {}) or {})
        context = metadata.get("activity_context")
        if ruleset.version == "ruleset-v1.5" and (
            float(metadata.get("locomotion_duration_s") or 0.0)
            < float(ruleset.thresholds["relative_speed_min_locomotion_seconds"])
            or int(metadata.get("gait_cycle_count") or 0)
            < int(ruleset.thresholds["gait_min_complete_cycles"])
        ):
            decisions.append({
                "observation_id": observation.observation_id,
                "status": "DEGRADED",
                "reason": "GAIT_CYCLE_CONTEXT_INSUFFICIENT",
                "activity_context": context,
            })
            continue
        contextual = baseline.get("baselines_by_context", {})
        stats = (
            contextual.get(context, {}).get("relative_gait_speed", {})
            if ruleset.version == "ruleset-v1.5" and context and contextual
            else baseline.get("baselines", {}).get("relative_gait_speed", {})
        )
        if ruleset.version == "ruleset-v1.5" and contextual and not stats:
            decisions.append({
                "observation_id": observation.observation_id,
                "status": "DEGRADED",
                "reason": "ACTIVITY_CONTEXT_BASELINE_UNAVAILABLE",
                "activity_context": context,
            })
            continue
        current = float(observation.feature_value)
        assessment = assess_relative_gait_speed(current, stats, ruleset)
        audit = {
            "observation_id": observation.observation_id,
            "activity_context": context,
            **assessment,
        }
        if assessment["status"] == "DEGRADED":
            decisions.append(audit)
            continue
        if assessment["status"] == "WITHIN_BASELINE":
            decisions.append(audit)
            continue
        if ruleset.version == "ruleset-v1.5":
            persistent, observed_windows = await _has_persistent_v15_deviation(
                db, observation, stats, ruleset,
            )
            audit.update({
                "persistent": persistent,
                "observed_abnormal_windows": observed_windows,
                "required_abnormal_windows": int(ruleset.windows["trend_persistence_windows"]),
            })
            if not persistent:
                audit["status"] = "CANDIDATE_ONLY"
                audit["reason"] = "TREND_PERSISTENCE_INSUFFICIENT"
                decisions.append(audit)
                continue
        center_value = float(assessment["baseline_median"])
        mad_value = float(assessment["baseline_mad"])
        deviation = float(assessment["deviation"])
        generated.append(Evidence(
            schema_version="1.0", evidence_id=_stable_id(
                observation.observation_id, center_value, ruleset.version
            ),
            observation_ids=[observation.observation_id], resident_id=observation.resident_id,
            timestamp=observation.timestamp, risk_domain=RiskDomain.FALL,
            evidence_type="relative_speed_change", severity=float(assessment["severity"]),
            confidence=observation.confidence, data_quality=observation.data_quality,
            baseline_value=center_value, current_value=round(current, 3),
            baseline_deviation=round(deviation, 3), time_scale=TimeScale.MEDIUM,
            location=observation.location,
            explanation=(
                f"Active-window gait speed deviated {abs(deviation):.1%} from the "
                f"{str(assessment['baseline_status']).lower()} personal median; "
                f"baseline MAD={mad_value:.3f}; activity context={context or 'UNSPECIFIED'}."
            ),
            adapter_version=(
                "personal-gait-postprocessor-v1.5"
                if ruleset.version == "ruleset-v1.5"
                else "personal-gait-postprocessor-v1.4"
            ),
            source_mode=observation.source_mode, simulated=observation.simulated,
        ))
        decisions.append(audit)
    return generated, {"status": "COMPLETE", "decisions": decisions}
