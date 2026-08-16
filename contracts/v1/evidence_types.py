"""One frozen Evidence dictionary shared by contracts and FastAPI."""

from __future__ import annotations


EVIDENCE_TYPES_BY_DOMAIN = {
    "FALL": {
        "rapid_rise", "slow_rise", "trunk_sway", "gait_instability",
        "relative_speed_change", "posture_recovered", "tracking_lost",
        "persistent_instability", "no_response", "normal_baseline_sample",
        "rise_duration_baseline_sample", "trunk_sway_baseline_sample",
        "gait_stability_baseline_sample",
    },
    "MENTAL": {
        "activity_range_decline", "room_transition_decline",
        "day_night_rhythm_change", "unusual_pacing", "mental_self_report",
        "family_concern", "voluntary_screening_concern",
        "family_contact_completed", "professional_support_suggested",
        "trend_recovered", "activity_range_baseline_sample",
        "circadian_baseline_sample",
    },
    "FRAUD": {
        "unauthorized_visitor", "unusual_dwell_time", "fraud_keyword",
        "identity_verified", "false_alarm_confirmed",
    },
    "SYSTEM": {
        "audio_quality_low", "low_illumination", "low_light", "high_risk_zone_entry",
        "obstacle_occupancy", "camera_occlusion", "stream_unavailable",
        "quality_gate_failed",
    },
}

INTERNAL_EVIDENCE_TYPES = {
    "no_response", "persistent_instability", "quality_gate_failed",
}
ALL_EVIDENCE_TYPES = sorted(set().union(*EVIDENCE_TYPES_BY_DOMAIN.values()))


def validate_evidence_type(risk_domain: object, evidence_type: str) -> str:
    domain = getattr(risk_domain, "value", risk_domain)
    if evidence_type not in EVIDENCE_TYPES_BY_DOMAIN.get(str(domain), set()):
        raise ValueError("evidence_type is not frozen for the selected risk_domain")
    return evidence_type
