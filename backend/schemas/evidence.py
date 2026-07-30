from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.schemas.common import RiskDomain, Score, SourceMode, TimezoneDatetime


class Evidence(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    schema_version: Literal["1.0"] = "1.0"
    evidence_id: str
    observation_ids: list[str] = Field(min_length=1)
    resident_id: str
    timestamp: TimezoneDatetime
    risk_domain: RiskDomain
    evidence_type: str
    severity: Score
    confidence: Score
    data_quality: Score
    baseline_value: float | None
    current_value: float | None
    baseline_deviation: float | None
    time_scale: Literal["SHORT", "MEDIUM", "LONG"]
    location: str | None
    explanation: str
    adapter_version: str
    source_mode: SourceMode
    simulated: bool

    @model_validator(mode="after")
    def validate_frozen_evidence_type(self):
        allowed = {
            RiskDomain.FALL: {"rapid_rise", "slow_rise", "trunk_sway", "gait_instability",
                              "relative_speed_change", "posture_recovered", "tracking_lost",
                              "normal_baseline_sample", "rise_duration_baseline_sample",
                              "trunk_sway_baseline_sample", "gait_stability_baseline_sample"},
            RiskDomain.MENTAL: {"activity_range_decline", "room_transition_decline",
                                "day_night_rhythm_change", "unusual_pacing", "mental_self_report",
                                "family_concern", "voluntary_screening_concern",
                                "family_contact_completed", "professional_support_suggested",
                                "trend_recovered", "activity_range_baseline_sample",
                                "circadian_baseline_sample"},
            RiskDomain.FRAUD: {"unauthorized_visitor", "unusual_dwell_time", "fraud_keyword",
                               "identity_verified", "false_alarm_confirmed"},
            RiskDomain.SYSTEM: {"audio_quality_low", "low_illumination", "high_risk_zone_entry",
                                "obstacle_occupancy", "camera_occlusion", "stream_unavailable"},
        }
        if self.evidence_type not in allowed[self.risk_domain]:
            raise ValueError("evidence_type is not frozen for the selected risk_domain")
        return self


class EvidenceCreate(Evidence):
    pass


class RiskEvaluationSummary(BaseModel):
    risk_level: str
    event_created: bool
    event_id: str | None
    matched_rule: str
    ruleset_version: str
    system_evidence_id: str | None = None


class EvidenceCreateResponse(BaseModel):
    evidence: Evidence
    saved: bool
    idempotent: bool
    evaluation: RiskEvaluationSummary
