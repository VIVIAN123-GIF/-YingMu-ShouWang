from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.schemas.common import Score, SourceMode, TimezoneDatetime


class InterventionResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    schema_version: Literal["1.0"] = "1.0"
    result_id: str
    event_id: str
    started_at: TimezoneDatetime
    completed_at: TimezoneDatetime | None
    action_type: str
    tool_name: str
    delivery_status: Literal["SUCCESS", "FAILED", "RETRYING"]
    resident_response: str | None
    family_feedback: str | None
    risk_after: Score | None
    resolved: bool
    resolution_reason: str | None
    operator: str
    source_mode: SourceMode
    simulated: bool


class InterventionResultCreate(InterventionResult):
    pass


class FamilyFeedbackCreate(BaseModel):
    feedback_id: str
    feedback_type: str
    value: str
    operator: Literal["family", "staff"] = "family"
