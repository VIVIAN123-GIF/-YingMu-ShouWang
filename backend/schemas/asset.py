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


class AssetCreate(Asset):
    pass
