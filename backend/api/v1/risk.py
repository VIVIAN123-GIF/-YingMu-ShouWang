from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.schemas.risk_event import RiskEvaluateRequest, RiskEvaluateResponse
from backend.schemas.risk_review import RiskReviewItem
from backend.service.risk_service import evaluate, list_risk_reviews
from backend.service.rule_log_service import log_rule

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/reviews", response_model=list[RiskReviewItem])
async def get_reviews(
    resident_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await list_risk_reviews(db, resident_id=resident_id, limit=limit)

@router.post("/evaluate", response_model=RiskEvaluateResponse)
async def post_evaluate(payload: RiskEvaluateRequest, db: AsyncSession = Depends(get_db)):
    result = await evaluate(
        db,
        payload.resident_id,
        payload.evaluated_at,
        risk_domain=payload.risk_domain.value,
    )
    # Persisted RuleTrace is the only log payload; do not rebuild semantics here.
    log_rule(result["trace"])
    return result
