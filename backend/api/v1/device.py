from fastapi import APIRouter

from backend.service.device_adapter import device_adapter

router = APIRouter(prefix="/device", tags=["device"])

@router.get("/status")
async def status():
    return await device_adapter.status()

@router.get("/snapshot")
async def snapshot():
    return await device_adapter.snapshot()

@router.get("/live-address", include_in_schema=False)
async def live_address():
    return await device_adapter.live_address()
