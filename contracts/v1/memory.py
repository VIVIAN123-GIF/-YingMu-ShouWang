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


def assess_relative_gait_speed(
    current: float, stats: dict[str, Any], ruleset: Ruleset,
) -> dict[str, Any]:
    """Return one auditable personal-speed decision shared by runtime and evals."""
    status = str(stats.get("status", "INSUFFICIENT"))
    center = stats.get("median")
    mad = stats.get("mad")
    if (
        status not in {BaselineStatus.PROVISIONAL.value, BaselineStatus.STABLE.value}
        or not isinstance(center, (int, float))
        or not isinstance(mad, (int, float))
    ):
        return {"status": "DEGRADED", "reason": "PERSONAL_BASELINE_INSUFFICIENT"}

    center_value = float(center)
    mad_value = max(float(mad), 0.0)
    denominator = max(abs(center_value), 1e-6)
    deviation = (float(current) - center_value) / denominator
    relative_threshold = float(ruleset.thresholds["relative_speed_deviation_ratio"])
    mad_multiplier = float(ruleset.thresholds[
        "stable_mad_multiplier"
        if status == BaselineStatus.STABLE.value
        else "provisional_mad_multiplier"
    ])
    mad_threshold = mad_multiplier * mad_value / denominator
    effective_threshold = max(relative_threshold, mad_threshold)
    saturation = float((ruleset.severity_saturation or {})["relative_speed_change"])
    severity = min(max(
        (abs(deviation) - effective_threshold)
        / max(saturation - effective_threshold, 1e-6),
        0.0,
    ), 1.0)
    return {
        "status": "EVIDENCE" if abs(deviation) >= effective_threshold else "WITHIN_BASELINE",
        "baseline_status": status,
        "baseline_median": round(center_value, 3),
        "baseline_mad": round(mad_value, 3),
        "deviation": round(deviation, 3),
        "relative_threshold": round(relative_threshold, 3),
        "mad_threshold": round(mad_threshold, 3),
        "effective_threshold": round(effective_threshold, 3),
        "severity": round(severity, 3),
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
    ENVIRONMENT_TYPES = {
        "low_light",
        "low_illumination",
        "high_risk_zone_entry",
        "obstacle_occupancy",
        "obstacle_zone",
        "narrow_passage",
        "far_from_support",
        "danger_zone_stay",
        "route_crosses_obstacle",
    }
    PRE_FALL_TYPES = {
        "rapid_rise",
        "slow_rise",
        "trunk_sway",
        "gait_instability",
        "persistent_instability",
        "step_asymmetry",
        "dragging_step",
        "unstable_turn",
        "support_reach",
    }
    METRIC_BY_FEATURE = {
        "sit_to_stand_duration": "rise_duration",
        "rise_duration_s": "rise_duration",
        "trunk_sway_angle": "trunk_sway",
        "gait_stability_score": "gait_stability",
        "relative_gait_speed": "relative_gait_speed",
        "step_speed_norm_s": "relative_gait_speed",
        "stable_trunk_angle_deg": "stable_trunk_angle_deg",
        "trunk_sway_angle_deg": "trunk_sway",
        "post_rise_pelvis_lateral_excursion_norm": "pelvis_lateral_excursion",
        "post_rise_support_width_change_norm": "support_width_change",
        "step_asymmetry_ratio": "step_asymmetry",
        "turn_angular_velocity_deg_s": "turn_angular_velocity",
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
        cutoff = now - timedelta(days=self.ruleset.windows.get(
            "baseline_lookback_days", self.ruleset.windows["long_days"]
        ))
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
            if len(days) >= self.ruleset.windows.get("stable_target_days", self.ruleset.windows["long_days"]):
                status = BaselineStatus.STABLE
            elif len(days) >= self.ruleset.windows.get("provisional_target_days", 3):
                status = BaselineStatus.PROVISIONAL
            else:
                status = BaselineStatus.INSUFFICIENT
            result[metric] = BaselineStats(metric, center, mad, len(values), len(days), status)
        return result

    def snapshot(self, resident_id: str, now: datetime) -> dict[str, Any]:
        short = self.query_short(resident_id, now)
        medium = self.query_medium(resident_id, now)
        long = self.query_long(resident_id, now)
        low_light = sum(1 for item in medium if item.evidence_type in {"low_light", "low_illumination"})
        abnormal_rises = sum(1 for item in medium if item.evidence_type == "rapid_rise")
        night_rises = sum(1 for item in medium if item.evidence_type in {"rapid_rise", "night_rise"} and (item.timestamp.hour >= 22 or item.timestamp.hour < 6))
        return {
            "resident_id": resident_id,
            "as_of": now.isoformat(),
            "short": {"window_seconds": self.ruleset.windows["short_seconds"], "evidence_ids": [item.evidence_id for item in short], "evidence_types": [item.evidence_type for item in short]},
            "medium": {"window_hours": self.ruleset.windows["medium_hours"], "abnormal_rise_count": abnormal_rises, "night_rise_count": night_rises, "low_light_count": low_light, "activity_state": self._activity_state(medium), "risk_state": self.state(resident_id).value},
            "long": {"window_days": self.ruleset.windows["long_days"], "evidence_ids": [item.evidence_id for item in long], "baseline": {key: value.as_dict() for key, value in self.baseline(resident_id, now).items()}},
        }

    def forewarning_profile(self, resident_id: str, now: datetime) -> dict[str, Any]:
        all_short = self.query_short(resident_id, now)
        all_medium = self.query_medium(resident_id, now)
        short = [item for item in all_short if item.risk_domain.value != "SYSTEM"]
        medium = [item for item in all_medium if item.risk_domain.value != "SYSTEM"]
        usable_fall = [
            item for item in short
            if item.risk_domain.value == "FALL"
            and self.ruleset.usable(float(item.confidence), float(item.data_quality))
        ]
        environment = [
            item for item in all_medium
            if item.risk_domain.value == "SYSTEM"
            and item.evidence_type in self.ENVIRONMENT_TYPES
            and self.ruleset.usable(float(item.confidence), float(item.data_quality))
        ] if usable_fall else []
        quality_penalty = self._quality_penalty(short)
        personal_deviation = self._personal_deviation(short + medium)
        environment_risk = self._environment_risk(environment)
        rule_risk = self._rule_risk(short)
        trend_risk = self._trend_risk(medium)
        instant = self._clamp(0.58 * rule_risk + 0.22 * personal_deviation + 0.20 * environment_risk - quality_penalty)
        thirty_seconds = self._clamp(0.55 * instant + 0.35 * trend_risk + 0.10 * environment_risk)
        three_minutes = self._clamp(0.45 * trend_risk + 0.25 * personal_deviation + 0.20 * environment_risk + 0.10 * instant)
        dominant = self._dominant_factors(short, medium, personal_deviation, environment_risk, quality_penalty)
        return {
            "as_of": now.isoformat(),
            "risk_level": self._risk_level(max(instant, thirty_seconds, three_minutes)),
            "instant_risk": round(instant, 2),
            "risk_30s": round(thirty_seconds, 2),
            "trend_3min": round(three_minutes, 2),
            "trend_direction": self._trend_direction(instant, three_minutes),
            "personal_deviation": round(personal_deviation, 2),
            "environment_risk": round(environment_risk, 2),
            "quality_penalty": round(quality_penalty, 2),
            "dominant_factors": dominant,
            "evidence_ids": [item.evidence_id for item in sorted(short + medium + environment, key=lambda item: item.timestamp) if item.evidence_type in self.PRE_FALL_TYPES | self.ENVIRONMENT_TYPES][-6:],
            "recommended_intervention": self._recommended_intervention(max(instant, thirty_seconds, three_minutes), quality_penalty),
        }

    @staticmethod
    def _clamp(value: float) -> float:
        return min(max(value, 0.0), 1.0)

    @staticmethod
    def _risk_level(score: float) -> str:
        if score >= 0.9:
            return "RED"
        if score >= 0.7:
            return "ORANGE"
        if score >= 0.4:
            return "YELLOW"
        return "GREEN"

    @staticmethod
    def _trend_direction(instant: float, trend: float) -> str:
        if trend >= instant + 0.08:
            return "RISING"
        if trend <= instant - 0.08:
            return "FALLING"
        return "STABLE"

    def _quality_penalty(self, evidences: list[Evidence]) -> float:
        if not evidences:
            return 0.0
        worst_quality = min(float(item.data_quality) for item in evidences)
        if worst_quality >= self.ruleset.thresholds["data_quality"]:
            return 0.0
        return min((self.ruleset.thresholds["data_quality"] - worst_quality) * 0.8, 0.3)

    @staticmethod
    def _personal_deviation(evidences: list[Evidence]) -> float:
        deviations = [
            min(abs(float(item.baseline_deviation)) / 3.0, 1.0)
            for item in evidences
            if item.baseline_deviation is not None
        ]
        return max(deviations, default=0.0)

    def _environment_risk(self, evidences: list[Evidence]) -> float:
        risks = [
            max(float(item.severity), float(item.confidence) * 0.65)
            for item in evidences
            if item.evidence_type in self.ENVIRONMENT_TYPES
        ]
        return min(sum(risks) / 2.0, 1.0)

    def _rule_risk(self, evidences: list[Evidence]) -> float:
        usable = [
            item for item in evidences
            if item.evidence_type in self.PRE_FALL_TYPES
            and item.confidence >= self.ruleset.thresholds["confidence"]
            and item.data_quality >= self.ruleset.thresholds["data_quality"]
        ]
        if not usable:
            return 0.0
        base = max(float(item.severity) for item in usable)
        if len({item.evidence_type for item in usable}) >= 2:
            base += 0.12
        return min(base, 1.0)

    def _trend_risk(self, evidences: list[Evidence]) -> float:
        recent = [
            item for item in evidences
            if item.evidence_type in self.PRE_FALL_TYPES
            and item.confidence >= self.ruleset.thresholds["confidence"]
            and item.data_quality >= self.ruleset.thresholds["data_quality"]
        ]
        if not recent:
            return 0.0
        average = sum(float(item.severity) for item in recent) / len(recent)
        repeated = min(len(recent) / 4.0, 0.25)
        return min(average + repeated, 1.0)

    def _dominant_factors(
        self,
        short: list[Evidence],
        medium: list[Evidence],
        personal_deviation: float,
        environment_risk: float,
        quality_penalty: float,
    ) -> list[str]:
        factors = []
        if any(item.evidence_type in self.PRE_FALL_TYPES for item in short):
            factors.append("fall_precursor_evidence")
        if personal_deviation >= 0.5:
            factors.append("personal_baseline_deviation")
        if environment_risk >= 0.3:
            factors.append("environment_interaction_risk")
        if quality_penalty > 0:
            factors.append("data_quality_downgrade")
        if len([item for item in medium if item.evidence_type in self.PRE_FALL_TYPES]) >= 2:
            factors.append("multi_scale_accumulation")
        return factors or ["normal_fluctuation"]

    @staticmethod
    def _recommended_intervention(score: float, quality_penalty: float) -> str:
        if quality_penalty > 0.15:
            return "画面质量不足，先切换补光或备用观测，不直接升级报警。"
        if score >= 0.9:
            return "通知家属并转人工接管，继续观察是否恢复。"
        if score >= 0.7:
            return "执行低打扰语音或灯光提醒，并进入恢复观察。"
        if score >= 0.4:
            return "保持观察，等待第二条独立前兆证据。"
        return "仅记录为日常波动，不打扰老人。"

    @staticmethod
    def _activity_state(evidences: Iterable[Evidence]) -> str:
        latest = sorted(evidences, key=lambda item: item.timestamp)
        for item in reversed(latest):
            if item.evidence_type in {"activity_range_decline", "low_activity"}:
                return "DECLINING"
            if item.evidence_type in {"normal_activity", "normal_baseline_sample"}:
                return "NORMAL"
        return "UNKNOWN"
