from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.schemas.observation import ObservationCreate, ObservationCreateResponse
from backend.service.observation_service import create_observation

router = APIRouter(prefix="/observations", tags=["observations"])

@router.post("", response_model=ObservationCreateResponse, status_code=status.HTTP_201_CREATED)
async def post_observation(payload: ObservationCreate, response: Response, db: AsyncSession = Depends(get_db)):
    observation, saved, idempotent = await create_observation(db, payload)
    response.status_code = 200 if idempotent else 201
    return {"observation": observation, "saved": saved, "idempotent": idempotent}
