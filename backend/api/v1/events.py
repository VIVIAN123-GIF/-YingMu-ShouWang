from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.schemas.intervention_result import (FamilyFeedbackCreate, InterventionResult,
                                                 InterventionResultCreate)
from backend.schemas.risk_event import EventDetailResponse, RiskEvent
from backend.service.event_service import (create_intervention_result, event_detail, intervene,
                                           list_events, record_feedback)

router = APIRouter(prefix="/events", tags=["events"])

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
