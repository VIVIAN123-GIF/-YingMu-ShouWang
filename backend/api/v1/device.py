import secrets
import os

from fastapi import APIRouter, Header

from backend.service.device_adapter import device_adapter
from backend.service.errors import ServiceError

router = APIRouter(prefix="/device", tags=["device"])

@router.get("/status")
async def status():
    return await device_adapter.status()

@router.get("/snapshot")
async def snapshot():
    return await device_adapter.snapshot()

@router.post("/stop")
async def stop_collection(x_control_token: str | None = Header(default=None)):
    control_token = os.getenv("YINGMU_CONTROL_TOKEN", "")
    if not control_token:
        raise ServiceError(503, "CONTROL_TOKEN_NOT_CONFIGURED",
                           "YINGMU_CONTROL_TOKEN must be configured before remote stop is enabled")
    if not x_control_token or not secrets.compare_digest(x_control_token, control_token):
        raise ServiceError(403, "CONTROL_FORBIDDEN", "only the authorized on-site service may stop collection")
    return await device_adapter.stop()
