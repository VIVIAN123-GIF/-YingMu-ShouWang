from typing import Literal

from pydantic import BaseModel

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
    device_ref: str | None = None
    device_model: str | None = None
    camera_position_id: str | None = None
    authorization_status: Literal["PENDING", "AUTHORIZED", "REVOKED"] = "PENDING"
    authorization_record_id: str | None = None
    retention_until: TimezoneDatetime | None = None


class AssetCreate(Asset):
    pass
