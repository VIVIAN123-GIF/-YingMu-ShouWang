from typing import Literal

from pydantic import BaseModel

from backend.schemas.common import SourceMode, TimezoneDatetime


class BaselineMetric(BaseModel):
    median: float | None
    mad: float | None
    sample_count: int
    distinct_days: int
    status: Literal["INSUFFICIENT", "PROVISIONAL", "STABLE"]


class BaselineProgress(BaseModel):
    observed_days: int
    provisional_target_days: int = 3
    stable_target_days: int = 7
    lookback_days: int = 30


class BaselineProvenance(BaseModel):
    device_ref: str
    device_model: str
    camera_position_id: str


class ResidentBaselineResponse(BaseModel):
    resident_id: str
    as_of: TimezoneDatetime
    ruleset_version: str
    baselines: dict[str, BaselineMetric]
    overall_status: Literal["INSUFFICIENT", "PROVISIONAL", "STABLE"]
    baseline_progress: BaselineProgress
    provenance: BaselineProvenance | None
    pre_fall_summary: dict[str, object]
    source_mode: SourceMode
    simulated: bool
