"""Frozen contracts at the backend-to-algorithm boundary."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import Evidence, Observation, SourceMode


class AlgorithmModule(str, Enum):
    GAIT = "GAIT"
    TRAJECTORY = "TRAJECTORY"
    LANGUAGE = "LANGUAGE"


class MediaType(str, Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"


class AdapterStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_EVIDENCE = "NO_EVIDENCE"
    LOW_QUALITY = "LOW_QUALITY"
    FAILED = "FAILED"


class AlgorithmJob(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["algorithm-job/1.0"]
    job_id: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=160)
    resident_id: str = Field(min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=160)
    media_type: MediaType
    media_locator: str = Field(min_length=1)
    captured_at: datetime
    source_mode: SourceMode
    simulated: bool
    location: str = Field(min_length=1, max_length=128)
    camera_position_id: str = Field(min_length=1, max_length=128)
    scene_config_id: str = Field(min_length=1, max_length=128)
    requested_modules: list[AlgorithmModule] = Field(min_length=1)
    deadline_ms: int = Field(default=8000, ge=100, le=120000)

    @field_validator("captured_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value

    @field_validator("media_locator")
    @classmethod
    def reject_credentials_in_locator(cls, value: str) -> str:
        normalized = value.lower().replace("-", "_")
        forbidden = ("accesstoken", "access_token", "appsecret", "api_key", "token=")
        if any(marker in normalized for marker in forbidden):
            raise ValueError("media_locator must not contain platform credentials")
        return value

    @field_validator("requested_modules")
    @classmethod
    def reject_duplicate_modules(cls, value: list[AlgorithmModule]) -> list[AlgorithmModule]:
        if len(value) != len(set(value)):
            raise ValueError("requested_modules cannot contain duplicates")
        return value


class AdapterError(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=256)
    retryable: bool = False


class ResidentResponseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: Literal["STABLE", "HELP", "UNCERTAIN"]
    confidence: float = Field(ge=0, le=1)
    transcript_observation_id: str = Field(min_length=1, max_length=160)


class AdapterBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["adapter-batch/1.0"]
    job_id: str = Field(min_length=1, max_length=160)
    module: AlgorithmModule
    adapter_version: str = Field(min_length=1, max_length=128)
    status: AdapterStatus
    started_at: datetime
    completed_at: datetime
    observations: list[Observation] = Field(default_factory=list)
    evidences: list[Evidence] = Field(default_factory=list)
    resident_response_candidate: ResidentResponseCandidate | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    error: AdapterError | None = None

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("adapter timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_status_payload(self) -> "AdapterBatch":
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.status == AdapterStatus.FAILED:
            if self.error is None:
                raise ValueError("FAILED batches require error")
            if self.observations or self.evidences:
                raise ValueError("FAILED batches cannot contain fabricated outputs")
        elif self.error is not None:
            raise ValueError("only FAILED batches may contain error")
        if self.status == AdapterStatus.NO_EVIDENCE:
            if not self.observations or self.evidences:
                raise ValueError("NO_EVIDENCE requires observations and no evidences")
        if self.status == AdapterStatus.LOW_QUALITY:
            quality_types = {
                "tracking_lost", "audio_quality_low", "camera_occlusion",
                "stream_unavailable", "low_illumination", "low_light",
                "assessment_indeterminate", "quality_gate_failed",
            }
            if not self.observations or not self.evidences:
                raise ValueError("LOW_QUALITY requires quality Observations and Evidence")
            if any(item.evidence_type not in quality_types for item in self.evidences):
                raise ValueError("LOW_QUALITY may only contain frozen quality Evidence")
        if self.resident_response_candidate is not None and self.module != AlgorithmModule.LANGUAGE:
            raise ValueError("resident_response_candidate is language-only")
        return self


class AlgorithmAdapter(Protocol):
    async def run(self, job: AlgorithmJob) -> AdapterBatch:
        """Return one validated batch for the supplied job."""


IMAGE_FORBIDDEN_EVIDENCE = {
    "rapid_rise", "slow_rise", "trunk_sway", "gait_instability",
    "relative_speed_change", "posture_recovered", "high_risk_zone_entry",
    "unusual_pacing", "activity_range_decline", "room_transition_decline",
    "sit_to_stand_transition", "post_rise_lateral_drift",
    "support_base_change", "compensatory_step", "assessment_indeterminate",
}


def validate_batch_for_job(batch: AdapterBatch, job: AlgorithmJob) -> AdapterBatch:
    if batch.job_id != job.job_id:
        raise ValueError("AdapterBatch job_id does not match AlgorithmJob")
    if batch.module not in job.requested_modules:
        raise ValueError("AdapterBatch module was not requested")
    for observation in batch.observations:
        if (
            observation.resident_id != job.resident_id
            or observation.asset_id != job.asset_id
            or observation.source_mode != job.source_mode
            or observation.simulated != job.simulated
        ):
            raise ValueError("Observation does not inherit AlgorithmJob provenance")
    for evidence in batch.evidences:
        if (
            evidence.resident_id != job.resident_id
            or evidence.source_mode != job.source_mode
            or evidence.simulated != job.simulated
        ):
            raise ValueError("Evidence does not inherit AlgorithmJob provenance")
        if job.media_type == MediaType.IMAGE and evidence.evidence_type in IMAGE_FORBIDDEN_EVIDENCE:
            raise ValueError("IMAGE jobs cannot produce temporal evidence")
        observation_ids = {item.observation_id for item in batch.observations}
        if not set(evidence.observation_ids).issubset(observation_ids):
            raise ValueError("Evidence must reference Observations from the same AdapterBatch")
    if batch.resident_response_candidate is not None:
        observation_ids = {item.observation_id for item in batch.observations}
        if batch.resident_response_candidate.transcript_observation_id not in observation_ids:
            raise ValueError("resident response must reference a batch Observation")
    return batch
