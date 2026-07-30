from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.schemas.risk_event import RiskEvaluateRequest, RiskEvaluateResponse
from backend.service.risk_service import evaluate

router = APIRouter(prefix="/risk", tags=["risk"])

@router.post("/evaluate", response_model=RiskEvaluateResponse)
async def post_evaluate(payload: RiskEvaluateRequest, db: AsyncSession = Depends(get_db)):
    return await evaluate(db, payload.resident_id, payload.evaluated_at)
