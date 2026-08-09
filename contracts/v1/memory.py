"""Small, inspectable three-layer memory for the v1.0 agent.

This is intentionally an in-memory implementation. It keeps the data contract
unchanged while making the short, medium and long query windows explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from statistics import median
from typing import Any, Iterable

from .models import Evidence, Observation, RiskLevel
from .ruleset import Ruleset


class BaselineStatus(str, Enum):
    INSUFFICIENT = "INSUFFICIENT"
    PROVISIONAL = "PROVISIONAL"
    STABLE = "STABLE"


@dataclass(frozen=True)
class BaselineStats:
    metric: str
    median: float | None
    mad: float | None
    sample_count: int
    distinct_days: int
    status: BaselineStatus

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "median": self.median,
            "mad": self.mad,
            "sample_count": self.sample_count,
            "distinct_days": self.distinct_days,
            "status": self.status.value,
        }


class MemoryStore:
    """Evidence/time-window memory plus conservative baseline admission."""

    SAFE_BASELINE_TYPES = {
        "normal_baseline_sample",
        "rise_duration_baseline_sample",
        "trunk_sway_baseline_sample",
        "gait_stability_baseline_sample",
        "activity_range_baseline_sample",
        "circadian_baseline_sample",
    }
    DANGEROUS_TYPES = {
        "rapid_rise",
        "trunk_sway",
        "gait_instability",
        "persistent_instability",
        "no_response",
        "quality_gate_failed",
    }
    QUALITY_FLAGS = {"tracking_lost", "camera_occlusion", "audio_quality_low"}
    METRIC_BY_FEATURE = {
        "sit_to_stand_duration": "rise_duration",
        "trunk_sway_angle": "trunk_sway",
        "gait_stability_score": "gait_stability",
        "relative_gait_speed": "relative_gait_speed",
        "stable_trunk_angle_deg": "stable_trunk_angle_deg",
        "activity_range": "activity_range",
        "sleep_midpoint": "circadian",
    }

    def __init__(self, ruleset: Ruleset):
        self.ruleset = ruleset
        self.observations: dict[str, Observation] = {}
        self.evidences: dict[str, Evidence] = {}
        self.baseline_samples: dict[str, dict[str, list[tuple[datetime, float]]]] = {}
        self.resident_states: dict[str, RiskLevel] = {}
        self.baseline_decisions: list[dict[str, Any]] = []

    def add_observation(self, observation: Observation) -> None:
        self.observations[observation.observation_id] = observation

    def set_state(self, resident_id: str, state: RiskLevel) -> None:
        self.resident_states[resident_id] = state

    def state(self, resident_id: str) -> RiskLevel:
        return self.resident_states.get(resident_id, RiskLevel.GREEN)

    def add_evidence(self, evidence: Evidence) -> dict[str, Any]:
        self.evidences[evidence.evidence_id] = evidence
        decision = self._baseline_decision(evidence)
        self.baseline_decisions.append(decision)
        if decision["accepted"]:
            metric = decision["metric"]
            self.baseline_samples.setdefault(evidence.resident_id, {}).setdefault(metric, []).append(
                (evidence.timestamp, float(evidence.current_value))
            )
            self._prune(evidence.resident_id, evidence.timestamp)
        return decision

    def _baseline_decision(self, evidence: Evidence) -> dict[str, Any]:
        state = self.state(evidence.resident_id)
        linked = [self.observations[item] for item in evidence.observation_ids if item in self.observations]
        metric = None
        for observation in linked:
            metric = self.METRIC_BY_FEATURE.get(observation.feature_name)
            if metric:
                break
        decision = {
            "evidence_id": evidence.evidence_id,
            "accepted": False,
            "reason": "not_a_baseline_sample",
            "metric": metric,
        }
        if evidence.evidence_type not in self.SAFE_BASELINE_TYPES:
            if evidence.evidence_type in self.DANGEROUS_TYPES:
                decision["reason"] = "dangerous_evidence_never_updates_baseline"
            return decision
        if state != RiskLevel.GREEN:
            decision["reason"] = f"state_{state.value.lower()}_blocks_baseline_update"
            return decision
        if evidence.confidence < self.ruleset.thresholds["confidence"] or evidence.data_quality < self.ruleset.thresholds["data_quality"]:
            decision["reason"] = "confidence_or_data_quality_below_threshold"
            return decision
        if not metric or not isinstance(evidence.current_value, (int, float)) or isinstance(evidence.current_value, bool):
            decision["reason"] = "no_numeric_baseline_metric"
            return decision
        if any(
            observation.feature_name in self.QUALITY_FLAGS
            or observation.data_quality < self.ruleset.thresholds["data_quality"]
            for observation in linked
        ):
            decision["reason"] = "linked_observation_quality_flag"
            return decision
        decision["accepted"] = True
        decision["reason"] = "green_high_quality_safe_sample"
        return decision

    def _prune(self, resident_id: str, now: datetime) -> None:
        cutoff = now - timedelta(days=self.ruleset.windows["long_days"])
        for metric, samples in self.baseline_samples.get(resident_id, {}).items():
            self.baseline_samples[resident_id][metric] = [item for item in samples if item[0] >= cutoff]

    @staticmethod
    def _in_window(timestamp: datetime, now: datetime, delta: timedelta) -> bool:
        return now - delta <= timestamp <= now

    def query_short(self, resident_id: str, now: datetime) -> list[Evidence]:
        return [
            evidence for evidence in self.evidences.values()
            if evidence.resident_id == resident_id
            and self._in_window(evidence.timestamp, now, timedelta(seconds=self.ruleset.windows["short_seconds"]))
        ]

    def query_medium(self, resident_id: str, now: datetime) -> list[Evidence]:
        return [
            evidence for evidence in self.evidences.values()
            if evidence.resident_id == resident_id
            and self._in_window(evidence.timestamp, now, timedelta(hours=self.ruleset.windows["medium_hours"]))
        ]

    def query_long(self, resident_id: str, now: datetime) -> list[Evidence]:
        return [
            evidence for evidence in self.evidences.values()
            if evidence.resident_id == resident_id
            and self._in_window(evidence.timestamp, now, timedelta(days=self.ruleset.windows["long_days"]))
        ]

    def baseline(self, resident_id: str, now: datetime) -> dict[str, BaselineStats]:
        self._prune(resident_id, now)
        result: dict[str, BaselineStats] = {}
        for metric, samples in self.baseline_samples.get(resident_id, {}).items():
            values = [value for _, value in samples]
            days = {timestamp.date() for timestamp, _ in samples}
            center = median(values) if values else None
            deviations = [abs(value - center) for value in values] if center is not None else []
            mad = median(deviations) if deviations else None
            if len(days) >= self.ruleset.windows["long_days"]:
                status = BaselineStatus.STABLE
            elif len(days) >= 3:
                status = BaselineStatus.PROVISIONAL
            else:
                status = BaselineStatus.INSUFFICIENT
            result[metric] = BaselineStats(metric, center, mad, len(values), len(days), status)
        return result

    def snapshot(self, resident_id: str, now: datetime) -> dict[str, Any]:
        short = self.query_short(resident_id, now)
        medium = self.query_medium(resident_id, now)
        long = self.query_long(resident_id, now)
        low_light = sum(1 for item in medium if item.evidence_type == "low_illumination")
        abnormal_rises = sum(1 for item in medium if item.evidence_type == "rapid_rise")
        night_rises = sum(1 for item in medium if item.evidence_type in {"rapid_rise", "night_rise"} and (item.timestamp.hour >= 22 or item.timestamp.hour < 6))
        return {
            "resident_id": resident_id,
            "as_of": now.isoformat(),
            "short": {"window_seconds": self.ruleset.windows["short_seconds"], "evidence_ids": [item.evidence_id for item in short], "evidence_types": [item.evidence_type for item in short]},
            "medium": {"window_hours": self.ruleset.windows["medium_hours"], "abnormal_rise_count": abnormal_rises, "night_rise_count": night_rises, "low_light_count": low_light, "activity_state": self._activity_state(medium), "risk_state": self.state(resident_id).value},
            "long": {"window_days": self.ruleset.windows["long_days"], "evidence_ids": [item.evidence_id for item in long], "baseline": {key: value.as_dict() for key, value in self.baseline(resident_id, now).items()}},
        }

    @staticmethod
    def _activity_state(evidences: Iterable[Evidence]) -> str:
        latest = sorted(evidences, key=lambda item: item.timestamp)
        for item in reversed(latest):
            if item.evidence_type in {"activity_range_decline", "low_activity"}:
                return "DECLINING"
            if item.evidence_type in {"normal_activity", "normal_baseline_sample"}:
                return "NORMAL"
        return "UNKNOWN"
