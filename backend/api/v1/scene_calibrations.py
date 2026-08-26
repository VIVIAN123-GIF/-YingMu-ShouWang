from fastapi import APIRouter

from adapters.trajectory_adapter import load_scene_calibration
from backend.service.errors import ServiceError
from contracts.v1.forewarning import SceneCalibration


router = APIRouter(prefix="/scene-calibrations", tags=["scene-calibrations"])


@router.get("/{scene_config_id}", response_model=SceneCalibration)
async def get_scene_calibration(scene_config_id: str):
    try:
        return load_scene_calibration(scene_config_id)
    except FileNotFoundError as exc:
        raise ServiceError(404, "SCENE_CONFIG_MISSING", "scene calibration does not exist") from exc
    except ValueError as exc:
        raise ServiceError(422, "SCENE_CONFIG_INVALID", "scene calibration is invalid") from exc
