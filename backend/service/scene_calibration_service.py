"""Database persistence for validated fixed-camera scene calibrations."""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import SceneCalibrationRecord, SystemConfig
from contracts.v1.forewarning import SceneCalibration


ACTIVE_SCENE_CALIBRATION_KEY = "active_scene_calibration_id"


async def upsert_scene_calibration(
    db: AsyncSession, calibration: SceneCalibration, *, make_active: bool = False,
) -> SceneCalibration:
    payload = json.dumps(calibration.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    record = (await db.execute(select(SceneCalibrationRecord).where(
        SceneCalibrationRecord.scene_config_id == calibration.scene_config_id
    ))).scalar_one_or_none()
    if record is None:
        db.add(SceneCalibrationRecord(
            scene_config_id=calibration.scene_config_id,
            calibration_payload=payload,
        ))
    else:
        record.calibration_payload = payload

    if make_active:
        active = (await db.execute(select(SystemConfig).where(
            SystemConfig.config_key == ACTIVE_SCENE_CALIBRATION_KEY
        ))).scalar_one_or_none()
        if active is None:
            db.add(SystemConfig(
                config_key=ACTIVE_SCENE_CALIBRATION_KEY,
                config_value=calibration.scene_config_id,
                desc="当前已生效场景标定",
            ))
        else:
            active.config_value = calibration.scene_config_id
    await db.commit()
    return calibration


async def get_scene_calibration(db: AsyncSession, scene_config_id: str) -> SceneCalibration | None:
    record = (await db.execute(select(SceneCalibrationRecord).where(
        SceneCalibrationRecord.scene_config_id == scene_config_id
    ))).scalar_one_or_none()
    if record is None:
        return None
    return SceneCalibration.model_validate_json(record.calibration_payload)


async def get_active_scene_calibration(db: AsyncSession) -> SceneCalibration | None:
    active_id = (await db.execute(select(SystemConfig.config_value).where(
        SystemConfig.config_key == ACTIVE_SCENE_CALIBRATION_KEY
    ))).scalar_one_or_none()
    return await get_scene_calibration(db, active_id) if active_id else None
