"""Contracts for the v1.3-min engineering forewarning layer."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import SourceMode


class SceneZone(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    zone_id: str = Field(min_length=1, max_length=128)
    zone_type: Literal["HIGH_RISK", "SUPPORT", "OBSTACLE", "SAFE"]
    polygon_norm: list[tuple[float, float]] = Field(min_length=3)

    @field_validator("polygon_norm")
    @classmethod
    def validate_polygon(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if any(not 0.0 <= coordinate <= 1.0 for point in value for coordinate in point):
            raise ValueError("polygon coordinates must be normalized to [0, 1]")
        if len(set(value)) < 3:
            raise ValueError("polygon requires at least three unique points")
        twice_area = sum(
            left[0] * right[1] - right[0] * left[1]
            for left, right in zip(value, value[1:] + value[:1])
        )
        if abs(twice_area) <= 1e-8:
            raise ValueError("polygon area must be non-zero")
        return value


class SceneCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["scene-calibration/1.0"]
    scene_config_id: str = Field(min_length=1, max_length=128)
    camera_position_id: str = Field(min_length=1, max_length=128)
    location: str = Field(min_length=1, max_length=128)
    frame_width: int = Field(gt=0, le=16384)
    frame_height: int = Field(gt=0, le=16384)
    zones: list[SceneZone] = Field(default_factory=list)
    effective_from: datetime
    supersedes: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=512)

    @field_validator("effective_from")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("effective_from must include a timezone")
        return value

    @model_validator(mode="after")
    def unique_zone_ids(self) -> "SceneCalibration":
        ids = [zone.zone_id for zone in self.zones]
        if len(ids) != len(set(ids)):
            raise ValueError("zone_id values must be unique")
        return self


class ForewarningComponents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    human_risk: float = Field(ge=0, le=1)
    personal_deviation: float | None = Field(default=None, ge=0, le=1)
    environment_risk: float = Field(ge=0, le=1)
    interaction_risk: float = Field(ge=0, le=1)


class ForewarningHorizon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_seconds: int = Field(gt=0, le=86400)
    engineering_index: float = Field(ge=0, le=1)
    attention_level: Literal["UNKNOWN", "GREEN", "YELLOW", "ORANGE"]


class ForewarningFactor(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    factor: Literal[
        "human_instability",
        "personal_baseline_deviation",
        "environment_context",
        "human_environment_interaction",
        "data_quality_downgrade",
    ]
    contribution: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)


class ForewarningSnapshot(BaseModel):
    """An auditable engineering index, deliberately separate from RiskEvent."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["forewarning-snapshot/1.0"]
    snapshot_id: str = Field(min_length=1, max_length=160)
    resident_id: str = Field(min_length=1, max_length=128)
    evaluated_at: datetime
    phase: Literal["PERIODIC", "PRE_INTERVENTION", "POST_INTERVENTION"]
    assessment_status: Literal["VALID", "PARTIAL", "INSUFFICIENT"]
    confidence_level: Literal["LOW", "MEDIUM", "HIGH"]
    baseline_status: Literal["INSUFFICIENT", "PROVISIONAL", "STABLE"]
    components: ForewarningComponents
    instant: ForewarningHorizon
    short_30s: ForewarningHorizon
    trend_3min: ForewarningHorizon
    dominant_factors: list[ForewarningFactor] = Field(default_factory=list)
    degradation_reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)
    scene_config_id: str | None = Field(default=None, max_length=128)
    event_id: str | None = Field(default=None, max_length=128)
    intervention_result_id: str | None = Field(default=None, max_length=128)
    recommended_action: str = Field(min_length=1, max_length=512)
    ruleset_version: str = Field(min_length=1, max_length=64)
    source_mode: SourceMode
    simulated: bool

    @field_validator("evaluated_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must include a timezone")
        return value

    @model_validator(mode="after")
    def enforce_unknown_on_insufficient(self) -> "ForewarningSnapshot":
        levels = (self.instant.attention_level, self.short_30s.attention_level, self.trend_3min.attention_level)
        if self.assessment_status == "INSUFFICIENT" and any(level != "UNKNOWN" for level in levels):
            raise ValueError("insufficient assessments must use UNKNOWN attention levels")
        return self
