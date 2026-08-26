"""Maintain the private Ezviz pre-alarm video ring buffer."""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone

from backend.config import (
    ENV_MODE,
    EZVIZ_LIVE_PLAYBACK_VERIFIED,
    YINGMU_STREAM_BUFFER_ENABLED,
    YINGMU_STREAM_BUFFER_PRE_SECONDS,
    YINGMU_STREAM_BUFFER_RECONNECT_SECONDS,
    YINGMU_STREAM_BUFFER_RETENTION_SECONDS,
    YINGMU_STREAM_BUFFER_SEGMENT_SECONDS,
    YINGMU_STREAM_BUFFER_STALL_SECONDS,
)
from backend.service.device_adapter import device_adapter
from backend.service.stream_buffer_service import (
    acquire_stream_buffer_lock,
    build_buffer_ffmpeg_command,
    buffer_session_stalled,
    cleanup_stream_buffer,
    continuous_coverage_before,
    create_buffer_session,
    inventory_buffer_segments,
    purge_stream_buffer_runtime,
    resolve_stream_buffer_root,
    release_stream_buffer_lock,
    validate_stream_buffer_authorization,
    write_buffer_status,
)
from backend.service.snapshot_asset_service import SnapshotAssetError


logger = logging.getLogger("backend.stream_buffer_worker")


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


async def run_session(root) -> int:
    validate_stream_buffer_authorization()
    source = await device_adapter.capture_video_source()
    session_id, session_dir = create_buffer_session(root)
    command = build_buffer_ffmpeg_command(source, session_dir)
    write_buffer_status(root, status="STARTING", session_id=session_id, segment_count=0)
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    session_started_at = datetime.now(timezone.utc)
    logger.info("stream_buffer_session_started session_id=%s", session_id)
    try:
        while process.returncode is None:
            await asyncio.sleep(max(1.0, float(YINGMU_STREAM_BUFFER_SEGMENT_SECONDS)))
            validate_stream_buffer_authorization()
            cleanup_stream_buffer(
                root,
                retention_seconds=YINGMU_STREAM_BUFFER_RETENTION_SECONDS,
                active_session_id=session_id,
            )
            segments = inventory_buffer_segments(root)
            session_segments = [item for item in segments if item.path.parent == session_dir]
            if buffer_session_stalled(
                segments,
                session_dir,
                session_started_at=session_started_at,
                stall_seconds=YINGMU_STREAM_BUFFER_STALL_SECONDS,
            ):
                logger.warning("stream_buffer_session_stalled session_id=%s", session_id)
                await _stop_process(process)
                return 75
            count = len(session_segments)
            newest_endpoint = session_segments[-1].ended_at if session_segments else datetime.now(timezone.utc)
            warm_coverage = continuous_coverage_before(
                session_segments,
                newest_endpoint,
                required_seconds=YINGMU_STREAM_BUFFER_PRE_SECONDS,
            )
            write_buffer_status(
                root,
                status=(
                    "READY"
                    if warm_coverage >= YINGMU_STREAM_BUFFER_PRE_SECONDS
                    else "WARMING"
                ),
                session_id=session_id,
                segment_count=count,
            )
        return await process.wait()
    finally:
        await _stop_process(process)


async def run(*, once: bool = False) -> int:
    if not YINGMU_STREAM_BUFFER_ENABLED:
        raise RuntimeError("YINGMU_STREAM_BUFFER_ENABLED must be true")
    if ENV_MODE != "live":
        raise RuntimeError("stream buffer worker requires YINGMU_ENV=live")
    if not EZVIZ_LIVE_PLAYBACK_VERIFIED:
        raise RuntimeError("stream buffer worker requires verified live playback")
    root = resolve_stream_buffer_root()
    lock_path = acquire_stream_buffer_lock(root)
    try:
        while True:
            try:
                return_code = await run_session(root)
                write_buffer_status(
                    root,
                    status="RECONNECTING",
                    session_id=None,
                    segment_count=len(inventory_buffer_segments(root)),
                    error_code="FFMPEG_EXITED",
                )
                logger.warning("stream_buffer_session_ended return_code=%s", return_code)
            except asyncio.CancelledError:
                write_buffer_status(
                    root,
                    status="STOPPED",
                    session_id=None,
                    segment_count=len(inventory_buffer_segments(root)),
                )
                raise
            except SnapshotAssetError as exc:
                write_buffer_status(
                    root,
                    status="STOPPED",
                    session_id=None,
                    segment_count=len(inventory_buffer_segments(root)),
                    error_code=exc.code,
                )
                logger.error("stream_buffer_authorization_stopped error_code=%s", exc.code)
                return 2
            except Exception as exc:
                error_code = type(exc).__name__
                write_buffer_status(
                    root,
                    status="RECONNECTING",
                    session_id=None,
                    segment_count=len(inventory_buffer_segments(root)),
                    error_code=error_code,
                )
                logger.warning("stream_buffer_session_failed error_type=%s", error_code)
            if once:
                return 1
            await asyncio.sleep(YINGMU_STREAM_BUFFER_RECONNECT_SECONDS)
    finally:
        release_stream_buffer_lock(lock_path)
        purge_stream_buffer_runtime(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintain the private pre-alarm video buffer.")
    parser.add_argument("--once", action="store_true", help="Run one stream session and exit.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        return asyncio.run(run(once=args.once))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
