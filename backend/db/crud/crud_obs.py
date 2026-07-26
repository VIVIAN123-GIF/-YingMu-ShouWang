from backend.db.crud.base import CRUDBase
from backend.db.models.observation import Observation
from pydantic import BaseModel, ConfigDict, Field
import datetime


class ObsCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: str = "1.0"
    observation_id: str
    resident_id: str
    timestamp: datetime.datetime
    source: str
    feature_name: str
    feature_value: str
    unit: str | None = None
    location: str | None = None
    confidence: float
    data_quality: float
    source_mode: str
    asset_id: str | None = None
    simulated: bool
    extra_metadata: str | None = Field(default=None, alias="metadata")
    device_sn: str


class ObsUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: str | None = None
    resident_id: str | None = None
    timestamp: datetime.datetime | None = None
    source: str | None = None
    feature_name: str | None = None
    feature_value: str | None = None
    unit: str | None = None
    location: str | None = None
    confidence: float | None = None
    data_quality: float | None = None
    source_mode: str | None = None
    asset_id: str | None = None
    simulated: bool | None = None
    extra_metadata: str | None = Field(default=None, alias="metadata")
    device_sn: str | None = None


crud_observation = CRUDBase[Observation, ObsCreate, ObsUpdate](Observation)