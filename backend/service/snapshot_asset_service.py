"""Persist an internal Ezviz snapshot as an authorized private Asset."""

from __future__ import annotations

import hashlib
import asyncio
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import (
    EZVIZ_DEVICE_MODEL,
    YINGMU_AUTHORIZATION_RECORD_ID,
    YINGMU_CAMERA_POSITION_ID,
    YINGMU_PRIVATE_MEDIA_ROOT,
    YINGMU_FFMPEG_BINARY,
    YINGMU_VIDEO_CAPTURE_SECONDS,
    YINGMU_RETENTION_UNTIL,
    YINGMU_SNAPSHOT_DOWNLOAD_TIMEOUT_SECONDS,
    YINGMU_SNAPSHOT_MAX_BYTES,
)
from backend.db.models import Asset as AssetRow
from backend.schemas.asset import AssetCreate
from backend.service.asset_service import asset_dict, create_asset
from backend.service.errors import ServiceError
from contracts.v1.platform import PlatformSnapshotResult
from contracts.v1.platform import PlatformVideoSource


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTENT_TYPES = {
    "image/jpeg": (".jpg", b"\xff\xd8\xff"),
    "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
    "image/webp": (".webp", b"RIFF"),
}


class SnapshotAssetError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool):
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class StoredSnapshot:
    storage_key: str
    content_sha256: str
    content_type: str
    byte_size: int


@dataclass(frozen=True)
class VideoProbe:
    duration_seconds: float
    frame_rate: float
    frame_count: int
    codec_name: str | None = None


VIDEO_MIN_DURATION_RATIO = 0.75
VIDEO_MIN_FRAME_RATE = 5.0


def _private_root(value: str) -> Path:
    if not value.strip():
        raise SnapshotAssetError(
            "PRIVATE_MEDIA_ROOT_REQUIRED",
            "Private media storage is not configured",
            retryable=False,
        )
    root = Path(value).expanduser().resolve()
    try:
        root.relative_to(REPOSITORY_ROOT)
    except ValueError:
        pass
    else:
        raise SnapshotAssetError(
            "PRIVATE_MEDIA_ROOT_UNSAFE",
            "Private media storage must be outside the repository",
            retryable=False,
        )
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SnapshotAssetError(
            "PRIVATE_MEDIA_ROOT_UNAVAILABLE",
            "Private media storage is unavailable",
            retryable=False,
        ) from exc
    return root


def _authorized_retention(value: str, captured_at: datetime) -> datetime:
    if not YINGMU_AUTHORIZATION_RECORD_ID.strip():
        raise SnapshotAssetError(
            "SNAPSHOT_AUTHORIZATION_REQUIRED",
            "An authorization record is required before media is retained",
            retryable=False,
        )
    if not YINGMU_CAMERA_POSITION_ID.strip():
        raise SnapshotAssetError(
            "CAMERA_POSITION_REQUIRED",
            "A frozen camera position is required before media is retained",
            retryable=False,
        )
    try:
        retention = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotAssetError(
            "SNAPSHOT_RETENTION_INVALID",
            "The media retention deadline is invalid",
            retryable=False,
        ) from exc
    if retention.tzinfo is None or retention.utcoffset() is None:
        raise SnapshotAssetError(
            "SNAPSHOT_RETENTION_INVALID",
            "The media retention deadline requires a timezone",
            retryable=False,
        )
    if retention <= captured_at:
        raise SnapshotAssetError(
            "SNAPSHOT_AUTHORIZATION_EXPIRED",
            "The media authorization has expired",
            retryable=False,
        )
    return retention


def _validate_signature(content_type: str, prefix: bytes) -> str:
    media = CONTENT_TYPES.get(content_type)
    if media is None:
        raise SnapshotAssetError(
            "SNAPSHOT_CONTENT_TYPE_INVALID",
            "The snapshot response is not a supported image",
            retryable=True,
        )
    extension, signature = media
    valid = prefix.startswith(signature)
    if content_type == "image/webp":
        valid = valid and len(prefix) >= 12 and prefix[8:12] == b"WEBP"
    if not valid:
        raise SnapshotAssetError(
            "SNAPSHOT_SIGNATURE_INVALID",
            "The snapshot bytes do not match the declared image type",
            retryable=True,
        )
    return extension


def _private_object(root: Path, storage_key: str) -> Path:
    if not storage_key or Path(storage_key).name != storage_key:
        raise SnapshotAssetError(
            "ASSET_STORAGE_KEY_INVALID",
            "The private Asset storage key is invalid",
            retryable=False,
        )
    path = (root / storage_key).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SnapshotAssetError(
            "ASSET_STORAGE_KEY_INVALID",
            "The private Asset storage key is invalid",
            retryable=False,
        ) from exc
    return path


def resolve_private_asset_path(storage_key: str) -> Path:
    """Resolve an internal Asset without exposing its storage location."""
    return _private_object(_private_root(YINGMU_PRIVATE_MEDIA_ROOT), storage_key)


async def _stream_snapshot(
    client: httpx.AsyncClient,
    snapshot: PlatformSnapshotResult,
    *,
    asset_id: str,
    root: Path,
    max_bytes: int,
) -> StoredSnapshot:
    part_path = root / f".{asset_id}-{uuid4().hex}.part"
    final_path: Path | None = None
    try:
        async with client.stream(
            "GET", str(snapshot.temporary_url), follow_redirects=True
        ) as response:
            if not 200 <= response.status_code < 300:
                raise SnapshotAssetError(
                    "SNAPSHOT_DOWNLOAD_HTTP_ERROR",
                    "The snapshot provider returned an unsuccessful response",
                    retryable=True,
                )
            content_type = (
                response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            )
            if content_type not in CONTENT_TYPES:
                raise SnapshotAssetError(
                    "SNAPSHOT_CONTENT_TYPE_INVALID",
                    "The snapshot response is not a supported image",
                    retryable=True,
                )
            digest = hashlib.sha256()
            byte_size = 0
            prefix = bytearray()
            with part_path.open("xb") as output:
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    byte_size += len(chunk)
                    if byte_size > max_bytes:
                        raise SnapshotAssetError(
                            "SNAPSHOT_TOO_LARGE",
                            "The snapshot exceeds the configured byte limit",
                            retryable=False,
                        )
                    if len(prefix) < 16:
                        prefix.extend(chunk[: 16 - len(prefix)])
                    digest.update(chunk)
                    output.write(chunk)
        if byte_size == 0:
            raise SnapshotAssetError(
                "SNAPSHOT_EMPTY",
                "The snapshot response was empty",
                retryable=True,
            )
        extension = _validate_signature(content_type, bytes(prefix))
        final_path = root / f"{asset_id}{extension}"
        part_path.replace(final_path)
        return StoredSnapshot(
            storage_key=final_path.name,
            content_sha256=digest.hexdigest(),
            content_type=content_type,
            byte_size=byte_size,
        )
    except SnapshotAssetError:
        raise
    except (httpx.HTTPError, OSError) as exc:
        raise SnapshotAssetError(
            "SNAPSHOT_DOWNLOAD_UNAVAILABLE",
            "The snapshot could not be downloaded or stored",
            retryable=True,
        ) from exc
    finally:
        if part_path.exists():
            part_path.unlink(missing_ok=True)


async def download_snapshot(
    snapshot: PlatformSnapshotResult,
    *,
    asset_id: str,
    media_root: str | None = None,
    max_bytes: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> StoredSnapshot:
    if snapshot.source_mode != "LIVE_DEVICE" or snapshot.simulated:
        raise SnapshotAssetError(
            "LIVE_SNAPSHOT_REQUIRED",
            "Only a real live-device snapshot can create a live Asset",
            retryable=False,
        )
    root = _private_root(media_root if media_root is not None else YINGMU_PRIVATE_MEDIA_ROOT)
    limit = max_bytes if max_bytes is not None else YINGMU_SNAPSHOT_MAX_BYTES
    if limit <= 0:
        raise SnapshotAssetError(
            "SNAPSHOT_SIZE_LIMIT_INVALID",
            "The snapshot byte limit must be positive",
            retryable=False,
        )
    if client is not None:
        return await _stream_snapshot(
            client, snapshot, asset_id=asset_id, root=root, max_bytes=limit
        )
    async with httpx.AsyncClient(
        timeout=YINGMU_SNAPSHOT_DOWNLOAD_TIMEOUT_SECONDS
    ) as owned_client:
        return await _stream_snapshot(
            owned_client, snapshot, asset_id=asset_id, root=root, max_bytes=limit
        )


async def persist_snapshot_asset(
    db: AsyncSession,
    snapshot: PlatformSnapshotResult,
    *,
    task_id: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[dict, bool]:
    retention = _authorized_retention(YINGMU_RETENTION_UNTIL, snapshot.captured_at)
    root = _private_root(YINGMU_PRIVATE_MEDIA_ROOT)
    asset_id = f"asset-live-{hashlib.sha256(task_id.encode('utf-8')).hexdigest()[:24]}"
    existing = (await db.execute(
        select(AssetRow).where(AssetRow.asset_id == asset_id)
    )).scalar_one_or_none()
    if existing is not None:
        existing_path = _private_object(root, existing.storage_key or "")
        if not existing_path.is_file():
            raise SnapshotAssetError(
                "ASSET_PRIVATE_OBJECT_MISSING",
                "The existing Asset has no private media object",
                retryable=False,
            )
        return asset_dict(existing), True

    stored = await download_snapshot(
        snapshot, asset_id=asset_id, media_root=str(root), client=client
    )
    payload = AssetCreate(
        asset_id=asset_id,
        title="萤石C6c告警抓拍",
        source_mode="LIVE_DEVICE",
        simulated=False,
        stream_url=None,
        fallback_url=None,
        fallback_kind="SERVER_MANAGED_SNAPSHOT",
        available=True,
        verification_status="VERIFIED_LIVE_CAPTURE",
        captured_at=snapshot.captured_at,
        notice="由萤石开放平台抓拍并转存，访问受授权控制",
        device_ref=snapshot.device_ref,
        device_model=EZVIZ_DEVICE_MODEL,
        camera_position_id=YINGMU_CAMERA_POSITION_ID,
        authorization_status="AUTHORIZED",
        authorization_record_id=YINGMU_AUTHORIZATION_RECORD_ID,
        retention_until=retention,
        content_sha256=stored.content_sha256,
        content_type=stored.content_type,
        byte_size=stored.byte_size,
    )
    try:
        return await create_asset(
            db, payload, storage_key=stored.storage_key, commit=False
        )
    except ServiceError as exc:
        _private_object(root, stored.storage_key).unlink(missing_ok=True)
        raise SnapshotAssetError(
            "SNAPSHOT_ASSET_CONFLICT",
            "The snapshot Asset could not be created consistently",
            retryable=False,
        ) from exc
    except Exception as exc:
        _private_object(root, stored.storage_key).unlink(missing_ok=True)
        raise SnapshotAssetError(
            "SNAPSHOT_ASSET_WRITE_FAILED",
            "The snapshot Asset could not be written",
            retryable=True,
        ) from exc


def _record_video_sync(
    source: PlatformVideoSource,
    *,
    output_path: Path,
    max_bytes: int,
) -> tuple[str, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        YINGMU_FFMPEG_BINARY, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source.temporary_url), "-t", str(YINGMU_VIDEO_CAPTURE_SECONDS),
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=max(30, YINGMU_VIDEO_CAPTURE_SECONDS + 30),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        output_path.unlink(missing_ok=True)
        raise SnapshotAssetError(
            "VIDEO_RECORDING_UNAVAILABLE", "The live video could not be recorded", retryable=True
        ) from exc
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        output_path.unlink(missing_ok=True)
        raise SnapshotAssetError("VIDEO_RECORDING_EMPTY", "The recorded video is empty", retryable=True)

    try:
        _validate_recorded_video(
            _probe_recorded_video(output_path),
            expected_seconds=YINGMU_VIDEO_CAPTURE_SECONDS,
            expected_codec="h264",
        )
    except SnapshotAssetError:
        output_path.unlink(missing_ok=True)
        raise

    byte_size = output_path.stat().st_size
    if byte_size > max_bytes:
        output_path.unlink(missing_ok=True)
        raise SnapshotAssetError("VIDEO_TOO_LARGE", "The recorded video exceeds the configured byte limit", retryable=False)
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    return digest, byte_size


def _ffprobe_binary() -> str:
    configured = Path(YINGMU_FFMPEG_BINARY)
    suffix = configured.suffix if configured.name.lower().startswith("ffmpeg") else ""
    if configured.name.lower().startswith("ffmpeg"):
        return str(configured.with_name(f"ffprobe{suffix}"))
    return "ffprobe"


def _parse_frame_rate(value: object) -> float:
    try:
        numerator, denominator = str(value).split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else 0.0
    except (TypeError, ValueError):
        return 0.0


def _probe_recorded_video(output_path: Path) -> VideoProbe:
    command = [
        _ffprobe_binary(), "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "format=duration:stream=codec_name,avg_frame_rate,nb_read_frames",
        "-of", "json", str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=max(30, YINGMU_VIDEO_CAPTURE_SECONDS + 30),
        )
        payload = json.loads(completed.stdout)
        streams = payload.get("streams") or []
        stream = streams[0]
        return VideoProbe(
            duration_seconds=float((payload.get("format") or {}).get("duration", 0)),
            frame_rate=_parse_frame_rate(stream.get("avg_frame_rate")),
            frame_count=int(stream.get("nb_read_frames", 0)),
            codec_name=str(stream.get("codec_name") or "").lower() or None,
        )
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError, TypeError, ValueError) as exc:
        raise SnapshotAssetError(
            "VIDEO_VALIDATION_UNAVAILABLE",
            "The recorded video could not be validated",
            retryable=False,
        ) from exc


def _validate_recorded_video(
    probe: VideoProbe,
    *,
    expected_seconds: int,
    expected_codec: str | None = None,
) -> None:
    if expected_codec and probe.codec_name != expected_codec.lower():
        raise SnapshotAssetError(
            "VIDEO_CODEC_UNSUPPORTED",
            "The live video codec does not match the verified baseline",
            retryable=False,
        )
    minimum_duration = expected_seconds * VIDEO_MIN_DURATION_RATIO
    if not math.isfinite(probe.duration_seconds) or probe.duration_seconds < minimum_duration:
        raise SnapshotAssetError(
            "VIDEO_DURATION_INSUFFICIENT",
            "The provider video ended before the required capture window",
            retryable=True,
        )
    if not math.isfinite(probe.frame_rate) or probe.frame_rate < VIDEO_MIN_FRAME_RATE:
        raise SnapshotAssetError(
            "VIDEO_FRAME_RATE_INSUFFICIENT",
            "The provider video does not contain enough temporal detail for analysis",
            retryable=True,
        )
    minimum_frames = math.ceil(minimum_duration * VIDEO_MIN_FRAME_RATE)
    if probe.frame_count < minimum_frames:
        raise SnapshotAssetError(
            "VIDEO_FRAME_COUNT_INSUFFICIENT",
            "The provider video does not contain enough decodable frames for analysis",
            retryable=True,
        )


async def persist_live_video_asset(
    db: AsyncSession,
    source: PlatformVideoSource,
    *,
    task_id: str,
) -> tuple[dict, bool]:
    retention = _authorized_retention(YINGMU_RETENTION_UNTIL, source.captured_at)
    root = _private_root(YINGMU_PRIVATE_MEDIA_ROOT)
    asset_id = f"asset-live-video-{hashlib.sha256(task_id.encode('utf-8')).hexdigest()[:24]}"
    output_path = root / f"{asset_id}.mp4"
    existing = (await db.execute(select(AssetRow).where(AssetRow.asset_id == asset_id))).scalar_one_or_none()
    if existing is not None:
        if not existing.storage_key or not (root / existing.storage_key).is_file():
            raise SnapshotAssetError("ASSET_PRIVATE_OBJECT_MISSING", "The existing video Asset has no private object", retryable=False)
        return asset_dict(existing), True
    digest, byte_size = await asyncio.to_thread(
        _record_video_sync, source, output_path=output_path, max_bytes=YINGMU_SNAPSHOT_MAX_BYTES * 30
    )
    payload = AssetCreate(
        asset_id=asset_id,
        title="Ezviz live alert video",
        source_mode="LIVE_DEVICE",
        simulated=False,
        stream_url=None,
        fallback_url=None,
        fallback_kind="SERVER_MANAGED_VIDEO",
        available=True,
        verification_status="VERIFIED_LIVE_CAPTURE",
        captured_at=source.captured_at,
        notice="Recorded from the Ezviz live stream and stored privately",
        device_ref=source.device_ref,
        device_model=EZVIZ_DEVICE_MODEL,
        camera_position_id=YINGMU_CAMERA_POSITION_ID,
        authorization_status="AUTHORIZED",
        authorization_record_id=YINGMU_AUTHORIZATION_RECORD_ID,
        retention_until=retention,
        content_sha256=digest,
        content_type="video/mp4",
        byte_size=byte_size,
    )
    try:
        return await create_asset(db, payload, storage_key=output_path.name, commit=False)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
