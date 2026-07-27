from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.schemas.evidence import EvidenceCreate, EvidenceCreateResponse
from backend.service.evidence_service import create_evidence

router = APIRouter(prefix="/evidence", tags=["evidence"])

@router.post("", response_model=EvidenceCreateResponse, status_code=status.HTTP_201_CREATED)
async def post_evidence(payload: EvidenceCreate, request: Request, response: Response,
                        db: AsyncSession = Depends(get_db)):
    evidence, saved, idempotent, evaluation = await create_evidence(db, payload, request.state.request_id)
    response.status_code = 200 if idempotent else 201
    return {"evidence": evidence, "saved": saved, "idempotent": idempotent,
            "evaluation": {"risk_level": evaluation["risk_level"],
                           "event_created": evaluation["event_created"],
                           "event_id": evaluation["event"]["event_id"] if evaluation["event"] else None,
                           "matched_rule": evaluation["matched_rule"],
                           "ruleset_version": evaluation["ruleset_version"]}}
