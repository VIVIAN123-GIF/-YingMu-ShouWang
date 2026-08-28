from fastapi import APIRouter
from backend.api.v1 import alarms, assets, device, events, evidence, ezviz_webhook, media, observations, reports, residents, risk, scene_calibrations

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
router.include_router(alarms.router)
router.include_router(scene_calibrations.router)
router.include_router(media.session_router)
