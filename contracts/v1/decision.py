"""Repository-neutral fall decision policy shared by the agent and FastAPI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .ruleset import Ruleset, load_ruleset


DANGER_EVIDENCE_TYPES = {
    "rapid_rise",
    "slow_rise",
    "trunk_sway",
    "gait_instability",
    "relative_speed_change",
    "persistent_instability",
    "no_response",
}


@dataclass(frozen=True)
class Decision:
    matched_rule: str
    risk_level: str
    next_status: str | None
    action: str
    reason: str
    evidence_ids: tuple[str, ...] = ()
    score: float | None = None
    score_components: dict[str, Any] = field(default_factory=dict)
    not_matched: dict[str, str] = field(default_factory=dict)


class FallDecisionPolicy:
    """Pure ruleset-v1.0 state decision; persistence is owned by adapters."""

    def __init__(self, ruleset: Ruleset | None = None):
        self.ruleset = ruleset or load_ruleset()

    def usable(self, evidence: Any) -> bool:
        domain = getattr(evidence, "risk_domain", None)
        domain_value = getattr(domain, "value", domain)
        return domain_value != "SYSTEM" and self.ruleset.usable(
            float(evidence.confidence), float(evidence.data_quality)
        )

    @staticmethod
    def _time(value: datetime, reference: datetime) -> datetime:
        if value.tzinfo is None and reference.tzinfo is not None:
            return value.replace(tzinfo=reference.tzinfo)
        if value.tzinfo is not None and reference.tzinfo is None:
            return value.replace(tzinfo=None)
        return value

    def evaluate(
        self,
        *,
        now: datetime,
        previous_state: str,
        active_status: str | None,
        active_created_at: datetime | None,
        recovery_started_at: datetime | None,
        recent: list[Any],
        trigger: Any | None = None,
        context_score: float = 0.0,
        intervention_attempts: int = 0,
        latest_intervention_at: datetime | None = None,
    ) -> Decision:
        thresholds = self.ruleset.thresholds
        usable_recent = [item for item in recent if self.usable(item)]

        if trigger is not None and not self.usable(trigger):
            return Decision(
                "R-FALL-03",
                previous_state,
                active_status,
                "NONE",
                "confidence or data_quality is below the ruleset gate; no risk upgrade",
                not_matched={"R-FALL-02": "trigger evidence is not usable"},
            )

        if active_status in {"OPEN", "INTERVENING", "OBSERVING"}:
            persistent = next(
                (item for item in usable_recent if item.evidence_type in {"persistent_instability", "no_response"}),
                None,
            )
            repeated = next(
                (
                    item for item in usable_recent
                    if intervention_attempts >= 2
                    and latest_intervention_at is not None
                    and self._time(item.timestamp, latest_intervention_at) > latest_intervention_at
                    and item.evidence_type in {"trunk_sway", "gait_instability"}
                ),
                None,
            )
            escalation = persistent or repeated
            if escalation is not None:
                return Decision(
                    "R-FALL-07", "RED", "ESCALATED", "ESCALATE",
                    "persistent hazard, no response, or hazard after two interventions",
                    (escalation.evidence_id,), thresholds["red_score"],
                )

            if active_status in {"OPEN", "INTERVENING"} and trigger is not None and trigger.evidence_type == "posture_recovered":
                duration = float(trigger.current_value) if isinstance(trigger.current_value, (int, float)) else -1.0
                if duration >= thresholds["stable_posture_seconds"] and (
                    active_created_at is None or self._time(trigger.timestamp, active_created_at) > active_created_at
                ):
                    return Decision(
                        "R-FALL-04", previous_state, "OBSERVING", "BEGIN_OBSERVING",
                        f"stable posture reached {duration:.3f}s; threshold={thresholds['stable_posture_seconds']}s",
                        (trigger.evidence_id,),
                    )
                return Decision(
                    "NO_MATCH", previous_state, active_status, "NONE",
                    "posture recovery evidence is valid but the stable-duration threshold is not met",
                    not_matched={
                        "R-FALL-04": f"stable duration {duration:.3f}s is below {thresholds['stable_posture_seconds']}s"
                    },
                )

            if active_status == "OBSERVING":
                hazard = next(
                    (
                        item for item in usable_recent
                        if recovery_started_at is not None
                        and self._time(item.timestamp, recovery_started_at) > recovery_started_at
                        and self._time(item.timestamp, now) <= now
                        and item.evidence_type in DANGER_EVIDENCE_TYPES
                        and item.evidence_type != "posture_recovered"
                    ),
                    None,
                )
                if hazard is not None:
                    return Decision(
                        "R-FALL-06", previous_state, "INTERVENING", "RESTART_INTERVENTION",
                        "new usable hazard appeared during the observation window",
                        (hazard.evidence_id,),
                    )
                comparable_recovery = self._time(recovery_started_at, now) if recovery_started_at is not None else None
                if comparable_recovery is not None and now >= comparable_recovery + timedelta(
                    seconds=thresholds["observation_seconds"]
                ):
                    return Decision(
                        "R-FALL-05", "GREEN", "RESOLVED", "RESOLVE",
                        f"{thresholds['observation_seconds']}s observation completed without a new hazard",
                    )
                return Decision(
                    "NO_MATCH", previous_state, active_status, "NONE",
                    "observation is still in progress",
                    not_matched={"R-FALL-05": "observation window is not complete"},
                )

            return Decision(
                "NO_MATCH", previous_state, active_status, "NONE",
                "active event is awaiting new evidence",
            )

        rapid_items = [item for item in usable_recent if item.evidence_type == "rapid_rise"]
        sway_items = [item for item in usable_recent if item.evidence_type == "trunk_sway"]
        pair = next(
            (
                (rapid, sway)
                for rapid in reversed(rapid_items)
                for sway in reversed(sway_items)
                if abs((self._time(sway.timestamp, rapid.timestamp) - rapid.timestamp).total_seconds()) <= self.ruleset.windows["short_seconds"]
                and self.ruleset.high_confidence([rapid.confidence, sway.confidence])
            ),
            None,
        )
        if pair:
            score_details = self.ruleset.score_details(list(pair), context_score)
            return Decision(
                "R-FALL-02", "ORANGE", "INTERVENING", "CREATE_EVENT",
                "rapid_rise and trunk_sway are within the short window with usable quality and high confidence",
                tuple(item.evidence_id for item in pair),
                score_details["final_score"], score_details,
                {"R-FALL-01": "a second independent short-window evidence is present"},
            )
        if rapid_items:
            return Decision(
                "R-FALL-01", "GREEN", None, "NONE",
                "rapid_rise alone waits for an independent danger signal",
                not_matched={"R-FALL-02": "trunk_sway is absent, unusable, or outside the short window"},
            )
        return Decision("NO_MATCH", previous_state, None, "NONE", "no usable short-window combination is present")


def quality_snapshot(evidences: list[Any], ruleset: Ruleset) -> dict[str, Any]:
    return {
        "thresholds": {
            "confidence": ruleset.thresholds["confidence"],
            "data_quality": ruleset.thresholds["data_quality"],
            "high_confidence": ruleset.thresholds["high_confidence"],
        },
        "evidences": [
            {
                "evidence_id": item.evidence_id,
                "evidence_type": item.evidence_type,
                "confidence": float(item.confidence),
                "data_quality": float(item.data_quality),
                "usable": ruleset.usable(float(item.confidence), float(item.data_quality)),
            }
            for item in evidences
        ],
    }
