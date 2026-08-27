import secrets

from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import YINGMU_MEDIA_ACCESS_TOKEN
from backend.db.database import get_db
from backend.schemas.asset import Asset, AssetCreate
from backend.service.asset_service import create_asset, get_asset, get_private_image_content
from backend.service.errors import ServiceError

router = APIRouter(prefix="/assets", tags=["assets"])


@router.post("", response_model=Asset, status_code=status.HTTP_201_CREATED)
async def post_asset(payload: AssetCreate, response: Response, db: AsyncSession = Depends(get_db)):
    result, idempotent = await create_asset(db, payload)
    response.status_code = 200 if idempotent else 201
    return result


@router.get("/{asset_id}", response_model=Asset)
async def read_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    return await get_asset(db, asset_id)


@router.get("/{asset_id}/content", response_class=FileResponse)
async def read_private_asset_content(
    asset_id: str,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    expected = YINGMU_MEDIA_ACCESS_TOKEN
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not expected:
        raise ServiceError(503, "MEDIA_ACCESS_TOKEN_NOT_CONFIGURED", "media access is not configured")
    if not authorization or not secrets.compare_digest(supplied, expected):
        raise ServiceError(401, "MEDIA_ACCESS_FORBIDDEN", "a valid media access token is required")
    path, content_type = await get_private_image_content(db, asset_id)
    return FileResponse(
        path,
        media_type=content_type,
        filename=f"{asset_id}{path.suffix}",
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
