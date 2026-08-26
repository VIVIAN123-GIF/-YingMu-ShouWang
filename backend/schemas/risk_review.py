from typing import Literal

from pydantic import BaseModel

from backend.schemas.common import SourceMode, TimezoneDatetime


class RiskReviewItem(BaseModel):
    schema_version: Literal["risk-review/1.0"] = "risk-review/1.0"
    trace_id: str
    resident_id: str
    evidence_id: str
    evidence_type: str
    explanation: str
    evaluated_at: TimezoneDatetime
    risk_level: Literal["UNKNOWN", "YELLOW"]
    matched_rule: str
    ruleset_version: str
    source_mode: SourceMode
    simulated: bool
    review_required: Literal[True] = True
