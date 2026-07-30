from fastapi import APIRouter
from backend.api.v1 import assets, device, events, evidence, ezviz_webhook, observations, reports, residents, risk

router = APIRouter(prefix="/api/v1")
router.include_router(observations.router)
router.include_router(evidence.router)
router.include_router(residents.router)
router.include_router(risk.router)
router.include_router(events.router)
router.include_router(device.router)
router.include_router(assets.router)
router.include_router(reports.router)
router.include_router(ezviz_webhook.router)
