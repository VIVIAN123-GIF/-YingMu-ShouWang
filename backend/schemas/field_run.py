from typing import Any, Literal

from pydantic import BaseModel

from backend.schemas.common import EventStatus, RiskLevel, Score, TimezoneDatetime
from backend.schemas.evidence import Evidence
from backend.schemas.intervention_result import InterventionResult
from backend.schemas.observation import Observation
from contracts.v1.forewarning import ForewarningSnapshot


class FieldRunMetric(BaseModel):
    detected: bool
    value: float | bool | str | None = None
    unit: str | None = None
    data_quality: Score | None = None
    evidence_id: str | None = None
    observation_id: str | None = None


class FieldRunEvent(BaseModel):
    event_id: str
    risk_level: RiskLevel
    risk_score: Score
    status: EventStatus
    recommended_action: str
    ruleset_version: str


class FieldRunSummary(BaseModel):
    schema_version: Literal["field-run/1.0"] = "field-run/1.0"
    run_id: str
    resident_id: str
    captured_at: TimezoneDatetime
    source_mode: Literal["LIVE_DEVICE"] = "LIVE_DEVICE"
    simulated: Literal[False] = False
    device_ref: str
    device_model: str | None = None
    camera_position_id: str | None = None
    authorization_ref: str
    scene_config_id: str | None = None
    task_status: str
    task_result: dict[str, Any]
    risk_level: Literal["UNKNOWN", "GREEN", "YELLOW", "ORANGE", "RED"]
    risk_score: Score
    current_risk_level: Literal["UNKNOWN", "GREEN", "YELLOW", "ORANGE", "RED"]
    current_risk_score: Score
    data_quality: Score | None = None
    metrics: dict[Literal["rapid_rise", "trunk_sway"], FieldRunMetric]
    event: FieldRunEvent | None = None
    evidences: list[Evidence]
    observations: list[Observation]
    rule_traces: list[dict[str, Any]]
    interventions: list[InterventionResult]
    forewarning_snapshots: list[ForewarningSnapshot]
