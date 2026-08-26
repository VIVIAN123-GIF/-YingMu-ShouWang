"""Repository-neutral fall decision policy shared by the agent and FastAPI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .ruleset import Ruleset, load_ruleset


DANGER_EVIDENCE_TYPES = {
    "trunk_sway",
    "gait_instability",
    "post_rise_lateral_drift",
    "support_base_change",
    "compensatory_step",
    "persistent_instability",
    "no_response",
}

MENTAL_TREND_EVIDENCE_TYPES = {
    "activity_range_decline",
    "room_transition_decline",
    "day_night_rhythm_change",
}

FRAUD_RISK_EVIDENCE_TYPES = {
    "unauthorized_visitor",
    "unusual_dwell_time",
    "fraud_keyword",
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
    """Pure fall-state decision; persistence is owned by adapters."""

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

        indeterminate = next(
            (item for item in reversed(recent) if item.evidence_type == "assessment_indeterminate"),
            None,
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

            if trigger is not None and trigger.evidence_type == "assessment_indeterminate":
                return Decision(
                    "R-FALL-09", previous_state, active_status, "REVIEW",
                    "post-rise assessment is indeterminate; the active event remains unchanged",
                    (trigger.evidence_id,),
                    not_matched={"R-FALL-07": "no new usable escalation signal is present"},
                )

            if trigger is not None and not self.usable(trigger):
                return Decision(
                    "R-FALL-03",
                    previous_state,
                    active_status,
                    "NONE",
                    "confidence or data_quality is below the ruleset gate; no risk upgrade",
                    not_matched={"R-FALL-07": "no usable internal escalation signal is present"},
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

        if indeterminate is not None:
            return Decision(
                "R-FALL-09", "UNKNOWN", None, "REVIEW",
                "post-rise assessment is indeterminate; manual review is required",
                (indeterminate.evidence_id,),
                not_matched={"R-FALL-02": "input quality or camera geometry is not assessable"},
            )

        if trigger is not None and not self.usable(trigger):
            return Decision(
                "R-FALL-03",
                previous_state,
                active_status,
                "NONE",
                "confidence or data_quality is below the ruleset gate; no risk upgrade",
                not_matched={"R-FALL-02": "trigger evidence is not usable"},
            )

        transitions = [
            item for item in usable_recent if item.evidence_type == "sit_to_stand_transition"
        ]
        family_by_type = {
            evidence_type: family
            for family, evidence_types in self.ruleset.signal_families.items()
            for evidence_type in evidence_types
        }
        signal_items = [item for item in usable_recent if item.evidence_type in family_by_type]

        def observation_ids(item: Any) -> set[str]:
            values = getattr(item, "observation_ids", ())
            if isinstance(values, str):
                try:
                    values = json.loads(values)
                except json.JSONDecodeError:
                    return set()
            return {str(value) for value in values if isinstance(value, str)}

        def same_assessment(left: Any, right: Any) -> bool:
            left_mode = getattr(getattr(left, "source_mode", None), "value", getattr(left, "source_mode", None))
            right_mode = getattr(getattr(right, "source_mode", None), "value", getattr(right, "source_mode", None))
            return (
                left_mode == right_mode
                and bool(left.simulated) == bool(right.simulated)
                and bool(observation_ids(left) & observation_ids(right))
            )

        def seconds_after(candidate: Any, transition_item: Any) -> float:
            return (
                self._time(candidate.timestamp, transition_item.timestamp)
                - transition_item.timestamp
            ).total_seconds()

        transition = next(
            (
                candidate
                for candidate in reversed(transitions)
                if any(
                    same_assessment(candidate, signal)
                    and 0 <= seconds_after(signal, candidate) <= self.ruleset.windows["short_seconds"]
                    for signal in signal_items
                )
            ),
            None,
        )
        paired_signals = [
            signal
            for signal in signal_items
            if transition is not None
            and same_assessment(transition, signal)
            and 0 <= seconds_after(signal, transition) <= self.ruleset.windows["short_seconds"]
        ]
        selected_by_family: dict[str, Any] = {}
        for signal in paired_signals:
            selected_by_family[family_by_type[signal.evidence_type]] = signal

        if transition is not None and len(selected_by_family) >= int(
            thresholds["orange_min_signal_families"]
        ):
            selected = [transition, *selected_by_family.values()]
            score_details = self.ruleset.score_details(selected[1:], context_score)
            source_mode = getattr(
                getattr(transition, "source_mode", None),
                "value",
                getattr(transition, "source_mode", None),
            )
            if source_mode in {"RECORDED_REPLAY", "MOCK"} and bool(transition.simulated):
                return Decision(
                    "R-FALL-02", "ORANGE", "INTERVENING", "CREATE_EVENT",
                    "an assessable sit-to-stand transition has instability in at least two independent signal families",
                    tuple(item.evidence_id for item in selected),
                    score_details["final_score"], score_details,
                )
            return Decision(
                "R-FALL-10", "YELLOW", None, "REVIEW",
                "multi-family post-rise instability requires review because live-device positive validation is incomplete",
                tuple(item.evidence_id for item in selected),
                score_details["final_score"], score_details,
                {"R-FALL-02": "automatic ORANGE is limited to explicitly simulated replay evidence"},
            )

        if transition is not None and selected_by_family:
            selected = [transition, *selected_by_family.values()]
            return Decision(
                "R-FALL-11", "YELLOW", None, "REVIEW",
                "one post-rise instability signal family is present; independent confirmation is absent",
                tuple(item.evidence_id for item in selected),
                not_matched={"R-FALL-02": "fewer than two independent signal families are present"},
            )

        rapid_items = [item for item in usable_recent if item.evidence_type == "rapid_rise"]
        slow_items = [item for item in usable_recent if item.evidence_type == "slow_rise"]
        instability_items = [
            item for item in usable_recent if item.evidence_type == "gait_instability"
        ]
        observation_pair = next(
            (
                (rapid, instability)
                for rapid in reversed(rapid_items)
                for instability in reversed(instability_items)
                if abs(
                    (self._time(instability.timestamp, rapid.timestamp) - rapid.timestamp).total_seconds()
                ) <= self.ruleset.windows["short_seconds"]
            ),
            None,
        )
        if observation_pair:
            return Decision(
                "R-FALL-08", "YELLOW", None, "REVIEW",
                "legacy rise-speed and gait-asymmetry signals require review and do not create an event",
                tuple(item.evidence_id for item in observation_pair),
                not_matched={"R-FALL-02": "transition-bound multi-family evidence is absent"},
            )
        speed_items = [*rapid_items, *slow_items]
        if speed_items:
            return Decision(
                "R-FALL-12", "YELLOW", None, "REVIEW",
                "rise speed is an observation signal and does not independently establish post-rise instability",
                (speed_items[-1].evidence_id,),
                not_matched={"R-FALL-02": "two independent post-rise instability families are absent"},
            )
        if transitions:
            return Decision(
                "R-FALL-01", "GREEN", None, "NONE",
                "the sit-to-stand transition is assessable and no post-rise instability signal is present",
                (transitions[-1].evidence_id,),
            )
        return Decision("NO_MATCH", previous_state, None, "NONE", "no usable short-window combination is present")


class MentalDecisionPolicy:
    """Engineering trend rules; this policy never makes a clinical diagnosis."""

    def __init__(self, ruleset: Ruleset | None = None):
        self.ruleset = ruleset or load_ruleset()

    def usable(self, evidence: Any) -> bool:
        return self.ruleset.usable(
            float(evidence.confidence), float(evidence.data_quality)
        )

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
        **_: Any,
    ) -> Decision:
        del now, recovery_started_at
        if trigger is not None and not self.usable(trigger):
            return Decision(
                "R-MENTAL-00", previous_state, active_status, "NONE",
                "confidence or data_quality is below the engineering gate; no trend event change",
            )

        if active_status in {"OPEN", "OBSERVING"}:
            if trigger is not None and trigger.evidence_type == "trend_recovered":
                if active_created_at is None or FallDecisionPolicy._time(
                    trigger.timestamp, active_created_at
                ) > active_created_at:
                    return Decision(
                        "R-MENTAL-03", "GREEN", "RESOLVED", "RESOLVE",
                        "the structured trend scenario supplied a post-event recovery marker",
                        (trigger.evidence_id,),
                    )
            if trigger is not None and trigger.evidence_type == "family_contact_completed":
                return Decision(
                    "R-MENTAL-02", "YELLOW", "OBSERVING", "BEGIN_OBSERVING",
                    "family contact was completed; continue non-clinical trend observation",
                    (trigger.evidence_id,),
                )
            if trigger is not None and trigger.evidence_type in MENTAL_TREND_EVIDENCE_TYPES:
                return Decision(
                    "R-MENTAL-01", "YELLOW", active_status, "ATTACH_EVIDENCE",
                    "another usable non-clinical trend deviation was recorded",
                    (trigger.evidence_id,),
                )
            return Decision(
                "NO_MATCH", previous_state, active_status, "NONE",
                "the active trend event is awaiting contact or recovery evidence",
            )

        if trigger is not None and trigger.evidence_type in MENTAL_TREND_EVIDENCE_TYPES:
            score_details = self.ruleset.score_details([trigger])
            return Decision(
                "R-MENTAL-01", "YELLOW", "OPEN", "CREATE_EVENT",
                "a usable non-clinical activity or day/night trend deviation was recorded",
                (trigger.evidence_id,), score_details["final_score"], score_details,
            )
        return Decision(
            "NO_MATCH", previous_state, None, "NONE",
            "no usable non-clinical trend deviation is present",
        )


class FraudDecisionPolicy:
    """Visitor/conversation verification rules; this policy never confirms fraud."""

    def __init__(self, ruleset: Ruleset | None = None):
        self.ruleset = ruleset or load_ruleset()

    def usable(self, evidence: Any) -> bool:
        return self.ruleset.usable(
            float(evidence.confidence), float(evidence.data_quality)
        )

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
        **_: Any,
    ) -> Decision:
        del now, active_created_at, recovery_started_at
        if trigger is not None and not self.usable(trigger):
            return Decision(
                "R-FRAUD-00", previous_state, active_status, "NONE",
                "confidence or data_quality is below the engineering gate; no verification event change",
            )

        if active_status in {"OPEN", "INTERVENING", "OBSERVING"} and trigger is not None:
            if trigger.evidence_type in {"identity_verified", "false_alarm_confirmed"}:
                next_status = (
                    "FALSE_ALARM" if trigger.evidence_type == "false_alarm_confirmed" else "RESOLVED"
                )
                return Decision(
                    "R-FRAUD-03", "GREEN", next_status, "RESOLVE",
                    "the structured verification scenario supplied an identity or false-alarm closure marker",
                    (trigger.evidence_id,),
                )

        usable_recent = [item for item in recent if self.usable(item)]
        by_type = {
            evidence_type: next(
                (item for item in reversed(usable_recent) if item.evidence_type == evidence_type),
                None,
            )
            for evidence_type in FRAUD_RISK_EVIDENCE_TYPES
        }
        combination = [item for item in by_type.values() if item is not None]
        if len(combination) == len(FRAUD_RISK_EVIDENCE_TYPES):
            score_details = self.ruleset.score_details(combination)
            return Decision(
                "R-FRAUD-02", "ORANGE", "INTERVENING",
                "UPGRADE_EVENT" if active_status else "CREATE_EVENT",
                "three independent visitor, dwell, and risk-word indicators require human verification",
                tuple(item.evidence_id for item in combination),
                score_details["final_score"], score_details,
            )

        if trigger is not None and trigger.evidence_type in FRAUD_RISK_EVIDENCE_TYPES:
            score_details = self.ruleset.score_details([trigger])
            action = "ATTACH_EVIDENCE" if active_status else "CREATE_EVENT"
            return Decision(
                "R-FRAUD-01", "YELLOW", active_status or "OPEN", action,
                "a single structured indicator starts or updates identity verification only",
                (trigger.evidence_id,), score_details["final_score"], score_details,
                {"R-FRAUD-02": "the three-indicator combination is incomplete"},
            )
        return Decision(
            "NO_MATCH", previous_state, active_status, "NONE",
            "no usable visitor, dwell, or risk-word indicator is present",
        )


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
