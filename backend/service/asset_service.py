from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Asset
from backend.schemas.asset import AssetCreate
from backend.service.errors import ServiceError
from backend.service.serialization import aware


def asset_dict(row: Asset):
    return {"asset_id": row.asset_id, "title": row.title, "source_mode": row.source_mode,
            "simulated": row.simulated, "stream_url": row.stream_url,
            "fallback_url": row.fallback_url, "fallback_kind": row.fallback_kind,
            "available": row.available, "verification_status": row.verification_status,
            "captured_at": aware(row.captured_at), "notice": row.notice,
            "device_ref": row.device_ref, "device_model": row.device_model,
            "camera_position_id": row.camera_position_id,
            "authorization_status": row.authorization_status,
            "authorization_record_id": row.authorization_record_id,
            "retention_until": aware(row.retention_until) if row.retention_until else None,
            "content_sha256": row.content_sha256, "content_type": row.content_type,
            "byte_size": row.byte_size}


async def get_asset(db: AsyncSession, asset_id: str):
    row = (await db.execute(select(Asset).where(Asset.asset_id == asset_id))).scalar_one_or_none()
    if not row:
        raise ServiceError(404, "ASSET_NOT_FOUND", "authorized asset does not exist")
    return asset_dict(row)


async def create_asset(
    db: AsyncSession,
    payload: AssetCreate,
    *,
    storage_key: str | None = None,
    commit: bool = True,
):
    row = (await db.execute(select(Asset).where(Asset.asset_id == payload.asset_id))).scalar_one_or_none()
    if row:
        if asset_dict(row) != payload.model_dump():
            raise ServiceError(409, "ASSET_ID_CONFLICT", "asset_id exists with different content")
        if storage_key is not None and row.storage_key != storage_key:
            raise ServiceError(409, "ASSET_STORAGE_CONFLICT", "asset_id uses a different private object")
        return asset_dict(row), True
    row = Asset(**payload.model_dump(), storage_key=storage_key)
    db.add(row)
    if commit:
        await db.commit()
    else:
        await db.flush()
    await db.refresh(row)
    return asset_dict(row), False
