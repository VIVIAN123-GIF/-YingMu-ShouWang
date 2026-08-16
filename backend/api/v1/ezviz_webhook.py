import logging
import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST
from backend.db.database import get_db
from backend.service.alarm_task_service import enqueue_alarm_task
from backend.service.ezviz_alarm_service import ingest_alarm, verify_signature
from backend.service.errors import ServiceError


router = APIRouter(prefix="/webhooks/ezviz", tags=["ezviz-webhook"])
logger = logging.getLogger("backend.ezviz_webhook")


def _safe_webhook_debug(request: Request, raw_body: bytes) -> dict:
    """Return only message shape for callback troubleshooting.

    This diagnostic is returned with WebHook failures. It intentionally excludes
    request values because provider payloads can contain signatures, tokens,
    device serials and media URLs.
    """
    try:
        envelope = json.loads(raw_body)
        json_valid = True
    except (UnicodeDecodeError, ValueError):
        envelope = None
        json_valid = False

    header = envelope.get("header") if isinstance(envelope, dict) else None
    body = envelope.get("body") if isinstance(envelope, dict) else None
    payload = body.get("payload") if isinstance(body, dict) else None
    return {
        "path": request.url.path,
        "content_type": request.headers.get("content-type"),
        "message_type_header": request.headers.get("message_type"),
        "signature_present": bool(request.headers.get("signature")),
        "timestamp_present": bool(request.headers.get("t")),
        "body_bytes": len(raw_body),
        "json_valid": json_valid,
        "top_level_keys": sorted(envelope) if isinstance(envelope, dict) else [],
        "header_keys": sorted(header) if isinstance(header, dict) else [],
        "body_keys": sorted(body) if isinstance(body, dict) else [],
        "payload_kind": type(payload).__name__ if payload is not None else "none",
    }


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


def _platform_test_message_id(envelope: object, request_message_type: str | None) -> str | None:
    """Return the official console-test ID, without treating it as a device alarm.

    Ezviz sends ``ys.test.msg`` when the developer presses the message-push
    console's test button.  It uses the normal signing/acknowledgement protocol
    but is not evidence of a physical-device alert and must not enter RiskAlarm.
    """
    if not isinstance(envelope, dict):
        return None
    header = envelope.get("header")
    if not isinstance(header, dict):
        return None
    if header.get("type") != "ys.test.msg" and request_message_type != "ys.test.msg":
        return None
    message_id = header.get("messageId")
    return message_id if isinstance(message_id, str) and message_id else None


def _platform_shadow_change_message_id(envelope: object, request_message_type: str | None) -> str | None:
    """Acknowledge device shadow updates without treating them as safety alarms.

    ``ys.shadow.change`` reports a device-property synchronization event. It is
    useful to acknowledge at the transport boundary, but it must not create a
    RiskAlarm or schedule snapshot/algorithm work.
    """
    if not isinstance(envelope, dict):
        return None
    header = envelope.get("header")
    if not isinstance(header, dict):
        return None
    if header.get("type") != "ys.shadow.change" and request_message_type != "ys.shadow.change":
        return None
    message_id = header.get("messageId")
    return message_id if isinstance(message_id, str) and message_id else None


@router.post("")
async def receive_ezviz_alarm(request: Request, db: AsyncSession = Depends(get_db)):
    raw_body = await request.body()
    try:
        verify_signature(raw_body, request.headers.get("t"), request.headers.get("signature"))
        try:
            envelope = await request.json()
        except ValueError as exc:
            raise ServiceError(422, "EZVIZ_WEBHOOK_JSON_INVALID", "WebHook body must be JSON") from exc
        _log_test_shape(request, envelope)
        if not isinstance(envelope, dict):
            raise ServiceError(422, "EZVIZ_WEBHOOK_ENVELOPE_INVALID", "WebHook body must be a JSON object")
        message_type = request.headers.get("message_type")
        test_message_id = _platform_test_message_id(envelope, message_type)
        if test_message_id:
            # The platform considers HTTP 200 plus the original messageId a success.
            # Do not enqueue a task or create an alarm for this console-only probe.
            logger.info("ezviz_webhook_console_test_acknowledged message_id=%s", test_message_id)
            return {"messageId": test_message_id}
        shadow_change_id = _platform_shadow_change_message_id(envelope, message_type)
        if shadow_change_id:
            logger.info("ezviz_webhook_shadow_change_acknowledged message_id=%s", shadow_change_id)
            return {"messageId": shadow_change_id}
        if message_type and message_type not in {"ys.alarm", "ys.iot", "ys.shadow.change"}:
            raise ServiceError(
                422,
                "EZVIZ_WEBHOOK_TYPE_UNSUPPORTED",
                "message_type must be ys.alarm, ys.iot, or ys.shadow.change",
            )
        result = await ingest_alarm(db, envelope)
        # Queueing is a short database write. The slower capture/algorithm work is performed
        # by backend.worker.alarm_worker after this endpoint has returned to Ezviz.
        await enqueue_alarm_task(db, result.alarm_msg_id)
        # 萤石要求最小成功响应为 {"messageId": "..."}；不要扩展该协议响应。
        return {"messageId": result.message_id}
    except ServiceError as exc:
        # Do not replace pre-existing diagnostics supplied by another safe adapter.
        if exc.debug is None:
            exc.debug = _safe_webhook_debug(request, raw_body)
        raise
