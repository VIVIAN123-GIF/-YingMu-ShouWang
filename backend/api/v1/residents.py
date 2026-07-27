from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.schemas.baseline import ResidentBaselineResponse
from backend.service.baseline_service import memory_store

router = APIRouter(prefix="/residents", tags=["residents"])

@router.get("/{resident_id}/baseline", response_model=ResidentBaselineResponse)
async def get_baseline(resident_id: str, as_of: datetime | None = Query(default=None),
                       db: AsyncSession = Depends(get_db)):
    current = as_of or datetime.now(timezone(timedelta(hours=8)))
    if current.tzinfo is None:
        from backend.service.errors import ServiceError
        raise ServiceError(422, "TIMEZONE_REQUIRED", "as_of must include timezone")
    return await memory_store.baseline(db, resident_id, current)
