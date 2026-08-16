from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.schemas.asset import Asset, AssetCreate
from backend.service.asset_service import create_asset, get_asset

router = APIRouter(prefix="/assets", tags=["assets"])


@router.post("", response_model=Asset, status_code=status.HTTP_201_CREATED)
async def post_asset(payload: AssetCreate, response: Response, db: AsyncSession = Depends(get_db)):
    result, idempotent = await create_asset(db, payload)
    response.status_code = 200 if idempotent else 201
    return result


@router.get("/{asset_id}", response_model=Asset)
async def read_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    return await get_asset(db, asset_id)
