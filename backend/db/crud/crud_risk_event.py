from backend.db.crud.base import CRUDBase
from backend.db.models.risk_event import RiskEvent
from pydantic import BaseModel
import datetime

class RiskEventCreate(BaseModel):
    schema_version: str = "1.0"
    event_id: str
    resident_id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    primary_domain: str
    related_domains: str
    risk_level: str
    risk_score: float
    evidence_ids: str
    evidence_summary: str
    time_horizon: str
    recommended_action: str
    intervention_policy: str
    status: str = "OPEN"
    ruleset_version: str = "ruleset-v1.0"

class RiskEventUpdate(BaseModel):
    updated_at: datetime.datetime | None = None
    risk_level: str | None = None
    risk_score: float | None = None
    status: str | None = None
    recommended_action: str | None = None

crud_risk_event = CRUDBase[RiskEvent, RiskEventCreate, RiskEventUpdate](RiskEvent)