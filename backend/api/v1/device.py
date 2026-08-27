import secrets
import os
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Response, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.service.device_adapter import device_adapter
from backend.service.errors import ServiceError
from backend.service.snapshot_asset_service import SnapshotAssetError, persist_snapshot_asset

router = APIRouter(prefix="/device", tags=["device"])

@router.get("/status")
async def status():
    return await device_adapter.status()

@router.get("/snapshot")
async def snapshot():
    return await device_adapter.snapshot()


@router.post("/snapshot", status_code=http_status.HTTP_201_CREATED)
async def persist_snapshot(response: Response, db: AsyncSession = Depends(get_db)):
    snapshot_result = await device_adapter.capture_snapshot()
    try:
        asset, idempotent = await persist_snapshot_asset(
            db,
            snapshot_result,
            task_id=f"manual-snapshot-{uuid4().hex}",
        )
        await db.commit()
    except SnapshotAssetError as exc:
        await db.rollback()
        raise ServiceError(
            503 if exc.retryable else 422,
            exc.code,
            exc.message,
        ) from exc
    response.status_code = http_status.HTTP_200_OK if idempotent else http_status.HTTP_201_CREATED
    return {"asset": asset, "idempotent": idempotent}


@router.post("/stop")
async def stop_collection(x_control_token: str | None = Header(default=None)):
    control_token = os.getenv("YINGMU_CONTROL_TOKEN", "")
    if not control_token:
        raise ServiceError(503, "CONTROL_TOKEN_NOT_CONFIGURED",
                           "YINGMU_CONTROL_TOKEN must be configured before remote stop is enabled")
    if not x_control_token or not secrets.compare_digest(x_control_token, control_token):
        raise ServiceError(403, "CONTROL_FORBIDDEN", "only the authorized on-site service may stop collection")
    return await device_adapter.stop()
