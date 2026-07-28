from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.service.report_service import weekly_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/weekly")
async def get_weekly_report(resident_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    return await weekly_report(db, resident_id)
