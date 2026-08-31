from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.trajectory_adapter import load_scene_calibration
from backend.db.database import get_db
from backend.service.scene_calibration_service import get_active_scene_calibration, get_scene_calibration
from backend.service.errors import ServiceError
from contracts.v1.forewarning import SceneCalibration


router = APIRouter(prefix="/scene-calibrations", tags=["scene-calibrations"])


@router.get("/current", response_model=SceneCalibration)
async def get_current_scene_calibration(db: AsyncSession = Depends(get_db)):
    calibration = await get_active_scene_calibration(db)
    if calibration is None:
        raise ServiceError(404, "SCENE_CONFIG_MISSING", "active scene calibration does not exist")
    return calibration


@router.get("/{scene_config_id}", response_model=SceneCalibration)
async def get_scene_calibration_by_id(scene_config_id: str, db: AsyncSession = Depends(get_db)):
    try:
        calibration = await get_scene_calibration(db, scene_config_id)
        if calibration is not None:
            return calibration
        return load_scene_calibration(scene_config_id)
    except FileNotFoundError as exc:
        raise ServiceError(404, "SCENE_CONFIG_MISSING", "scene calibration does not exist") from exc
    except ValueError as exc:
        raise ServiceError(422, "SCENE_CONFIG_INVALID", "scene calibration is invalid") from exc
