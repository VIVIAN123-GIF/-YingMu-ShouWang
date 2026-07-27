from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.schemas.risk_event import EventDetailResponse
from backend.service.event_service import event_detail

router = APIRouter(prefix="/events", tags=["events"])

@router.get("/{event_id}", response_model=EventDetailResponse)
async def get_event(event_id: str, db: AsyncSession = Depends(get_db)):
    return await event_detail(db, event_id)
