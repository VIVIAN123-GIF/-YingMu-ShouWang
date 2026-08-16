from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.service.alarm_task_service import list_alarm_tasks


router = APIRouter(prefix="/alarms", tags=["alarms"])


@router.get("/processing")
async def get_alarm_processing(
    resident_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await list_alarm_tasks(db, resident_id=resident_id, limit=limit)
