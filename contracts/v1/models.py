"""Canonical v1.0 data objects used by algorithms, the agent and the UI.

The models are deliberately strict: an unknown field is rejected so that a
feature module cannot silently introduce a second contract.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator

from .evidence_types import ALL_EVIDENCE_TYPES, INTERNAL_EVIDENCE_TYPES, validate_evidence_type


SCHEMA_VERSION = "1.0"
FeatureValue = Union[StrictFloat, StrictInt, StrictStr, StrictBool]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, str_strip_whitespace=True)

    @field_validator("schema_version", check_fields=False)
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
        return value


def _aware_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


def _aware_timestamp_optional(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _aware_timestamp(value)


def _score(value: float) -> float:
    if not 0 <= value <= 1:
        raise ValueError("score must be between 0 and 1")
    return value


def _nullable_non_empty(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("nullable text must use null instead of an empty string")
    return value


class RiskDomain(str, Enum):
    FALL = "FALL"
    MENTAL = "MENTAL"
    FRAUD = "FRAUD"
    SYSTEM = "SYSTEM"


class RiskLevel(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    INTERVENING = "INTERVENING"
    OBSERVING = "OBSERVING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    FALSE_ALARM = "FALSE_ALARM"


class SourceMode(str, Enum):
    LIVE_DEVICE = "LIVE_DEVICE"
    RECORDED_REPLAY = "RECORDED_REPLAY"
    PUBLIC_DATASET = "PUBLIC_DATASET"
    MOCK = "MOCK"


class TimeScale(str, Enum):
    SHORT = "SHORT"
    MEDIUM = "MEDIUM"
    LONG = "LONG"


class TimeHorizon(str, Enum):
    TREND = "TREND"
    TODAY = "TODAY"
    IMMINENT = "IMMINENT"


class Operator(str, Enum):
    SYSTEM = "system"
    FAMILY = "family"
    STAFF = "staff"


class DeliveryStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class Observation(ContractModel):
    schema_version: Literal["1.0"]
    observation_id: str = Field(min_length=1)
    resident_id: str = Field(min_length=1)
    timestamp: datetime
    source: str = Field(min_length=1)
    feature_name: str = Field(min_length=1)
    feature_value: FeatureValue
    unit: str | None
    location: str | None
    confidence: StrictFloat
    data_quality: StrictFloat
    source_mode: SourceMode
    asset_id: str | None
    simulated: StrictBool
    metadata: dict[str, Any] = Field(default_factory=dict)

    _timestamp = field_validator("timestamp")(_aware_timestamp)
    _confidence = field_validator("confidence")(classmethod(lambda cls, value: _score(value)))
    _quality = field_validator("data_quality")(classmethod(lambda cls, value: _score(value)))
    _unit = field_validator("unit")(_nullable_non_empty)
    _location = field_validator("location")(_nullable_non_empty)
    _asset_id = field_validator("asset_id")(_nullable_non_empty)


class Evidence(ContractModel):
    schema_version: Literal["1.0"]
    evidence_id: str = Field(min_length=1)
    observation_ids: list[str] = Field(min_length=1)
    resident_id: str = Field(min_length=1)
    timestamp: datetime
    risk_domain: RiskDomain
    evidence_type: str = Field(
        min_length=1,
        json_schema_extra={
            "enum": ALL_EVIDENCE_TYPES,
            "x-internal-only": sorted(INTERNAL_EVIDENCE_TYPES),
        },
    )
    severity: StrictFloat
    confidence: StrictFloat
    data_quality: StrictFloat
    baseline_value: StrictFloat | StrictInt | None
    current_value: StrictFloat | StrictInt | None
    baseline_deviation: StrictFloat | StrictInt | None
    time_scale: TimeScale
    location: str | None
    explanation: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    source_mode: SourceMode
    simulated: StrictBool

    _timestamp = field_validator("timestamp")(_aware_timestamp)
    _severity = field_validator("severity")(classmethod(lambda cls, value: _score(value)))
    _confidence = field_validator("confidence")(classmethod(lambda cls, value: _score(value)))
    _quality = field_validator("data_quality")(classmethod(lambda cls, value: _score(value)))
    _location = field_validator("location")(_nullable_non_empty)

    @field_validator("observation_ids")
    @classmethod
    def validate_observation_ids(cls, values: list[str]) -> list[str]:
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("observation_ids must contain non-empty strings")
        if len(values) != len(set(values)):
            raise ValueError("observation_ids cannot contain duplicates")
        return values

    @model_validator(mode="after")
    def validate_frozen_evidence_type(self) -> "Evidence":
        validate_evidence_type(self.risk_domain, self.evidence_type)
        return self


class EvidenceSummary(ContractModel):
    evidence_id: str = Field(min_length=1)
    evidence_type: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class RiskEvent(ContractModel):
    schema_version: Literal["1.0"]
    event_id: str = Field(min_length=1)
    resident_id: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime
    primary_domain: RiskDomain
    related_domains: list[RiskDomain]
    risk_level: RiskLevel
    risk_score: StrictFloat
    evidence_ids: list[str] = Field(min_length=1)
    evidence_summary: list[EvidenceSummary] = Field(min_length=1)
    time_horizon: TimeHorizon
    recommended_action: str = Field(min_length=1)
    intervention_policy: str = Field(min_length=1)
    status: EventStatus
    ruleset_version: str = Field(min_length=1)
    source_mode: SourceMode
    simulated: StrictBool

    _created_at = field_validator("created_at")(_aware_timestamp)
    _updated_at = field_validator("updated_at")(_aware_timestamp)
    _risk_score = field_validator("risk_score")(classmethod(lambda cls, value: _score(value)))


class InterventionResult(ContractModel):
    schema_version: Literal["1.0"]
    result_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    started_at: datetime
    completed_at: datetime | None
    action_type: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    delivery_status: DeliveryStatus
    resident_response: str | None
    family_feedback: str | None
    risk_after: StrictFloat | None
    resolved: StrictBool
    resolution_reason: str | None
    operator: Operator
    source_mode: SourceMode
    simulated: StrictBool

    _started_at = field_validator("started_at")(_aware_timestamp)
    _completed_at = field_validator("completed_at")(_aware_timestamp_optional)
    _risk_after = field_validator("risk_after")(classmethod(lambda cls, value: None if value is None else _score(value)))
    _resident_response = field_validator("resident_response")(_nullable_non_empty)
    _family_feedback = field_validator("family_feedback")(_nullable_non_empty)
    _resolution_reason = field_validator("resolution_reason")(_nullable_non_empty)
