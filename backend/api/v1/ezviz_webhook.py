from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.service.ezviz_alarm_service import ingest_alarm, verify_signature
from backend.service.errors import ServiceError


router = APIRouter(prefix="/webhooks/ezviz", tags=["ezviz-webhook"])


@router.post("")
async def receive_ezviz_alarm(request: Request, db: AsyncSession = Depends(get_db)):
    raw_body = await request.body()
    verify_signature(raw_body, request.headers.get("t"), request.headers.get("signature"))
    try:
        envelope = await request.json()
    except ValueError as exc:
        raise ServiceError(422, "EZVIZ_WEBHOOK_JSON_INVALID", "WebHook body must be JSON") from exc
    if not isinstance(envelope, dict):
        raise ServiceError(422, "EZVIZ_WEBHOOK_ENVELOPE_INVALID", "WebHook body must be a JSON object")
    message_type = request.headers.get("message_type")
    if message_type and message_type != "ys.alarm":
        raise ServiceError(422, "EZVIZ_WEBHOOK_TYPE_UNSUPPORTED", "message_type must be ys.alarm")
    message_id, _ = await ingest_alarm(db, envelope)
    # 萤石要求最小成功响应为 {"messageId": "..."}；不要扩展该协议响应。
    return {"messageId": message_id}
