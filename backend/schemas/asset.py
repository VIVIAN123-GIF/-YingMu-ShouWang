from pydantic import BaseModel, Field, model_validator

from backend.schemas.common import SourceMode, TimezoneDatetime


class Asset(BaseModel):
    asset_id: str
    title: str
    source_mode: SourceMode
    simulated: bool
    stream_url: str | None
    fallback_url: str | None
    fallback_kind: str
    available: bool
    verification_status: str
    captured_at: TimezoneDatetime
    notice: str
    # Recorded-replay provenance is required for C6c acceptance.  These fields
    # must survive the API round trip so an idempotent asset submission can be
    # compared with the persisted record.
    device_ref: str | None = None
    device_model: str | None = None
    camera_position_id: str | None = None
    authorization_status: str = "PENDING"
    authorization_record_id: str | None = None
    retention_until: TimezoneDatetime | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    content_type: str | None = Field(
        default=None,
        pattern=r"^(image/(jpeg|png|webp)|video/mp4)$",
    )
    byte_size: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_complete_content_metadata(self):
        values = (self.content_sha256, self.content_type, self.byte_size)
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("asset content metadata must be provided together")
        return self


class AssetCreate(Asset):
    pass
