"""Frozen handoff contract for Ezviz snapshot capture results."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from .models import SourceMode


class PlatformSnapshotResult(BaseModel):
    """Internal platform-to-backend result; temporary_url is never browser-facing."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    schema_version: Literal["platform-snapshot/1.0"]
    request_id: StrictStr = Field(min_length=3, max_length=128)
    device_ref: StrictStr = Field(
        min_length=8,
        max_length=72,
        pattern=r"^device-[A-Za-z0-9_-]+$",
    )
    channel_no: StrictInt = Field(ge=1)
    captured_at: datetime
    source_mode: Literal[SourceMode.LIVE_DEVICE, SourceMode.MOCK]
    simulated: StrictBool
    temporary_url: HttpUrl | None = Field(json_schema_extra={"writeOnly": True})
    expires_at: datetime | None
    provider_latency_ms: StrictInt = Field(ge=0)

    @field_validator("captured_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("platform snapshot timestamps must include timezone offset")
        return value

    @model_validator(mode="after")
    def validate_source_semantics(self) -> "PlatformSnapshotResult":
        if self.source_mode == SourceMode.LIVE_DEVICE:
            if self.simulated:
                raise ValueError("LIVE_DEVICE snapshot cannot be simulated")
            if self.temporary_url is None:
                raise ValueError("LIVE_DEVICE snapshot requires an internal temporary_url")
        elif not self.simulated:
            raise ValueError("MOCK snapshot must set simulated=true")
        if self.expires_at is not None and self.expires_at <= self.captured_at:
            raise ValueError("expires_at must be later than captured_at")
        return self


class PlatformVideoSource(BaseModel):
    """Internal live-stream source used only while recording a private video Asset."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    schema_version: Literal["platform-video/1.0"]
    request_id: StrictStr = Field(min_length=3, max_length=128)
    device_ref: StrictStr = Field(min_length=8, max_length=72, pattern=r"^device-[A-Za-z0-9_-]+$")
    channel_no: StrictInt = Field(ge=1)
    captured_at: datetime
    source_mode: Literal[SourceMode.LIVE_DEVICE]
    simulated: StrictBool
    temporary_url: HttpUrl = Field(json_schema_extra={"writeOnly": True})
    expires_at: datetime | None
    provider_latency_ms: StrictInt = Field(ge=0)

    @field_validator("captured_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("platform video timestamps must include timezone offset")
        return value

    @model_validator(mode="after")
    def validate_source_semantics(self) -> "PlatformVideoSource":
        if self.simulated:
            raise ValueError("LIVE_DEVICE video cannot be simulated")
        if self.expires_at is not None and self.expires_at <= self.captured_at:
            raise ValueError("video source expires_at must be later than captured_at")
        return self
