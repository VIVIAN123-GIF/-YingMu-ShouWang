"""Privately ingest one authorized MP4 and enqueue its algorithm task."""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import (
    YINGMU_AUTHORIZATION_RECORD_ID,
    YINGMU_CAMERA_POSITION_ID,
    YINGMU_PRIVATE_MEDIA_ROOT,
    YINGMU_RETENTION_UNTIL,
)
from backend.db.models import AlarmProcessingTask, DeviceInfo, RiskAlarm
from backend.schemas.asset import AssetCreate
from backend.service.asset_service import create_asset
from backend.service.serialization import CN_TZ, dumps


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class RecordedReplayIngestError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_input(value: Path) -> Path:
    path = value.expanduser().resolve()
    if path.suffix.lower() != ".mp4":
        raise RecordedReplayIngestError("REPLAY_FORMAT_INVALID", "recorded replay must be an MP4")
    if not path.is_file() or path.stat().st_size <= 0:
        raise RecordedReplayIngestError("REPLAY_FILE_INVALID", "recorded replay is not readable")
    with path.open("rb") as stream:
        prefix = stream.read(64)
    if b"ftyp" not in prefix[4:64]:
        raise RecordedReplayIngestError("REPLAY_SIGNATURE_INVALID", "recorded replay has an invalid MP4 signature")
    return path


def _private_root(value: str) -> Path:
    if not value.strip():
        raise RecordedReplayIngestError("PRIVATE_MEDIA_ROOT_REQUIRED", "private media storage is not configured")
    root = Path(value).expanduser().resolve()
    try:
        root.relative_to(REPOSITORY_ROOT)
    except ValueError:
        pass
    else:
        raise RecordedReplayIngestError(
            "PRIVATE_MEDIA_ROOT_UNSAFE",
            "private media storage must be outside the repository",
        )
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RecordedReplayIngestError(
            "PRIVATE_MEDIA_ROOT_UNAVAILABLE",
            "private media storage is unavailable",
        ) from exc
    return root


def _timezone_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RecordedReplayIngestError(
            f"{field}_TIMEZONE_REQUIRED",
            f"{field.lower()} requires a timezone",
        )
    return value.astimezone(CN_TZ)


def _retention(value: str | datetime, captured_at: datetime) -> datetime:
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except ValueError as exc:
        raise RecordedReplayIngestError("REPLAY_RETENTION_INVALID", "recorded replay retention is invalid") from exc
    parsed = _timezone_datetime(parsed, field="REPLAY_RETENTION")
    if parsed <= max(captured_at, datetime.now(CN_TZ)):
        raise RecordedReplayIngestError(
            "REPLAY_AUTHORIZATION_EXPIRED",
            "recorded replay authorization has expired",
        )
    return parsed


def _stable_ids(
    content_sha256: str,
    resident_id: str,
    captured_at: datetime,
    camera_position_id: str,
) -> dict[str, str]:
    identity = "|".join(
        (content_sha256, resident_id, captured_at.isoformat(), camera_position_id)
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    device_digest = hashlib.sha256(
        f"{resident_id}|{camera_position_id}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "asset_id": f"asset-replay-{digest}",
        "alarm_msg_id": f"alarm-replay-{digest}",
        "task_id": f"alarm-task-replay-{digest}",
        "device_sn": f"replay-device-{device_digest}",
        "storage_key": f"replay-{digest}-{content_sha256[:16]}.mp4",
    }


def _copy_private(source: Path, destination: Path, expected_sha256: str) -> bool:
    if destination.exists():
        if not destination.is_file() or _sha256(destination) != expected_sha256:
            raise RecordedReplayIngestError(
                "PRIVATE_MEDIA_CONFLICT",
                "private replay object conflicts with existing content",
            )
        return False
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.part"
    try:
        shutil.copyfile(source, temporary)
        if _sha256(temporary) != expected_sha256:
            raise RecordedReplayIngestError(
                "PRIVATE_MEDIA_COPY_INVALID",
                "private replay copy failed integrity verification",
            )
        os.replace(temporary, destination)
    except RecordedReplayIngestError:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise RecordedReplayIngestError(
            "PRIVATE_MEDIA_COPY_FAILED",
            "private replay copy failed",
        ) from exc
    return True


async def enqueue_recorded_replay(
    db: AsyncSession,
    *,
    input_path: Path,
    resident_id: str,
    captured_at: datetime,
    private_media_root: str | None = None,
    camera_position_id: str | None = None,
    authorization_record_id: str | None = None,
    retention_until: str | datetime | None = None,
) -> dict[str, object]:
    resident_id = resident_id.strip()
    if not resident_id or len(resident_id) > 128:
        raise RecordedReplayIngestError(
            "RESIDENT_ID_INVALID",
            "resident_id is required and must not exceed 128 characters",
        )
    source = _validate_input(input_path)
    captured_at = _timezone_datetime(captured_at, field="CAPTURED_AT")
    camera = (
        camera_position_id
        if camera_position_id is not None
        else YINGMU_CAMERA_POSITION_ID
    ).strip()
    authorization = (
        authorization_record_id
        if authorization_record_id is not None
        else YINGMU_AUTHORIZATION_RECORD_ID
    ).strip()
    if not camera:
        raise RecordedReplayIngestError("CAMERA_POSITION_REQUIRED", "recorded replay camera position is required")
    if not authorization:
        raise RecordedReplayIngestError("REPLAY_AUTHORIZATION_REQUIRED", "recorded replay authorization is required")
    retention_source = retention_until if retention_until is not None else YINGMU_RETENTION_UNTIL
    if not retention_source:
        raise RecordedReplayIngestError("REPLAY_RETENTION_REQUIRED", "recorded replay retention is required")
    retention = _retention(retention_source, captured_at)
    root = _private_root(private_media_root if private_media_root is not None else YINGMU_PRIVATE_MEDIA_ROOT)
    content_sha256 = _sha256(source)
    ids = _stable_ids(content_sha256, resident_id, captured_at, camera)
    destination = (root / ids["storage_key"]).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise RecordedReplayIngestError("PRIVATE_MEDIA_KEY_INVALID", "private replay object key is invalid") from exc
    copied = _copy_private(source, destination, content_sha256)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    asset_payload = AssetCreate(
        asset_id=ids["asset_id"],
        title="Authorized recorded replay",
        source_mode="RECORDED_REPLAY",
        simulated=True,
        stream_url=None,
        fallback_url=None,
        fallback_kind="private_storage",
        available=True,
        verification_status="VERIFIED_REPLAY",
        captured_at=captured_at,
        notice="Authorized recorded replay retained in private storage",
        device_ref=f"device-ref-{ids['device_sn'][-16:]}",
        device_model="EZVIZ_C6C",
        camera_position_id=camera,
        authorization_status="AUTHORIZED",
        authorization_record_id=authorization,
        retention_until=retention,
        content_sha256=content_sha256,
        content_type="video/mp4",
        byte_size=source.stat().st_size,
    )
    try:
        _, asset_idempotent = await create_asset(
            db,
            asset_payload,
            storage_key=ids["storage_key"],
            commit=False,
        )
        device = (await db.execute(select(DeviceInfo).where(
            DeviceInfo.device_sn == ids["device_sn"]
        ))).scalar_one_or_none()
        if device is None:
            db.add(DeviceInfo(
                resident_id=resident_id,
                device_sn=ids["device_sn"],
                channel_no=1,
                device_name="recorded-replay-device",
                is_online=False,
                adapter_mode="RECORDED_REPLAY",
            ))
            await db.flush()
        elif device.resident_id != resident_id:
            raise RecordedReplayIngestError(
                "REPLAY_DEVICE_CONFLICT",
                "recorded replay device belongs to another resident",
            )

        alarm = (await db.execute(select(RiskAlarm).where(
            RiskAlarm.alarm_msg_id == ids["alarm_msg_id"]
        ))).scalar_one_or_none()
        if alarm is None:
            db.add(RiskAlarm(
                alarm_msg_id=ids["alarm_msg_id"],
                resident_id=resident_id,
                device_sn=ids["device_sn"],
                alarm_source="recorded_replay_cli",
                alarm_type="RecordedReplay",
                capture_img_path=None,
                alarm_time=captured_at.replace(tzinfo=None),
                raw_callback_json=dumps({
                    "source": "recorded_replay_cli",
                    "asset_id": ids["asset_id"],
                }),
            ))
            await db.flush()
        elif alarm.resident_id != resident_id or alarm.device_sn != ids["device_sn"]:
            raise RecordedReplayIngestError(
                "REPLAY_ALARM_CONFLICT",
                "recorded replay alarm conflicts with existing data",
            )

        task = (await db.execute(select(AlarmProcessingTask).where(
            AlarmProcessingTask.task_id == ids["task_id"]
        ))).scalar_one_or_none()
        task_created = task is None
        if task is None:
            task = AlarmProcessingTask(
                task_id=ids["task_id"],
                alarm_msg_id=ids["alarm_msg_id"],
                resident_id=resident_id,
                device_sn=ids["device_sn"],
                status="CAPTURED",
                attempt_count=0,
                max_attempts=3,
                capture_asset_id=ids["asset_id"],
                capture_completed_at=now,
                available_at=now,
            )
            db.add(task)
        elif (
            task.alarm_msg_id != ids["alarm_msg_id"]
            or task.resident_id != resident_id
            or task.capture_asset_id != ids["asset_id"]
        ):
            raise RecordedReplayIngestError(
                "REPLAY_TASK_CONFLICT",
                "recorded replay task conflicts with existing data",
            )
        await db.commit()
    except Exception:
        await db.rollback()
        if copied:
            destination.unlink(missing_ok=True)
        raise

    return {
        "result": "CREATED" if task_created else "EXISTING",
        "asset_id": ids["asset_id"],
        "task_id": ids["task_id"],
        "status": task.status,
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "asset_idempotent": asset_idempotent,
    }
