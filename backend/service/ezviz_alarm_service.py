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

from backend.config import EZVIZ_WEBHOOK_MAX_AGE_SECONDS, EZVIZ_WEBHOOK_SECRET
from backend.db.models import DeviceInfo, RiskAlarm
from backend.service.errors import ServiceError


_SENSITIVE_BODY_FIELDS = {"checksum", "url", "shortUrl", "accessToken", "appSecret"}
_CN_TZ = timezone(timedelta(hours=8))
logger = logging.getLogger("backend.ezviz_webhook")


def _redact(value: Any, key: str | None = None) -> Any:
    if key in _SENSITIVE_BODY_FIELDS:
        return "***"
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


def verify_signature(raw_body: bytes, timestamp: str | None, signature: str | None) -> None:
    """Verify the official Signature = HMAC-SHA1(secret, Message + t) contract."""
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
    if header.get("type") != "ys.alarm":
        raise ServiceError(422, "EZVIZ_WEBHOOK_TYPE_UNSUPPORTED", "only ys.alarm is accepted by this endpoint")

    message_id = header.get("messageId")
    device_serial = header.get("deviceId")
    alarm_id = body.get("alarmId") or message_id
    if not all(isinstance(value, str) and value for value in (message_id, device_serial, alarm_id)):
        raise ServiceError(422, "EZVIZ_WEBHOOK_FIELDS_REQUIRED", "messageId, deviceId and alarmId are required")

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
    picture_id = pictures[0].get("id") if isinstance(pictures, list) and pictures and isinstance(pictures[0], dict) else None
    row = RiskAlarm(
        alarm_msg_id=alarm_id,
        resident_id=device.resident_id,
        device_sn=device_serial,
        alarm_source="ezviz_cloud_webhook",
        alarm_type=str(body.get("alarmType") or "unknown"),
        capture_img_path=picture_id,
        alarm_time=_parse_alarm_time(body.get("alarmTime")),
        raw_callback_json=json.dumps(_redact(envelope), ensure_ascii=False, separators=(",", ":")),
    )
    db.add(row)
    await db.commit()
    logger.info("ezviz_alarm_ingested alarm_id=%s device_serial=%s alarm_type=%s", alarm_id, device_serial,
                row.alarm_type)
    return message_id, False
