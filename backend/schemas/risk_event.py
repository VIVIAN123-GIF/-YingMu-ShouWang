from typing import Any, Literal

from pydantic import BaseModel

from backend.schemas.common import EventStatus, RiskDomain, RiskLevel, Score, SourceMode, TimezoneDatetime
from backend.schemas.evidence import Evidence
from backend.schemas.observation import Observation
from contracts.v1.forewarning import ForewarningSnapshot


class RiskEvent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: str
    resident_id: str
    created_at: TimezoneDatetime
    updated_at: TimezoneDatetime
    primary_domain: RiskDomain
    related_domains: list[RiskDomain]
    risk_level: RiskLevel
    risk_score: Score
    evidence_ids: list[str]
    evidence_summary: list[Any]
    time_horizon: Literal["TREND", "TODAY", "IMMINENT"]
    recommended_action: str
    intervention_policy: str
    status: EventStatus
    ruleset_version: str
    source_mode: SourceMode
    simulated: bool


class RiskEvaluateRequest(BaseModel):
    resident_id: str
    evaluated_at: TimezoneDatetime
    risk_domain: RiskDomain = RiskDomain.FALL


class RiskEvaluateResponse(BaseModel):
    risk_level: RiskLevel
    event_created: bool
    event: RiskEvent | None
    matched_rule: str
    ruleset_version: str
    forewarning_snapshot: ForewarningSnapshot | None = None


class EventDetailResponse(RiskEvent):
    evidences: list[Evidence]
    observations: list[Observation]
    rule_traces: list[dict[str, Any]]
    interventions: list[dict[str, Any]]
