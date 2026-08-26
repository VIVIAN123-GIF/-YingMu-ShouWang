"""Frozen structured contracts for event explanation by the LLM agent."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictStr,
    field_validator,
    model_validator,
)

from .models import RiskLevel, TimeHorizon


NonEmptyText = Annotated[StrictStr, Field(min_length=1)]


class AgentBaselineStatus(str, Enum):
    INSUFFICIENT = "INSUFFICIENT"
    PROVISIONAL = "PROVISIONAL"
    STABLE = "STABLE"
    UNAVAILABLE = "UNAVAILABLE"


class AgentInterventionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class PlatformCapability(str, Enum):
    EZVIZ_DEVICE_STATUS = "EZVIZ_DEVICE_STATUS"
    EZVIZ_CAPTURE = "EZVIZ_CAPTURE"
    EZVIZ_WEBHOOK = "EZVIZ_WEBHOOK"
    EZVIZ_LIVE_PLAYBACK = "EZVIZ_LIVE_PLAYBACK"
    EZVIZ_SERVER_VOICE = "EZVIZ_SERVER_VOICE"
    MOCK_VOICE = "MOCK_VOICE"
    TEXT_NOTICE = "TEXT_NOTICE"


class AgentEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_type: NonEmptyText
    explanation: NonEmptyText


class AgentForewarningSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    snapshot_id: StrictStr = Field(min_length=1, max_length=160)
    assessment_status: Literal["VALID", "PARTIAL", "INSUFFICIENT"]
    confidence_level: Literal["LOW", "MEDIUM", "HIGH"]
    baseline_status: AgentBaselineStatus
    instant_index: StrictFloat = Field(ge=0, le=1)
    short_30s_index: StrictFloat = Field(ge=0, le=1)
    trend_3min_index: StrictFloat = Field(ge=0, le=1)
    dominant_factors: list[StrictStr] = Field(default_factory=list, max_length=5)
    degradation_reasons: list[StrictStr] = Field(default_factory=list, max_length=8)


class AgentExplanationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    schema_version: Literal["agent-explanation/1.0"]
    request_id: StrictStr = Field(min_length=3, max_length=128)
    event_id: StrictStr = Field(min_length=1, max_length=128)
    resident_id: StrictStr = Field(min_length=1, max_length=128)
    risk_level: RiskLevel
    risk_score: StrictFloat
    time_horizon: TimeHorizon
    evidence: list[AgentEvidenceItem] = Field(min_length=1, max_length=12)
    baseline_status: AgentBaselineStatus
    intervention_status: AgentInterventionStatus
    verified_capabilities: list[PlatformCapability]
    unverified_capabilities: list[PlatformCapability]
    forewarning: AgentForewarningSummary | None = None

    @field_validator("risk_score")
    @classmethod
    def validate_risk_score(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("risk_score must be between 0 and 1")
        return value

    @field_validator("verified_capabilities", "unverified_capabilities")
    @classmethod
    def reject_duplicate_capabilities(
        cls,
        values: list[PlatformCapability],
    ) -> list[PlatformCapability]:
        if len(values) != len(set(values)):
            raise ValueError("capability lists cannot contain duplicates")
        return values

    @model_validator(mode="after")
    def reject_capability_overlap(self) -> "AgentExplanationRequest":
        overlap = set(self.verified_capabilities) & set(self.unverified_capabilities)
        if overlap:
            raise ValueError("verified and unverified capabilities cannot overlap")
        return self


class AgentExplanationResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    schema_version: Literal["agent-explanation/1.0"]
    request_id: StrictStr = Field(min_length=3, max_length=128)
    event_id: StrictStr = Field(min_length=1, max_length=128)
    summary: StrictStr = Field(min_length=1, max_length=200)
    reasoning_points: list[StrictStr] = Field(min_length=1, max_length=4)
    recommended_action_text: StrictStr = Field(min_length=1, max_length=200)
    capability_notice: StrictStr = Field(min_length=1, max_length=240)
    generated_by: StrictStr = Field(min_length=1, max_length=64)
    fallback_used: StrictBool

    @field_validator("reasoning_points")
    @classmethod
    def validate_reasoning_points(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 160 for value in values):
            raise ValueError("reasoning points must contain 1 to 160 characters")
        if len(values) != len(set(values)):
            raise ValueError("reasoning points cannot contain duplicates")
        return values
