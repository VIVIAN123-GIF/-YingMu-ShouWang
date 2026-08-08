import logging
import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST
from backend.db.database import get_db
from backend.service.ezviz_alarm_service import ingest_alarm, verify_signature
from backend.service.errors import ServiceError


router = APIRouter(prefix="/webhooks/ezviz", tags=["ezviz-webhook"])
logger = logging.getLogger("backend.ezviz_webhook")


def _log_test_shape(request: Request, envelope: object) -> None:
    """Log only callback structure during short-lived unsigned integration."""
    if not EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST:
        return
    top_level_keys = sorted(envelope) if isinstance(envelope, dict) else []
    header = envelope.get("header") if isinstance(envelope, dict) else None
    body = envelope.get("body") if isinstance(envelope, dict) else None
    payload = body.get("payload") if isinstance(body, dict) else None
    if isinstance(payload, str):
        try:
            parsed_payload = json.loads(payload)
        except ValueError:
            parsed_payload = None
    else:
        parsed_payload = payload
    basic = parsed_payload.get("basic") if isinstance(parsed_payload, dict) else None
    intelligent_tag = parsed_payload.get("intelligentTag") if isinstance(parsed_payload, dict) else None
    service_info = parsed_payload.get("serviceInfo") if isinstance(parsed_payload, dict) else None
    logger.info(
        "ezviz_webhook_test_shape header_names=%s top_level_keys=%s header_keys=%s "
        "body_keys=%s message_type=%s header_type=%s payload_kind=%s payload_keys=%s "
        "basic_keys=%s intelligent_tag_keys=%s service_info_keys=%s",
        sorted(request.headers.keys()),
        top_level_keys,
        sorted(header) if isinstance(header, dict) else [],
        sorted(body) if isinstance(body, dict) else [],
        request.headers.get("message_type"),
        header.get("type") if isinstance(header, dict) else None,
        type(payload).__name__ if payload is not None else "none",
        sorted(parsed_payload) if isinstance(parsed_payload, dict) else [],
        sorted(basic) if isinstance(basic, dict) else [],
        sorted(intelligent_tag) if isinstance(intelligent_tag, dict) else [],
        sorted(service_info) if isinstance(service_info, dict) else [],
    )


@router.post("")
async def receive_ezviz_alarm(request: Request, db: AsyncSession = Depends(get_db)):
    raw_body = await request.body()
    verify_signature(raw_body, request.headers.get("t"), request.headers.get("signature"))
    try:
        envelope = await request.json()
    except ValueError as exc:
        raise ServiceError(422, "EZVIZ_WEBHOOK_JSON_INVALID", "WebHook body must be JSON") from exc
    _log_test_shape(request, envelope)
    if not isinstance(envelope, dict):
        raise ServiceError(422, "EZVIZ_WEBHOOK_ENVELOPE_INVALID", "WebHook body must be a JSON object")
    message_type = request.headers.get("message_type")
    if message_type and message_type not in {"ys.alarm", "ys.iot"}:
        raise ServiceError(422, "EZVIZ_WEBHOOK_TYPE_UNSUPPORTED", "message_type must be ys.alarm or ys.iot")
    message_id, _ = await ingest_alarm(db, envelope)
    # 萤石要求最小成功响应为 {"messageId": "..."}；不要扩展该协议响应。
    return {"messageId": message_id}
