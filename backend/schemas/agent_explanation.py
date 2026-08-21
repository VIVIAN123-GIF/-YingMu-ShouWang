from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from backend.schemas.common import TimezoneDatetime
from contracts.v1.agent import AgentExplanationResponse


class AgentExplanationJobResponse(BaseModel):
    request_id: str | None = None
    event_id: str
    event_version_hash: str | None = None
    status: Literal[
        "NOT_REQUESTED", "PENDING", "PROCESSING", "RETRY",
        "SUCCESS", "FALLBACK", "FAILED",
    ]
    explanation: AgentExplanationResponse | None = None
    generated_by: str | None = None
    fallback_used: bool | None = None
    attempt_count: int = 0
    error_code: str | None = None
    created_at: TimezoneDatetime | None = None
    completed_at: TimezoneDatetime | None = None


class AgentExplanationEnqueueResponse(BaseModel):
    job: AgentExplanationJobResponse
    created: bool
