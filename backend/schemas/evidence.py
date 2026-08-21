from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.schemas.common import RiskDomain, Score, SourceMode, TimezoneDatetime
from contracts.v1.evidence_types import (
    ALL_EVIDENCE_TYPES,
    INTERNAL_EVIDENCE_TYPES,
    validate_evidence_type,
)


class Evidence(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    schema_version: Literal["1.0"] = "1.0"
    evidence_id: str
    observation_ids: list[str] = Field(min_length=1)
    resident_id: str
    timestamp: TimezoneDatetime
    risk_domain: RiskDomain
    evidence_type: str = Field(
        json_schema_extra={
            "enum": ALL_EVIDENCE_TYPES,
            "x-internal-only": sorted(INTERNAL_EVIDENCE_TYPES),
        }
    )
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
        validate_evidence_type(self.risk_domain, self.evidence_type)
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
