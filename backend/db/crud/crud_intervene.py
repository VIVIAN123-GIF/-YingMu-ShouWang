from backend.db.crud.base import CRUDBase
from backend.db.models.intervention_result import InterventionResult
from pydantic import BaseModel
import datetime

class InterveneCreate(BaseModel):
    schema_version: str = "1.0"
    result_id: str
    event_id: str
    started_at: datetime.datetime
    completed_at: datetime.datetime | None
    action_type: str
    tool_name: str
    delivery_status: str
    resident_response: str | None
    family_feedback: str | None
    risk_after: float | None
    resolved: bool
    resolution_reason: str | None
    operator: str = "system"

class InterveneUpdate(BaseModel):
    completed_at: datetime.datetime | None = None
    delivery_status: str | None = None
    resident_response: str | None = None
    family_feedback: str | None = None
    risk_after: float | None = None
    resolved: bool | None = None
    resolution_reason: str | None = None

crud_intervene = CRUDBase[InterventionResult, InterveneCreate, InterveneUpdate](InterventionResult)