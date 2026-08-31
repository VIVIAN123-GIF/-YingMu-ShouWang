"""Private rolling video buffer used to preserve pre-alarm motion."""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import (
    EZVIZ_DEVICE_MODEL,
    YINGMU_AUTHORIZATION_RECORD_ID,
    YINGMU_CAMERA_POSITION_ID,
    YINGMU_FFMPEG_BINARY,
    YINGMU_PRIVATE_MEDIA_ROOT,
    YINGMU_RETENTION_UNTIL,
    YINGMU_SNAPSHOT_MAX_BYTES,
    YINGMU_STREAM_BUFFER_POST_SECONDS,
    YINGMU_STREAM_BUFFER_PRE_SECONDS,
    YINGMU_STREAM_BUFFER_MAX_ALARM_DELAY_SECONDS,
    YINGMU_STREAM_BUFFER_RETENTION_SECONDS,
    YINGMU_STREAM_BUFFER_ROOT,
    YINGMU_STREAM_BUFFER_SELECTION_RETRY_SECONDS,
    YINGMU_STREAM_BUFFER_SEGMENT_SECONDS,
    YINGMU_STREAM_BUFFER_STALL_SECONDS,
)
from backend.db.models import Asset as AssetRow
from backend.schemas.asset import AssetCreate
from backend.service.asset_service import asset_dict, create_asset
from backend.service.snapshot_asset_service import (
    REPOSITORY_ROOT,
    SnapshotAssetError,
    _authorized_retention,
    _private_object,
    _private_root,
    _probe_recorded_video,
    _validate_recorded_video,
)
from contracts.v1.platform import PlatformVideoSource


CN_TZ = timezone(timedelta(hours=8))
UTC = timezone.utc
SESSIONS_DIRECTORY = "sessions"
WORK_DIRECTORY = "work"
STATUS_FILENAME = "status.json"
LOCK_FILENAME = "worker.lock"


class StreamBufferError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class BufferedSegment:
    path: Path
    started_at: datetime
    ended_at: datetime
    byte_size: int


@dataclass(frozen=True)
class BufferSelection:
    alarm_time: datetime
    window_start: datetime
    window_end: datetime
    coverage_seconds: float
    segments: tuple[BufferedSegment, ...]


def _aware_alarm_time(value: datetime) -> datetime:
    aware = value.replace(tzinfo=CN_TZ) if value.tzinfo is None else value
    return aware.astimezone(UTC)


def resolve_stream_buffer_root(value: str | None = None) -> Path:
    configured = value if value is not None else YINGMU_STREAM_BUFFER_ROOT
    if configured and configured.strip():
        candidate = configured
    elif YINGMU_PRIVATE_MEDIA_ROOT.strip():
        candidate = str(Path(YINGMU_PRIVATE_MEDIA_ROOT) / ".stream-buffer")
    else:
        raise StreamBufferError(
            "STREAM_BUFFER_ROOT_REQUIRED",
            "Private stream buffer storage is not configured",
        )
    try:
        root = _private_root(candidate)
    except SnapshotAssetError as exc:
        raise StreamBufferError("STREAM_BUFFER_ROOT_UNSAFE", exc.message) from exc
    for child in (SESSIONS_DIRECTORY, WORK_DIRECTORY):
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


def validate_stream_buffer_authorization(now: datetime | None = None) -> datetime:
    captured_at = now or datetime.now(CN_TZ)
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        captured_at = captured_at.replace(tzinfo=CN_TZ)
    return _authorized_retention(YINGMU_RETENTION_UNTIL, captured_at)


def create_buffer_session(root: Path) -> tuple[str, Path]:
    session_id = f"session-{uuid4().hex}"
    session_dir = (root / SESSIONS_DIRECTORY / session_id).resolve()
    try:
        session_dir.relative_to((root / SESSIONS_DIRECTORY).resolve())
    except ValueError as exc:
        raise StreamBufferError("STREAM_BUFFER_SESSION_INVALID", "Buffer session path is invalid") from exc
    session_dir.mkdir(parents=True, exist_ok=False)
    return session_id, session_dir


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def acquire_stream_buffer_lock(root: Path) -> Path:
    """Atomically enforce one buffer writer without serializing private paths."""
    lock_path = root / LOCK_FILENAME
    payload = json.dumps(
        {
            "schema_version": "stream-buffer-lock/1.0",
            "pid": os.getpid(),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "contains_credentials": False,
        },
        sort_keys=True,
    )
    for _attempt in range(2):
        try:
            with lock_path.open("x", encoding="utf-8") as handle:
                handle.write(payload)
            return lock_path
        except FileExistsError:
            try:
                existing = json.loads(lock_path.read_text(encoding="utf-8"))
                existing_pid = int(existing.get("pid", 0))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                existing_pid = 0
            if _process_is_running(existing_pid):
                raise StreamBufferError(
                    "STREAM_BUFFER_WORKER_ALREADY_RUNNING",
                    "Another rolling buffer worker already owns the device stream",
                )
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
    raise StreamBufferError(
        "STREAM_BUFFER_LOCK_FAILED",
        "The rolling buffer worker lock could not be acquired",
    )


def _acquire_stream_buffer_cleanup_lock(root: Path) -> tuple[Path, bool]:
    """Atomically exclude a worker while transient artifacts are removed."""
    lock_path = root / LOCK_FILENAME
    payload = json.dumps(
        {
            "schema_version": "stream-buffer-lock/1.0",
            "pid": os.getpid(),
            "owner": "SHUTDOWN_CLEANUP",
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "contains_credentials": False,
        },
        sort_keys=True,
    )
    stale_removed = False
    for _attempt in range(3):
        try:
            with lock_path.open("x", encoding="utf-8") as handle:
                handle.write(payload)
            return lock_path, stale_removed
        except FileExistsError:
            try:
                existing = json.loads(lock_path.read_text(encoding="utf-8"))
                existing_pid = int(existing.get("pid", 0))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                existing_pid = 0
            if _process_is_running(existing_pid):
                raise StreamBufferError(
                    "STREAM_BUFFER_WORKER_STILL_ACTIVE",
                    "The rolling buffer worker is still active during shutdown cleanup",
                )
            try:
                lock_path.unlink()
                stale_removed = True
            except FileNotFoundError:
                pass
    raise StreamBufferError(
        "STREAM_BUFFER_PURGE_LOCK_FAILED",
        "Shutdown cleanup could not exclusively lock the rolling buffer",
    )


def release_stream_buffer_lock(lock_path: Path) -> None:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        if int(payload.get("pid", 0)) != os.getpid():
            return
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return
    lock_path.unlink(missing_ok=True)


def build_buffer_ffmpeg_command(
    source: PlatformVideoSource,
    session_dir: Path,
    *,
    segment_seconds: int | None = None,
) -> list[str]:
    seconds = segment_seconds or YINGMU_STREAM_BUFFER_SEGMENT_SECONDS
    output_pattern = session_dir / "segment-%09d.ts"
    return [
        YINGMU_FFMPEG_BINARY,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-rw_timeout",
        str(YINGMU_STREAM_BUFFER_STALL_SECONDS * 1_000_000),
        "-i",
        str(source.temporary_url),
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-sc_threshold",
        "0",
        "-force_key_frames",
        f"expr:gte(t,n_forced*{seconds})",
        "-f",
        "segment",
        "-segment_format",
        "mpegts",
        "-segment_time",
        str(seconds),
        "-reset_timestamps",
        "1",
        str(output_pattern),
    ]


def write_buffer_status(
    root: Path,
    *,
    status: str,
    session_id: str | None,
    segment_count: int,
    error_code: str | None = None,
) -> None:
    payload = {
        "schema_version": "stream-buffer-status/1.0",
        "status": status,
        "session_id": session_id,
        "segment_count": segment_count,
        "error_code": error_code,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "contains_credentials": False,
    }
    temporary = root / f".{STATUS_FILENAME}.{uuid4().hex}.tmp"
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.replace(root / STATUS_FILENAME)


def inventory_buffer_segments(
    root: Path,
    *,
    now: datetime | None = None,
    segment_seconds: int | None = None,
    settle_seconds: float = 0.5,
) -> list[BufferedSegment]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    duration = float(segment_seconds or YINGMU_STREAM_BUFFER_SEGMENT_SECONDS)
    segments: list[BufferedSegment] = []
    for path in (root / SESSIONS_DIRECTORY).glob("session-*/segment-*.ts"):
        try:
            stat = path.stat()
        except OSError:
            continue
        ended_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        if stat.st_size <= 0 or ended_at > current - timedelta(seconds=settle_seconds):
            continue
        segments.append(
            BufferedSegment(
                path=path,
                started_at=ended_at - timedelta(seconds=duration),
                ended_at=ended_at,
                byte_size=stat.st_size,
            )
        )
    return sorted(segments, key=lambda item: (item.started_at, item.path.name))


def active_session_segments(root: Path, segments: list[BufferedSegment]) -> list[BufferedSegment]:
    """Return closed segments from the Worker session named in status.json."""
    try:
        status = json.loads((root / STATUS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return segments
    session_id = status.get("session_id") if isinstance(status, dict) else None
    if not isinstance(session_id, str) or not session_id:
        return segments
    selected = [item for item in segments if item.path.parent.name == session_id]
    if status.get("status") in {"STARTING", "WARMING", "READY"} and selected:
        # FFmpeg closes a segment only when it opens the next one. Its current
        # output can have an old mtime between write bursts, so settle-time
        # checks alone cannot prove that the highest-index file is complete.
        newest = max(selected, key=lambda item: (_segment_index(item) or -1, item.path.name))
        selected.remove(newest)
    return selected


def buffer_session_stalled(
    segments: list[BufferedSegment],
    session_dir: Path,
    *,
    session_started_at: datetime,
    now: datetime | None = None,
    stall_seconds: int | None = None,
) -> bool:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    threshold = stall_seconds or YINGMU_STREAM_BUFFER_STALL_SECONDS
    session_segments = [item for item in segments if item.path.parent == session_dir]
    if not session_segments:
        return (current - session_started_at).total_seconds() > threshold
    newest = max(item.ended_at for item in session_segments)
    return (current - newest).total_seconds() > threshold


def _coverage_seconds(
    segments: list[BufferedSegment],
    window_start: datetime,
    window_end: datetime,
    *,
    gap_tolerance_seconds: float = 0.0,
) -> float:
    intervals = sorted(
        (
            max(item.started_at, window_start),
            min(item.ended_at, window_end),
        )
        for item in segments
        if item.ended_at > window_start and item.started_at < window_end
    )
    if not intervals:
        return 0.0
    total = 0.0
    start, end = intervals[0]
    for next_start, next_end in intervals[1:]:
        if next_start <= end + timedelta(seconds=gap_tolerance_seconds):
            end = max(end, next_end)
            continue
        total += (end - start).total_seconds()
        start, end = next_start, next_end
    return total + (end - start).total_seconds()


def _segment_index(segment: BufferedSegment) -> int | None:
    stem = segment.path.stem
    try:
        return int(stem.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return None


def _validate_continuous_segments(
    segments: list[BufferedSegment], *, segment_seconds: int
) -> None:
    """Reject gaps and overlapping capture sessions before coverage is measured."""
    if len(segments) < 2:
        return
    tolerance = max(0.25, segment_seconds * 0.25)
    ordered = sorted(segments, key=lambda item: (item.started_at, item.path.name))
    for previous, current in zip(ordered, ordered[1:]):
        previous_session = previous.path.parent.name
        current_session = current.path.parent.name
        gap = (current.started_at - previous.ended_at).total_seconds()
        if previous_session == current_session:
            previous_index = _segment_index(previous)
            current_index = _segment_index(current)
            if (
                previous_index is not None
                and current_index is not None
                and current_index != previous_index + 1
            ):
                raise StreamBufferError(
                    "STREAM_BUFFER_SEGMENT_GAP",
                    "A rolling buffer segment is missing",
                )
            if abs(gap) > tolerance:
                raise StreamBufferError(
                    "STREAM_BUFFER_SEGMENT_GAP",
                    "The rolling buffer contains a discontinuity",
                )
            continue
        if gap < -tolerance:
            raise StreamBufferError(
                "STREAM_BUFFER_SESSION_OVERLAP",
                "Overlapping rolling buffer sessions cannot be combined",
            )
        if gap > segment_seconds + tolerance:
            raise StreamBufferError(
                "STREAM_BUFFER_SEGMENT_GAP",
                "The rolling buffer contains a cross-session gap",
            )


def continuous_coverage_before(
    segments: list[BufferedSegment],
    endpoint: datetime,
    *,
    required_seconds: int,
    segment_seconds: int | None = None,
) -> float:
    """Return continuous coverage ending at the newest completed segment."""
    if not segments:
        return 0.0
    duration = YINGMU_STREAM_BUFFER_SEGMENT_SECONDS if segment_seconds is None else segment_seconds
    ordered = sorted(
        (item for item in segments if item.ended_at <= endpoint),
        key=lambda item: (item.started_at, item.path.name),
    )
    if not ordered:
        return 0.0
    newest_end = ordered[-1].ended_at
    start = newest_end - timedelta(seconds=required_seconds)
    selected = [item for item in ordered if item.ended_at > start]
    try:
        _validate_continuous_segments(selected, segment_seconds=duration)
    except StreamBufferError:
        return 0.0
    if selected[0].started_at > start:
        return max(0.0, (newest_end - selected[0].started_at).total_seconds())
    return float(required_seconds)


def warm_coverage_ready(
    coverage_seconds: float,
    *,
    required_seconds: int,
    segment_seconds: int | None = None,
) -> bool:
    """Apply the same filesystem timestamp tolerance used by alarm selection."""
    duration = YINGMU_STREAM_BUFFER_SEGMENT_SECONDS if segment_seconds is None else segment_seconds
    tolerance = max(0.25, duration * 0.25)
    return coverage_seconds >= max(0.0, required_seconds - tolerance)


def select_alarm_window(
    segments: list[BufferedSegment],
    alarm_time: datetime,
    *,
    pre_seconds: int | None = None,
    post_seconds: int | None = None,
    segment_seconds: int | None = None,
) -> BufferSelection:
    before = YINGMU_STREAM_BUFFER_PRE_SECONDS if pre_seconds is None else pre_seconds
    after = YINGMU_STREAM_BUFFER_POST_SECONDS if post_seconds is None else post_seconds
    duration = YINGMU_STREAM_BUFFER_SEGMENT_SECONDS if segment_seconds is None else segment_seconds
    normalized_alarm = _aware_alarm_time(alarm_time)
    window_start = normalized_alarm - timedelta(seconds=before)
    window_end = normalized_alarm + timedelta(seconds=after)
    selected = [
        item
        for item in segments
        if item.ended_at > window_start and item.started_at < window_end
    ]
    if not selected:
        raise StreamBufferError("STREAM_BUFFER_EMPTY", "No completed buffer segments cover the alarm")

    _validate_continuous_segments(selected, segment_seconds=duration)
    boundary_tolerance = timedelta(seconds=max(0.25, duration * 0.25))
    coverage = _coverage_seconds(
        selected,
        window_start,
        window_end,
        gap_tolerance_seconds=boundary_tolerance.total_seconds(),
    )
    minimum_coverage = max(1.0, before + after - boundary_tolerance.total_seconds())
    if (
        selected[0].started_at > window_start + boundary_tolerance
        or selected[-1].ended_at < window_end - boundary_tolerance
        or coverage < minimum_coverage
    ):
        raise StreamBufferError(
            "STREAM_BUFFER_COVERAGE_INSUFFICIENT",
            "The rolling buffer does not cover the required alarm window",
        )
    return BufferSelection(
        alarm_time=normalized_alarm,
        window_start=window_start,
        window_end=window_end,
        coverage_seconds=coverage,
        segments=tuple(selected),
    )


def cleanup_stream_buffer(
    root: Path,
    *,
    retention_seconds: int | None = None,
    now: datetime | None = None,
    active_session_id: str | None = None,
) -> int:
    retention = retention_seconds or YINGMU_STREAM_BUFFER_RETENTION_SECONDS
    current = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff = current - timedelta(seconds=retention)
    removed = 0
    sessions_root = root / SESSIONS_DIRECTORY
    for path in sessions_root.glob("session-*/segment-*.ts"):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if modified < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    for session_dir in sessions_root.glob("session-*"):
        if session_dir.name == active_session_id:
            continue
        try:
            session_dir.rmdir()
        except OSError:
            pass

    work_root = root / WORK_DIRECTORY
    for workspace in work_root.glob("task-*"):
        try:
            modified = datetime.fromtimestamp(workspace.stat().st_mtime, tz=UTC)
            if modified < cutoff:
                shutil.rmtree(workspace, ignore_errors=True)
        except OSError:
            continue
    return removed


def purge_stream_buffer_runtime(
    root: Path | None = None,
) -> dict[str, int | bool]:
    """Remove only transient rolling-buffer artifacts from a validated private root."""
    buffer_root = resolve_stream_buffer_root(str(root) if root is not None else None)
    sessions_root = buffer_root / SESSIONS_DIRECTORY
    work_root = buffer_root / WORK_DIRECTORY
    lock_path, stale_lock_removed = _acquire_stream_buffer_cleanup_lock(buffer_root)
    removed_segments = 0
    removed_workspaces = 0
    failures = False
    status_removed = False
    lock_removed = False
    try:
        for path in sessions_root.glob("session-*/segment-*.ts"):
            try:
                path.unlink(missing_ok=True)
                removed_segments += 1
            except OSError:
                failures = True
        for session_dir in sessions_root.glob("session-*"):
            try:
                session_dir.rmdir()
            except OSError:
                pass

        for path in (*work_root.glob("task-*"), *work_root.glob("probe-*.mp4")):
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
                removed_workspaces += 1
            except OSError:
                failures = True

        status_path = buffer_root / STATUS_FILENAME
        try:
            status_removed = status_path.exists()
            status_path.unlink(missing_ok=True)
        except OSError:
            failures = True
    finally:
        try:
            release_stream_buffer_lock(lock_path)
            lock_removed = not lock_path.exists()
        except OSError:
            failures = True

    if failures:
        raise StreamBufferError(
            "STREAM_BUFFER_PURGE_FAILED",
            "One or more transient stream buffer artifacts could not be removed",
        )
    return {
        "removed_segments": removed_segments,
        "removed_workspaces": removed_workspaces,
        "status_removed": status_removed,
        "lock_removed": lock_removed or stale_lock_removed,
        "lock_active": False,
    }


def _concat_manifest_line(path: Path) -> str:
    name = path.name
    if Path(name).name != name or "'" in name or "\n" in name or "\r" in name:
        raise StreamBufferError("STREAM_BUFFER_SEGMENT_NAME_INVALID", "A buffer segment name is invalid")
    return f"file '{name}'\n"


def _assemble_selection_sync(
    selection: BufferSelection,
    *,
    root: Path,
    output_path: Path,
    task_id: str,
    max_bytes: int,
) -> tuple[str, int, float]:
    task_digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:24]
    workspace = root / WORK_DIRECTORY / f"task-{task_digest}-{uuid4().hex}"
    temporary_output = output_path.with_name(f".{output_path.name}.{uuid4().hex}.part.mp4")
    workspace.mkdir(parents=True, exist_ok=False)
    try:
        copied: list[Path] = []
        for index, segment in enumerate(selection.segments):
            destination = workspace / f"segment-{index:05d}.ts"
            shutil.copy2(segment.path, destination)
            if destination.stat().st_size != segment.byte_size:
                raise StreamBufferError(
                    "STREAM_BUFFER_SEGMENT_CHANGED",
                    "A rolling segment changed while it was being isolated",
                )
            copied.append(destination)
        manifest = workspace / "concat.txt"
        manifest.write_text("".join(_concat_manifest_line(path) for path in copied), encoding="ascii")
        trim_start = max(
            0.0,
            (selection.window_start - selection.segments[0].started_at).total_seconds(),
        )
        target_duration = (selection.window_end - selection.window_start).total_seconds()
        command = [
            YINGMU_FFMPEG_BINARY,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(manifest),
            "-ss",
            f"{trim_start:.3f}",
            "-t",
            f"{target_duration:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(temporary_output),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                timeout=max(45, int(selection.coverage_seconds) + 45),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise StreamBufferError(
                "STREAM_BUFFER_ASSEMBLY_FAILED",
                "The buffered alarm video could not be assembled",
            ) from exc
        if not temporary_output.is_file() or temporary_output.stat().st_size <= 0:
            raise StreamBufferError("STREAM_BUFFER_ASSEMBLY_EMPTY", "The buffered alarm video is empty")
        expected_seconds = max(1, int(math.floor(selection.coverage_seconds)))
        try:
            probe = _probe_recorded_video(temporary_output)
            _validate_recorded_video(
                probe,
                expected_seconds=expected_seconds,
                expected_codec="h264",
            )
        except SnapshotAssetError as exc:
            code = exc.code if exc.code == "VIDEO_CODEC_UNSUPPORTED" else "STREAM_BUFFER_VIDEO_INVALID"
            raise StreamBufferError(code, exc.message) from exc
        byte_size = temporary_output.stat().st_size
        if byte_size > max_bytes:
            raise StreamBufferError("STREAM_BUFFER_VIDEO_TOO_LARGE", "The buffered video exceeds its size limit")
        digest = hashlib.sha256(temporary_output.read_bytes()).hexdigest()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_output.replace(output_path)
        return digest, byte_size, probe.duration_seconds
    except StreamBufferError:
        raise
    except OSError as exc:
        raise StreamBufferError(
            "STREAM_BUFFER_IO_FAILED",
            "The buffered alarm video could not be isolated or stored",
        ) from exc
    finally:
        temporary_output.unlink(missing_ok=True)
        shutil.rmtree(workspace, ignore_errors=True)


async def wait_for_alarm_window(
    alarm_time: datetime,
    *,
    post_seconds: int | None = None,
    segment_seconds: int | None = None,
) -> None:
    after = YINGMU_STREAM_BUFFER_POST_SECONDS if post_seconds is None else post_seconds
    duration = YINGMU_STREAM_BUFFER_SEGMENT_SECONDS if segment_seconds is None else segment_seconds
    required_at = _aware_alarm_time(alarm_time) + timedelta(seconds=after + duration + 0.75)
    delay = (required_at - datetime.now(UTC)).total_seconds()
    maximum_delay = after + duration + 5
    if delay > maximum_delay:
        raise StreamBufferError("STREAM_BUFFER_ALARM_TIME_INVALID", "The alarm time is unexpectedly in the future")
    if delay > 0:
        await asyncio.sleep(delay)


async def select_alarm_window_with_retry(
    root: Path,
    alarm_time: datetime,
    *,
    retry_seconds: float | None = None,
) -> BufferSelection:
    """Wait briefly for the final completed segment without moving the alarm anchor."""
    retry_for = (
        YINGMU_STREAM_BUFFER_SELECTION_RETRY_SECONDS
        if retry_seconds is None
        else retry_seconds
    )
    deadline = asyncio.get_running_loop().time() + max(0.0, retry_for)
    retryable_codes = {
        "STREAM_BUFFER_EMPTY",
        "STREAM_BUFFER_COVERAGE_INSUFFICIENT",
    }
    while True:
        segments = await asyncio.to_thread(inventory_buffer_segments, root)
        segments = active_session_segments(root, segments)
        try:
            return select_alarm_window(segments, alarm_time)
        except StreamBufferError as exc:
            remaining = deadline - asyncio.get_running_loop().time()
            if exc.code not in retryable_codes or remaining <= 0:
                raise
            await asyncio.sleep(min(0.5, remaining))


async def persist_buffered_video_asset(
    db: AsyncSession,
    *,
    task_id: str,
    alarm_time: datetime,
    device_ref: str,
) -> tuple[dict, bool]:
    root = resolve_stream_buffer_root()
    private_root = _private_root(YINGMU_PRIVATE_MEDIA_ROOT)
    asset_id = f"asset-live-video-{hashlib.sha256(task_id.encode('utf-8')).hexdigest()[:24]}"
    output_path = _private_object(private_root, f"{asset_id}.mp4")
    existing = (
        await db.execute(select(AssetRow).where(AssetRow.asset_id == asset_id))
    ).scalar_one_or_none()
    if existing is not None:
        if not existing.storage_key or not _private_object(private_root, existing.storage_key).is_file():
            raise StreamBufferError(
                "STREAM_BUFFER_ASSET_MISSING",
                "The existing buffered Asset has no private media object",
            )
        return asset_dict(existing), True

    alarm_age = (datetime.now(UTC) - _aware_alarm_time(alarm_time)).total_seconds()
    if alarm_age > YINGMU_STREAM_BUFFER_MAX_ALARM_DELAY_SECONDS:
        raise StreamBufferError(
            "STREAM_BUFFER_ALARM_DELAY_EXCEEDED",
            "The alarm arrived too late for the configured rolling buffer guarantee",
        )
    await wait_for_alarm_window(alarm_time)
    selection = await select_alarm_window_with_retry(root, alarm_time)
    captured_at = selection.window_start.astimezone(CN_TZ)
    retention = _authorized_retention(YINGMU_RETENTION_UNTIL, captured_at)
    max_bytes = YINGMU_SNAPSHOT_MAX_BYTES * 30
    digest, byte_size, _ = await asyncio.to_thread(
        _assemble_selection_sync,
        selection,
        root=root,
        output_path=output_path,
        task_id=task_id,
        max_bytes=max_bytes,
    )
    try:
        payload = AssetCreate(
            asset_id=asset_id,
            title="Ezviz buffered live alert video",
            source_mode="LIVE_DEVICE",
            simulated=False,
            stream_url=None,
            fallback_url=None,
            fallback_kind="SERVER_MANAGED_RING_BUFFER",
            available=True,
            verification_status="VERIFIED_LIVE_BUFFER_CAPTURE",
            captured_at=captured_at,
            notice="Assembled from an authorized short-lived private ring buffer",
            device_ref=device_ref,
            device_model=EZVIZ_DEVICE_MODEL,
            camera_position_id=YINGMU_CAMERA_POSITION_ID,
            authorization_status="AUTHORIZED",
            authorization_record_id=YINGMU_AUTHORIZATION_RECORD_ID,
            retention_until=retention,
            content_sha256=digest,
            content_type="video/mp4",
            byte_size=byte_size,
        )
        return await create_asset(db, payload, storage_key=output_path.name, commit=False)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise


def repository_contains_buffer(root: Path) -> bool:
    """Used by diagnostics without exposing the configured private path."""
    try:
        root.resolve().relative_to(REPOSITORY_ROOT)
        return True
    except ValueError:
        return False


def stream_buffer_health(root: Path | None = None) -> dict:
    buffer_root = root or resolve_stream_buffer_root()
    now = datetime.now(UTC)
    segments = inventory_buffer_segments(buffer_root, now=now)
    status_path = buffer_root / STATUS_FILENAME
    worker_status = "NOT_STARTED"
    error_code = None
    if status_path.is_file():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            worker_status = str(status.get("status") or "UNKNOWN")
            error_code = status.get("error_code")
        except (OSError, json.JSONDecodeError):
            worker_status = "STATUS_INVALID"
    # The worker's readiness refers to its current ffmpeg session. Previous
    # sessions can overlap in the retention window while a worker reconnects.
    # They must not make the current session look discontinuous.
    active_segments = active_session_segments(buffer_root, segments)
    newest_endpoint = active_segments[-1].ended_at if active_segments else now
    coverage = continuous_coverage_before(
        active_segments,
        newest_endpoint,
        required_seconds=YINGMU_STREAM_BUFFER_PRE_SECONDS,
    )
    newest_age = (
        max(0.0, (now - active_segments[-1].ended_at).total_seconds()) if active_segments else None
    )
    ready = bool(
        worker_status == "READY"
        and active_segments
        and warm_coverage_ready(
            coverage,
            required_seconds=YINGMU_STREAM_BUFFER_PRE_SECONDS,
        )
        and newest_age is not None
        and newest_age <= YINGMU_STREAM_BUFFER_SEGMENT_SECONDS * 3
    )
    return {
        "schema_version": "stream-buffer-health/1.0",
        "status": worker_status,
        "ready": ready,
        "completed_segments": len(active_segments),
        "pre_alarm_coverage_seconds": round(coverage, 3),
        "newest_segment_age_seconds": round(newest_age, 3) if newest_age is not None else None,
        "error_code": error_code,
        "contains_credentials": False,
        "contains_media_path": False,
    }


def probe_stream_buffer_assembly(root: Path | None = None) -> dict:
    buffer_root = root or resolve_stream_buffer_root()
    now = datetime.now(UTC)
    alarm_time = now - timedelta(
        seconds=YINGMU_STREAM_BUFFER_POST_SECONDS
        + YINGMU_STREAM_BUFFER_SEGMENT_SECONDS
        + 1
    )
    segments = active_session_segments(
        buffer_root, inventory_buffer_segments(buffer_root, now=now)
    )
    selection = select_alarm_window(segments, alarm_time)
    output_path = buffer_root / WORK_DIRECTORY / f"probe-{uuid4().hex}.mp4"
    try:
        _, byte_size, _ = _assemble_selection_sync(
            selection,
            root=buffer_root,
            output_path=output_path,
            task_id=f"stream-buffer-probe-{uuid4().hex}",
            max_bytes=YINGMU_SNAPSHOT_MAX_BYTES * 30,
        )
        probe = _probe_recorded_video(output_path)
        return {
            "schema_version": "stream-buffer-probe/1.0",
            "result": "SUCCESS",
            "selected_segments": len(selection.segments),
            "coverage_seconds": round(selection.coverage_seconds, 3),
            "duration_seconds": round(probe.duration_seconds, 3),
            "frame_rate": round(probe.frame_rate, 3),
            "frame_count": probe.frame_count,
            "codec_name": probe.codec_name,
            "byte_size": byte_size,
            "contains_credentials": False,
            "contains_media_path": False,
            "media_retained": False,
        }
    finally:
        output_path.unlink(missing_ok=True)
