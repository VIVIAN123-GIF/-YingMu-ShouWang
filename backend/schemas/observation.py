from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from backend.schemas.common import Score, SourceMode, TimezoneDatetime


class Observation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    schema_version: Literal["1.0"] = "1.0"
    observation_id: str
    resident_id: str
    timestamp: TimezoneDatetime
    source: str
    feature_name: str
    feature_value: float | str | bool
    unit: str | None
    location: str | None
    confidence: Score
    data_quality: Score
    source_mode: SourceMode
    asset_id: str | None
    simulated: bool
    metadata: dict[str, Any] | None = None


class ObservationCreate(Observation):
    pass


class ObservationCreateResponse(BaseModel):
    observation: Observation
    saved: bool
    idempotent: bool
