"""Cross-adapter semantic validation that cannot be expressed by JSON Schema alone."""

from __future__ import annotations

import math
import json
from typing import Any

from .ruleset import Ruleset, load_ruleset


class EvidenceSemanticError(ValueError):
    pass


def _feature_value(observation: Any) -> Any:
    value = getattr(observation, "feature_value", None)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def validate_evidence_semantics(
    evidence: Any,
    observations: list[Any],
    ruleset: Ruleset | None = None,
) -> None:
    if evidence.evidence_type != "posture_recovered":
        return
    selected_ruleset = ruleset or load_ruleset()
    threshold = float(selected_ruleset.thresholds["stable_posture_seconds"])
    current = evidence.current_value
    baseline = evidence.baseline_value
    if not isinstance(current, (int, float)) or isinstance(current, bool) or current < 0:
        raise EvidenceSemanticError("posture_recovered.current_value must be stable duration in seconds")
    if not isinstance(baseline, (int, float)) or not math.isclose(float(baseline), threshold, abs_tol=1e-6):
        raise EvidenceSemanticError(f"posture_recovered.baseline_value must be {threshold:g} seconds")
    by_feature = {getattr(item, "feature_name", ""): item for item in observations}
    duration_observation = by_feature.get("stable_posture_duration")
    angle_observation = by_feature.get("stable_trunk_angle_deg")
    if duration_observation is None or angle_observation is None:
        raise EvidenceSemanticError(
            "posture_recovered must reference stable_posture_duration and stable_trunk_angle_deg Observations"
        )
    duration_value = _feature_value(duration_observation)
    angle_value = _feature_value(angle_observation)
    if not isinstance(duration_value, (int, float)) or not math.isclose(float(duration_value), float(current), abs_tol=1e-3):
        raise EvidenceSemanticError("stable_posture_duration Observation must equal Evidence.current_value")
    if not isinstance(angle_value, (int, float)) or isinstance(angle_value, bool):
        raise EvidenceSemanticError("stable_trunk_angle_deg Observation must contain a numeric angle")
