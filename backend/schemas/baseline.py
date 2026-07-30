from typing import Literal

from pydantic import BaseModel

from backend.schemas.common import SourceMode, TimezoneDatetime


class BaselineMetric(BaseModel):
    median: float | None
    mad: float | None
    sample_count: int
    distinct_days: int
    status: Literal["INSUFFICIENT", "PROVISIONAL", "STABLE"]


class ResidentBaselineResponse(BaseModel):
    resident_id: str
    as_of: TimezoneDatetime
    ruleset_version: str
    baselines: dict[str, BaselineMetric]
    source_mode: SourceMode
    simulated: bool
