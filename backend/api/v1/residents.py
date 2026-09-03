from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.schemas.baseline import ResidentBaselineResponse
from backend.schemas.field_run import FieldRunSummary
from backend.service.baseline_service import memory_store
from backend.service.field_run_service import list_live_field_runs
from backend.service.forewarning_service import latest_forewarning, list_forewarning
from contracts.v1.forewarning import ForewarningSnapshot

router = APIRouter(prefix="/residents", tags=["residents"])


@router.get("/{resident_id}/field-runs", response_model=list[FieldRunSummary])
async def get_field_runs(
    resident_id: str,
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    return await list_live_field_runs(db, resident_id, limit=limit)

@router.get("/{resident_id}/baseline", response_model=ResidentBaselineResponse)
async def get_baseline(resident_id: str, as_of: datetime | None = Query(default=None),
                       db: AsyncSession = Depends(get_db)):
    current = as_of or datetime.now(timezone(timedelta(hours=8)))
    if current.tzinfo is None:
        from backend.service.errors import ServiceError
        raise ServiceError(422, "TIMEZONE_REQUIRED", "as_of must include timezone")
    return await memory_store.baseline(db, resident_id, current)


@router.get("/{resident_id}/forewarning/latest", response_model=ForewarningSnapshot | None)
async def get_latest_forewarning(resident_id: str, db: AsyncSession = Depends(get_db)):
    return await latest_forewarning(db, resident_id)


@router.get("/{resident_id}/forewarning", response_model=list[ForewarningSnapshot])
async def get_forewarning_history(
    resident_id: str,
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    for value in (from_time, to_time):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            from backend.service.errors import ServiceError
            raise ServiceError(422, "TIMEZONE_REQUIRED", "forewarning time filters must include timezone")
    return await list_forewarning(db, resident_id, from_time=from_time, to_time=to_time, limit=limit)
