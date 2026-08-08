"""Secure ingestion of the official Ezviz `ys.alarm` WebHook envelope."""

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import (
    EZVIZ_APP_SECRET,
    EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST,
    EZVIZ_WEBHOOK_MAX_AGE_SECONDS,
    EZVIZ_WEBHOOK_SECRET,
)
from backend.db.models import DeviceInfo, RiskAlarm
from backend.service.errors import ServiceError


_SENSITIVE_BODY_FIELDS = {"checksum", "url", "shortUrl", "accessToken", "appSecret"}
_CN_TZ = timezone(timedelta(hours=8))
logger = logging.getLogger("backend.ezviz_webhook")


def _redact(value: Any, key: str | None = None) -> Any:
    if key in _SENSITIVE_BODY_FIELDS:
        return "***"
    if key == "payload" and isinstance(value, str):
        try:
            return json.dumps(_redact(json.loads(value)), ensure_ascii=False, separators=(",", ":"))
        except ValueError:
            return value
    if isinstance(value, dict):
        return {name: _redact(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _parse_alarm_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ServiceError(422, "EZVIZ_ALARM_TIME_REQUIRED", "ys.alarm body.alarmTime is required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ServiceError(422, "EZVIZ_ALARM_TIME_INVALID", "alarmTime must use ISO 8601 format") from exc
    return parsed.replace(tzinfo=_CN_TZ) if parsed.tzinfo is None else parsed


def _parse_iot_alarm_time(value: Any) -> datetime:
    """Normalize the GB/IoT payload's ``basic.dateTime`` without logging it."""
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:  # millisecond epoch
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=_CN_TZ)
    if isinstance(value, str) and value.isdigit():
        return _parse_iot_alarm_time(int(value))
    return _parse_alarm_time(value)


def _iot_alarm_fields(header: dict[str, Any], body: dict[str, Any]) -> tuple[str, str, str, datetime, Any]:
    """Adapt a verified ``ys.iot`` GB alert to the internal raw-alarm fields."""
    payload = body.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as exc:
            raise ServiceError(422, "EZVIZ_IOT_PAYLOAD_INVALID", "ys.iot body.payload must be JSON") from exc
    if not isinstance(payload, dict):
        raise ServiceError(422, "EZVIZ_IOT_PAYLOAD_REQUIRED", "ys.iot body.payload must be an object")
    basic = payload.get("basic")
    if not isinstance(basic, dict):
        raise ServiceError(422, "EZVIZ_IOT_BASIC_REQUIRED", "ys.iot payload.basic is required")

    message_id = header.get("messageId")
    device_serial = header.get("deviceId") or body.get("deviceId")
    alarm_id = basic.get("UUID") or message_id
    if not all(isinstance(value, str) and value for value in (message_id, device_serial, alarm_id)):
        raise ServiceError(422, "EZVIZ_WEBHOOK_FIELDS_REQUIRED", "ys.iot requires messageId, deviceId and basic.UUID")
    alarm_type = body.get("identifier") or body.get("resourceType") or "ys.iot"
    if not isinstance(alarm_type, str) or not alarm_type:
        alarm_type = "ys.iot"
    return message_id, device_serial, alarm_id, _parse_iot_alarm_time(basic.get("dateTime")), payload


def verify_signature(raw_body: bytes, timestamp: str | None, signature: str | None) -> None:
    """Verify the official Signature = HMAC-SHA1(secret, Message + t) contract."""
    if EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST:
        app_secret_matches = False
        if EZVIZ_APP_SECRET and timestamp and signature:
            expected_with_app_secret = hmac.new(
                EZVIZ_APP_SECRET.encode("utf-8"), raw_body + timestamp.encode("utf-8"),
                hashlib.sha1,
            ).hexdigest()
            app_secret_matches = hmac.compare_digest(
                expected_with_app_secret.lower(), signature.strip().lower()
            )
        logger.warning(
            "ezviz_webhook unsigned test mode accepted callback; signature_present=%s "
            "timestamp_present=%s app_secret_signature_matches=%s; disable "
            "EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST after temporary integration",
            bool(signature), bool(timestamp), app_secret_matches,
        )
        return
    if not EZVIZ_WEBHOOK_SECRET:
        raise ServiceError(503, "EZVIZ_WEBHOOK_SECRET_NOT_CONFIGURED",
                           "configure EZVIZ_WEBHOOK_SECRET before enabling the WebHook")
    if not timestamp or not signature:
        raise ServiceError(401, "EZVIZ_WEBHOOK_SIGNATURE_REQUIRED", "t and Signature headers are required")
    try:
        timestamp_ms = int(timestamp)
    except ValueError as exc:
        raise ServiceError(401, "EZVIZ_WEBHOOK_TIMESTAMP_INVALID", "t must be a millisecond timestamp") from exc
    age_ms = abs(int(time.time() * 1000) - timestamp_ms)
    if age_ms > EZVIZ_WEBHOOK_MAX_AGE_SECONDS * 1000:
        raise ServiceError(401, "EZVIZ_WEBHOOK_TIMESTAMP_EXPIRED", "WebHook timestamp is outside the allowed window")
    expected = hmac.new(EZVIZ_WEBHOOK_SECRET.encode("utf-8"), raw_body + timestamp.encode("utf-8"),
                        hashlib.sha1).hexdigest()
    if not hmac.compare_digest(expected.lower(), signature.strip().lower()):
        raise ServiceError(401, "EZVIZ_WEBHOOK_SIGNATURE_INVALID", "WebHook signature verification failed")


async def ingest_alarm(db: AsyncSession, envelope: dict[str, Any]) -> tuple[str, bool]:
    header = envelope.get("header")
    body = envelope.get("body")
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ServiceError(422, "EZVIZ_WEBHOOK_ENVELOPE_INVALID", "message must contain object header and body")
    message_type = header.get("type")
    payload: Any = None
    if message_type == "ys.iot":
        message_id, device_serial, alarm_id, alarm_time, payload = _iot_alarm_fields(header, body)
        alarm_type = body.get("identifier") or body.get("resourceType") or "ys.iot"
    elif message_type == "ys.alarm":
        message_id = header.get("messageId")
        device_serial = header.get("deviceId")
        alarm_id = body.get("alarmId") or message_id
        if not all(isinstance(value, str) and value for value in (message_id, device_serial, alarm_id)):
            raise ServiceError(422, "EZVIZ_WEBHOOK_FIELDS_REQUIRED", "messageId, deviceId and alarmId are required")
        alarm_type = str(body.get("alarmType") or "unknown")
        alarm_time = _parse_alarm_time(body.get("alarmTime"))
    else:
        raise ServiceError(422, "EZVIZ_WEBHOOK_TYPE_UNSUPPORTED", "only ys.alarm and ys.iot are accepted")

    device = (await db.execute(select(DeviceInfo).where(
        DeviceInfo.device_sn == device_serial))).scalar_one_or_none()
    if not device:
        raise ServiceError(409, "EZVIZ_WEBHOOK_DEVICE_UNREGISTERED",
                           "register the Ezviz device with EZVIZ_RESIDENT_ID before accepting alarms")

    existing = (await db.execute(select(RiskAlarm).where(
        RiskAlarm.alarm_msg_id == alarm_id))).scalar_one_or_none()
    if existing:
        return message_id, True

    pictures = body.get("pictureList")
    if message_type == "ys.iot" and isinstance(payload, dict):
        intelligent_tag = payload.get("intelligentTag")
        if isinstance(intelligent_tag, dict):
            pictures = intelligent_tag.get("pictures")
    picture_id = pictures[0].get("id") if isinstance(pictures, list) and pictures and isinstance(pictures[0], dict) else None
    row = RiskAlarm(
        alarm_msg_id=alarm_id,
        resident_id=device.resident_id,
        device_sn=device_serial,
        alarm_source="ezviz_cloud_webhook",
        alarm_type=alarm_type,
        capture_img_path=picture_id,
        alarm_time=alarm_time,
        raw_callback_json=json.dumps(_redact(envelope), ensure_ascii=False, separators=(",", ":")),
    )
    db.add(row)
    await db.commit()
    logger.info("ezviz_alarm_ingested alarm_id=%s device_serial=%s alarm_type=%s", alarm_id, device_serial,
                row.alarm_type)
    return message_id, False
