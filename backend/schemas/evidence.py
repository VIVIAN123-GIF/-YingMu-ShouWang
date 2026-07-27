from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class EvidenceCreate(Evidence):
    pass


class RiskEvaluationSummary(BaseModel):
    risk_level: str
    event_created: bool
    event_id: str | None
    matched_rule: str
    ruleset_version: str


class EvidenceCreateResponse(BaseModel):
    evidence: Evidence
    saved: bool
    idempotent: bool
    evaluation: RiskEvaluationSummary
