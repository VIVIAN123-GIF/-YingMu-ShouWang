import os
import secrets

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.schemas.intervention_result import (FamilyFeedbackCreate, InterventionResult,
                                                 InterventionResultCreate)
from backend.schemas.risk_event import EventDetailResponse, RiskEvent
from backend.service.event_service import (create_intervention_result, event_detail, intervene,
                                           list_events, record_feedback)
from backend.schemas.agent_explanation import (
    AgentExplanationEnqueueResponse,
    AgentExplanationJobResponse,
)
from backend.service.agent_explanation_job_service import (
    enqueue_event_explanation,
    job_dict,
    latest_event_explanation,
)
from backend.service.errors import ServiceError
from backend.service.forewarning_service import event_forewarning
from contracts.v1.forewarning import ForewarningSnapshot

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/{event_id}/forewarning", response_model=list[ForewarningSnapshot])
async def get_event_forewarning(event_id: str, db: AsyncSession = Depends(get_db)):
    return await event_forewarning(db, event_id)

@router.get("", response_model=list[RiskEvent])
async def get_events(resident_id: str | None = Query(default=None),
                     db: AsyncSession = Depends(get_db)):
    return await list_events(db, resident_id)

@router.get("/{event_id}", response_model=EventDetailResponse)
async def get_event(event_id: str, db: AsyncSession = Depends(get_db)):
    return await event_detail(db, event_id)

@router.post("/{event_id}/results", response_model=InterventionResult,
             status_code=status.HTTP_201_CREATED)
async def post_result(event_id: str, payload: InterventionResultCreate, response: Response,
                      db: AsyncSession = Depends(get_db)):
    result, idempotent = await create_intervention_result(db, event_id, payload)
    response.status_code = 200 if idempotent else 201
    return result

@router.post("/{event_id}/feedback", response_model=InterventionResult,
             status_code=status.HTTP_201_CREATED)
async def post_feedback(event_id: str, payload: FamilyFeedbackCreate, response: Response,
                        db: AsyncSession = Depends(get_db)):
    result, idempotent = await record_feedback(db, event_id, payload)
    response.status_code = 200 if idempotent else 201
    return result

@router.post("/{event_id}/intervene", response_model=InterventionResult)
async def post_intervene(event_id: str, db: AsyncSession = Depends(get_db)):
    return await intervene(db, event_id)


@router.get("/{event_id}/explanation", response_model=AgentExplanationJobResponse)
async def get_explanation(event_id: str, db: AsyncSession = Depends(get_db)):
    return await latest_event_explanation(db, event_id)


@router.post(
    "/{event_id}/explanation",
    response_model=AgentExplanationEnqueueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_explanation(
    event_id: str,
    response: Response,
    x_control_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    control_token = os.getenv("YINGMU_CONTROL_TOKEN", "")
    if not control_token:
        raise ServiceError(503, "CONTROL_TOKEN_NOT_CONFIGURED", "control token is not configured")
    if not x_control_token or not secrets.compare_digest(x_control_token, control_token):
        raise ServiceError(403, "CONTROL_FORBIDDEN", "valid X-Control-Token is required")
    job, created = await enqueue_event_explanation(db, event_id)
    response.status_code = 201 if created else 200
    return {"job": job_dict(job), "created": created}
