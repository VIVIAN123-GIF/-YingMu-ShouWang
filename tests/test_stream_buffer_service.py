from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.models import Asset as AssetRow
from backend.service import alarm_task_service
from backend.service import algorithm_task_service
from backend.service.stream_buffer_service import (
    acquire_stream_buffer_lock,
    BufferedSegment,
    StreamBufferError,
    buffer_session_stalled,
    build_buffer_ffmpeg_command,
    cleanup_stream_buffer,
    create_buffer_session,
    inventory_buffer_segments,
    purge_stream_buffer_runtime,
    resolve_stream_buffer_root,
    release_stream_buffer_lock,
    select_alarm_window,
    select_alarm_window_with_retry,
    stream_buffer_health,
    write_buffer_status,
)
from backend.service import stream_buffer_service
from backend.service import snapshot_asset_service
from contracts.v1.platform import PlatformVideoSource


UTC = timezone.utc


def segment(path: Path, start: datetime, seconds: int = 2) -> BufferedSegment:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"segment")
    return BufferedSegment(
        path=path,
        started_at=start,
        ended_at=start + timedelta(seconds=seconds),
        byte_size=path.stat().st_size,
    )


def source() -> PlatformVideoSource:
    return PlatformVideoSource(
        schema_version="platform-video/1.0",
        request_id="stream-buffer-test-001",
        device_ref="device-buffer-test",
        channel_no=1,
        captured_at="2026-08-25T21:00:00+08:00",
        source_mode="LIVE_DEVICE",
        simulated=False,
        temporary_url="https://stream.example/private.flv",
        expires_at="2026-08-25T21:05:00+08:00",
        provider_latency_ms=10,
    )


def test_stream_buffer_root_must_be_outside_repository():
    with pytest.raises(StreamBufferError) as caught:
        resolve_stream_buffer_root(str(Path.cwd() / "unsafe-buffer"))
    assert caught.value.code == "STREAM_BUFFER_ROOT_UNSAFE"


def test_stream_buffer_lock_rejects_duplicate_writer_and_releases(tmp_path):
    root = resolve_stream_buffer_root(str(tmp_path / "buffer"))
    lock_path = acquire_stream_buffer_lock(root)

    with pytest.raises(StreamBufferError) as caught:
        acquire_stream_buffer_lock(root)

    assert caught.value.code == "STREAM_BUFFER_WORKER_ALREADY_RUNNING"
    release_stream_buffer_lock(lock_path)
    assert not lock_path.exists()
    replacement = acquire_stream_buffer_lock(root)
    release_stream_buffer_lock(replacement)


def test_complete_alarm_window_is_selected(tmp_path):
    alarm = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)
    start = alarm - timedelta(seconds=12)
    segments = [
        segment(tmp_path / f"segment-{index:03d}.ts", start + timedelta(seconds=index * 2))
        for index in range(17)
    ]

    selected = select_alarm_window(
        segments,
        alarm,
        pre_seconds=10,
        post_seconds=20,
        segment_seconds=2,
    )

    assert len(selected.segments) == 15
    assert selected.window_start == alarm - timedelta(seconds=10)
    assert selected.window_end == alarm + timedelta(seconds=20)
    assert selected.coverage_seconds == 30


def test_alarm_window_with_missing_leading_buffer_is_rejected(tmp_path):
    alarm = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)
    segments = [
        segment(tmp_path / f"segment-{index:03d}.ts", alarm + timedelta(seconds=index * 2))
        for index in range(11)
    ]

    with pytest.raises(StreamBufferError) as caught:
        select_alarm_window(
            segments,
            alarm,
            pre_seconds=10,
            post_seconds=20,
            segment_seconds=2,
        )

    assert caught.value.code == "STREAM_BUFFER_COVERAGE_INSUFFICIENT"


def test_alarm_window_rejects_missing_segment_inside_session(tmp_path):
    alarm = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)
    start = alarm - timedelta(seconds=12)
    session_dir = tmp_path / "session-one"
    segments = [
        segment(session_dir / f"segment-{index:03d}.ts", start + timedelta(seconds=index * 2))
        for index in range(17)
        if index != 8
    ]

    with pytest.raises(StreamBufferError) as caught:
        select_alarm_window(segments, alarm, pre_seconds=10, post_seconds=20, segment_seconds=2)

    assert caught.value.code == "STREAM_BUFFER_SEGMENT_GAP"


def test_alarm_window_rejects_overlapping_sessions(tmp_path):
    alarm = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)
    start = alarm - timedelta(seconds=12)
    first = [
        segment(tmp_path / "session-one" / f"segment-{index:03d}.ts", start + timedelta(seconds=index * 2))
        for index in range(9)
    ]
    second_start = start + timedelta(seconds=14)
    second = [
        segment(tmp_path / "session-two" / f"segment-{index:03d}.ts", second_start + timedelta(seconds=index * 2))
        for index in range(10)
    ]

    with pytest.raises(StreamBufferError) as caught:
        select_alarm_window(first + second, alarm, pre_seconds=10, post_seconds=20, segment_seconds=2)

    assert caught.value.code == "STREAM_BUFFER_SESSION_OVERLAP"


def test_alarm_window_retries_until_last_segment_is_complete(tmp_path, monkeypatch):
    alarm = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)
    start = alarm - timedelta(seconds=12)
    complete = [
        segment(tmp_path / "session-one" / f"segment-{index:03d}.ts", start + timedelta(seconds=index * 2))
        for index in range(17)
    ]
    inventories = iter((complete[:-1], complete))

    def inventory(*_args, **_kwargs):
        return next(inventories)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(stream_buffer_service, "inventory_buffer_segments", inventory)
    monkeypatch.setattr(stream_buffer_service.asyncio, "sleep", no_sleep)

    selected = asyncio.run(select_alarm_window_with_retry(tmp_path, alarm, retry_seconds=1))

    assert selected.coverage_seconds == 30


def test_inventory_skips_active_segment_and_cleanup_removes_expired(tmp_path):
    root = resolve_stream_buffer_root(str(tmp_path / "buffer"))
    _, session_dir = create_buffer_session(root)
    now = datetime.now(UTC)
    old = session_dir / "segment-000000000.ts"
    ready = session_dir / "segment-000000001.ts"
    active = session_dir / "segment-000000002.ts"
    for path in (old, ready, active):
        path.write_bytes(b"segment")
    os.utime(old, (now.timestamp() - 90, now.timestamp() - 90))
    os.utime(ready, (now.timestamp() - 3, now.timestamp() - 3))
    os.utime(active, (now.timestamp(), now.timestamp()))

    inventory = inventory_buffer_segments(
        root, now=now, segment_seconds=2, settle_seconds=0.5
    )

    assert [item.path.name for item in inventory] == [old.name, ready.name]
    assert cleanup_stream_buffer(root, retention_seconds=60, now=now) == 1
    assert not old.exists()
    assert ready.exists()
    assert active.exists()


def test_cleanup_keeps_active_empty_session(tmp_path):
    root = resolve_stream_buffer_root(str(tmp_path / "buffer"))
    session_id, session_dir = create_buffer_session(root)

    cleanup_stream_buffer(root, retention_seconds=60, active_session_id=session_id)

    assert session_dir.is_dir()


def test_runtime_purge_removes_only_known_transient_artifacts(tmp_path):
    private_root = tmp_path / "private"
    root = resolve_stream_buffer_root(str(private_root / ".stream-buffer"))
    session_id, session_dir = create_buffer_session(root)
    segment(session_dir / "segment-000000001.ts", datetime.now(UTC))
    workspace = root / "work" / "task-test"
    workspace.mkdir(parents=True)
    (workspace / "manifest.txt").write_text("temporary", encoding="utf-8")
    (root / "status.json").write_text("{}", encoding="utf-8")
    (root / "keep-for-review.txt").write_text("preserve", encoding="utf-8")
    formal_asset = private_root / "asset-live-video-test.mp4"
    formal_asset.write_bytes(b"formal asset")
    (root / "worker.lock").write_text(
        json.dumps({"pid": 99999999}), encoding="utf-8"
    )

    report = purge_stream_buffer_runtime(root)
    second = purge_stream_buffer_runtime(root)

    assert report == {
        "removed_segments": 1,
        "removed_workspaces": 1,
        "status_removed": True,
        "lock_removed": True,
        "lock_active": False,
    }
    assert second["removed_segments"] == 0
    assert (root / "keep-for-review.txt").read_text(encoding="utf-8") == "preserve"
    assert formal_asset.read_bytes() == b"formal asset"
    assert not (root / "worker.lock").exists()
    assert not (root / "sessions" / session_id).exists()


def test_runtime_purge_rejects_active_worker_lock(tmp_path):
    root = resolve_stream_buffer_root(str(tmp_path / "buffer"))
    lock_path = root / "worker.lock"
    lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    _, session_dir = create_buffer_session(root)
    active_segment = session_dir / "segment-001.ts"
    active_segment.write_bytes(b"active")
    status_path = root / "status.json"
    status_path.write_text("{}", encoding="utf-8")

    with pytest.raises(StreamBufferError) as caught:
        purge_stream_buffer_runtime(root)

    assert caught.value.code == "STREAM_BUFFER_WORKER_STILL_ACTIVE"
    assert lock_path.is_file()
    assert active_segment.is_file()
    assert status_path.is_file()


def test_runtime_purge_reports_sanitized_failure(tmp_path, monkeypatch):
    root = resolve_stream_buffer_root(str(tmp_path / "buffer"))
    status_path = root / "status.json"
    status_path.write_text("{}", encoding="utf-8")
    original_unlink = Path.unlink

    def fail_status(path, *args, **kwargs):
        if path == status_path:
            raise OSError("private path must not escape")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_status)

    with pytest.raises(StreamBufferError) as caught:
        purge_stream_buffer_runtime(root)

    assert caught.value.code == "STREAM_BUFFER_PURGE_FAILED"
    assert "private path" not in caught.value.message


def test_buffer_assembly_rejects_non_h264_output(tmp_path, monkeypatch):
    root = resolve_stream_buffer_root(str(tmp_path / "buffer"))
    started_at = datetime.now(UTC) - timedelta(seconds=2)
    buffered = segment(root / "sessions" / "session-test" / "segment-001.ts", started_at)
    selection = stream_buffer_service.BufferSelection(
        alarm_time=started_at + timedelta(seconds=1),
        window_start=started_at,
        window_end=started_at + timedelta(seconds=2),
        coverage_seconds=2.0,
        segments=(buffered,),
    )

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"encoded video")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(stream_buffer_service.subprocess, "run", fake_run)
    monkeypatch.setattr(
        stream_buffer_service,
        "_probe_recorded_video",
        lambda _path: snapshot_asset_service.VideoProbe(
            duration_seconds=2.0,
            frame_rate=15.0,
            frame_count=30,
            codec_name="hevc",
        ),
    )

    with pytest.raises(StreamBufferError) as caught:
        stream_buffer_service._assemble_selection_sync(
            selection,
            root=root,
            output_path=tmp_path / "assembled.mp4",
            task_id="task-codec-test",
            max_bytes=1024 * 1024,
        )

    assert caught.value.code == "VIDEO_CODEC_UNSUPPORTED"
    assert not (tmp_path / "assembled.mp4").exists()


def test_status_file_and_command_do_not_serialize_credentials(tmp_path):
    root = resolve_stream_buffer_root(str(tmp_path / "buffer"))
    session_id, session_dir = create_buffer_session(root)
    command = build_buffer_ffmpeg_command(source(), session_dir, segment_seconds=2)

    assert "segment-%09d.ts" in command[-1]
    assert "-segment_time" in command
    assert "-rw_timeout" in command
    write_buffer_status(root, status="READY", session_id=session_id, segment_count=5)
    status_text = (root / "status.json").read_text(encoding="utf-8")
    status = json.loads(status_text)
    assert status["status"] == "READY"
    assert status["segment_count"] == 5
    assert status["contains_credentials"] is False
    assert "stream.example" not in status_text


def test_session_stall_detects_missing_or_stale_segments(tmp_path):
    now = datetime.now(UTC)
    session_dir = tmp_path / "session-test"
    session_dir.mkdir()
    started = now - timedelta(seconds=20)
    assert buffer_session_stalled(
        [], session_dir, session_started_at=started, now=now, stall_seconds=15
    )
    fresh = segment(session_dir / "segment-001.ts", now - timedelta(seconds=3))
    assert not buffer_session_stalled(
        [fresh], session_dir, session_started_at=started, now=now, stall_seconds=15
    )
    stale = segment(session_dir / "segment-002.ts", now - timedelta(seconds=30))
    assert buffer_session_stalled(
        [stale], session_dir, session_started_at=started, now=now, stall_seconds=15
    )


def test_health_report_is_redacted_and_requires_warm_coverage(tmp_path, monkeypatch):
    root = resolve_stream_buffer_root(str(tmp_path / "buffer"))
    session_id, session_dir = create_buffer_session(root)
    now = datetime.now(UTC)
    for index in range(6):
        path = session_dir / f"segment-{index:09d}.ts"
        path.write_bytes(b"segment")
        ended_at = now - timedelta(seconds=11 - index * 2)
        os.utime(path, (ended_at.timestamp(), ended_at.timestamp()))
    write_buffer_status(root, status="READY", session_id=session_id, segment_count=6)
    monkeypatch.setattr(stream_buffer_service, "YINGMU_STREAM_BUFFER_PRE_SECONDS", 10)
    monkeypatch.setattr(stream_buffer_service, "YINGMU_STREAM_BUFFER_SEGMENT_SECONDS", 2)

    health = stream_buffer_health(root)
    serialized = json.dumps(health)

    assert health["ready"] is True
    assert health["pre_alarm_coverage_seconds"] >= 8
    assert health["contains_credentials"] is False
    assert health["contains_media_path"] is False
    assert str(root) not in serialized


def test_health_stays_warming_with_only_one_completed_segment(tmp_path, monkeypatch):
    root = resolve_stream_buffer_root(str(tmp_path / "buffer"))
    session_id, session_dir = create_buffer_session(root)
    now = datetime.now(UTC)
    path = session_dir / "segment-000000000.ts"
    path.write_bytes(b"segment")
    ended_at = now - timedelta(seconds=2)
    os.utime(path, (ended_at.timestamp(), ended_at.timestamp()))
    write_buffer_status(root, status="READY", session_id=session_id, segment_count=1)
    monkeypatch.setattr(stream_buffer_service, "YINGMU_STREAM_BUFFER_PRE_SECONDS", 10)
    monkeypatch.setattr(stream_buffer_service, "YINGMU_STREAM_BUFFER_SEGMENT_SECONDS", 2)

    health = stream_buffer_health(root)

    assert health["ready"] is False
    assert health["pre_alarm_coverage_seconds"] == 2


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required")
def test_real_ffmpeg_segments_are_assembled_into_playable_mp4(tmp_path, monkeypatch):
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    root = resolve_stream_buffer_root(str(tmp_path / "buffer"))
    _, session_dir = create_buffer_session(root)
    pattern = session_dir / "segment-%03d.ts"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=10",
            "-t",
            "34",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-sc_threshold",
            "0",
            "-force_key_frames",
            "expr:gte(t,n_forced*2)",
            "-f",
            "segment",
            "-segment_format",
            "mpegts",
            "-segment_time",
            "2",
            "-reset_timestamps",
            "1",
            str(pattern),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    files = sorted(session_dir.glob("segment-*.ts"))
    assert len(files) == 17
    alarm = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)
    starts_at = alarm - timedelta(seconds=12)
    segments = [
        BufferedSegment(
            path=path,
            started_at=starts_at + timedelta(seconds=index * 2),
            ended_at=starts_at + timedelta(seconds=(index + 1) * 2),
            byte_size=path.stat().st_size,
        )
        for index, path in enumerate(files)
    ]
    selection = select_alarm_window(
        segments,
        alarm,
        pre_seconds=10,
        post_seconds=20,
        segment_seconds=2,
    )
    output = tmp_path / "assembled.mp4"
    monkeypatch.setattr(stream_buffer_service, "YINGMU_FFMPEG_BINARY", ffmpeg)

    digest, byte_size, duration = stream_buffer_service._assemble_selection_sync(
        selection,
        root=root,
        output_path=output,
        task_id="alarm-task-ffmpeg-integration",
        max_bytes=20 * 1024 * 1024,
    )

    assert output.is_file()
    assert len(digest) == 64
    assert byte_size == output.stat().st_size
    assert duration >= 29
    assert duration <= 31
    assert not list((root / "work").glob("task-*"))


def test_buffered_asset_is_private_live_and_idempotent(tmp_path, monkeypatch):
    private_root = tmp_path / "private"
    buffer_root = tmp_path / "buffer"
    database_path = tmp_path / "buffer-asset.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    normalized = datetime.now(UTC) - timedelta(seconds=30)
    alarm = normalized.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    start = normalized - timedelta(seconds=12)
    segment_root = buffer_root / "sessions" / "session-test"
    segments = [
        segment(segment_root / f"segment-{index:03d}.ts", start + timedelta(seconds=index * 2))
        for index in range(17)
    ]

    async def no_wait(*_args, **_kwargs):
        return None

    def inventory(*_args, **_kwargs):
        return segments

    def assemble(_selection, *, output_path, **_kwargs):
        content = b"private-buffered-mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        return hashlib.sha256(content).hexdigest(), len(content), 30.0

    monkeypatch.setattr(stream_buffer_service, "YINGMU_PRIVATE_MEDIA_ROOT", str(private_root))
    monkeypatch.setattr(stream_buffer_service, "YINGMU_STREAM_BUFFER_ROOT", str(buffer_root))
    monkeypatch.setattr(stream_buffer_service, "YINGMU_RETENTION_UNTIL", "2026-09-30T23:59:59+08:00")
    monkeypatch.setattr(stream_buffer_service, "YINGMU_STREAM_BUFFER_MAX_ALARM_DELAY_SECONDS", 86_400)
    monkeypatch.setattr(stream_buffer_service, "wait_for_alarm_window", no_wait)
    monkeypatch.setattr(stream_buffer_service, "inventory_buffer_segments", inventory)
    monkeypatch.setattr(stream_buffer_service, "_assemble_selection_sync", assemble)
    monkeypatch.setattr(snapshot_asset_service, "YINGMU_AUTHORIZATION_RECORD_ID", "consent-buffer-001")
    monkeypatch.setattr(snapshot_asset_service, "YINGMU_CAMERA_POSITION_ID", "living-room-buffer-v1")

    async def run():
        async with engine.begin() as connection:
            await connection.run_sync(AssetRow.__table__.create)
        async with session_factory() as db:
            created, idempotent = await stream_buffer_service.persist_buffered_video_asset(
                db,
                task_id="alarm-task-buffer-persist-001",
                alarm_time=alarm,
                device_ref="device-buffer-test",
            )
            await db.commit()
            repeated, repeated_idempotent = await stream_buffer_service.persist_buffered_video_asset(
                db,
                task_id="alarm-task-buffer-persist-001",
                alarm_time=alarm,
                device_ref="device-buffer-test",
            )
            row = (await db.execute(select(AssetRow))).scalar_one()
            return created, idempotent, repeated, repeated_idempotent, row

    created, idempotent, repeated, repeated_idempotent, row = asyncio.run(run())
    asyncio.run(engine.dispose())

    assert idempotent is False
    assert repeated_idempotent is True
    assert repeated == created
    assert created["source_mode"] == "LIVE_DEVICE"
    assert created["simulated"] is False
    assert created["verification_status"] == "VERIFIED_LIVE_BUFFER_CAPTURE"
    assert created["fallback_kind"] == "SERVER_MANAGED_RING_BUFFER"
    assert "storage_key" not in created
    assert (private_root / row.storage_key).is_file()


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, alarm):
        self.alarm = alarm
        self.commits = 0

    async def execute(self, _statement):
        return FakeResult(self.alarm)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _task):
        return None


def processing_task():
    return SimpleNamespace(
        task_id="alarm-task-buffer-001",
        alarm_msg_id="alarm-buffer-001",
        resident_id="resident-buffer-001",
        device_sn="device-buffer-001",
        attempt_count=1,
        max_attempts=3,
        capture_asset_id=None,
        status="PROCESSING",
        capture_completed_at=None,
        finished_at=None,
        available_at=None,
        error_stage=None,
        error_code=None,
        error_message=None,
    )


def test_alarm_worker_prefers_buffered_asset(monkeypatch):
    task = processing_task()
    session = FakeSession(SimpleNamespace(alarm_time=datetime.now()))
    direct_called = False

    async def buffered(_db, task_id, _alarm_time, device_ref):
        assert task_id == task.task_id
        assert device_ref.startswith("device-")
        return {"asset_id": "asset-buffered-001"}, False

    async def direct_source():
        nonlocal direct_called
        direct_called = True
        return source()

    monkeypatch.setattr(alarm_task_service, "YINGMU_CAPTURE_MEDIA_MODE", "VIDEO")
    monkeypatch.setattr(alarm_task_service, "YINGMU_STREAM_BUFFER_ENABLED", True)
    monkeypatch.setattr(alarm_task_service, "persist_buffered_video_asset", buffered)

    result = asyncio.run(
        alarm_task_service.process_claimed_task(
            session,
            task,
            capture_video_source=direct_source,
            store_buffered_asset=buffered,
        )
    )

    assert direct_called is False
    assert result.status == "CAPTURED"
    assert result.capture_asset_id == "asset-buffered-001"
    assert json.loads(result.algorithm_summary)["capture"] == {
        "mode": "RING_BUFFER",
        "buffer_error_code": None,
    }


def test_alarm_worker_falls_back_when_buffer_is_unavailable(monkeypatch):
    task = processing_task()
    session = FakeSession(SimpleNamespace(alarm_time=datetime.now()))
    source_called = False

    async def buffered(_db, _task_id, _alarm_time, _device_ref):
        raise StreamBufferError("STREAM_BUFFER_EMPTY", "safe failure")

    async def direct_source():
        nonlocal source_called
        source_called = True
        return source()

    async def store_direct(_db, _source, task_id):
        assert task_id == task.task_id
        return {"asset_id": "asset-direct-fallback-001"}, False

    monkeypatch.setattr(alarm_task_service, "YINGMU_CAPTURE_MEDIA_MODE", "VIDEO")
    monkeypatch.setattr(alarm_task_service, "YINGMU_STREAM_BUFFER_ENABLED", True)
    monkeypatch.setattr(alarm_task_service, "persist_buffered_video_asset", buffered)

    result = asyncio.run(
        alarm_task_service.process_claimed_task(
            session,
            task,
            capture_video_source=direct_source,
            store_video_asset=store_direct,
            store_buffered_asset=buffered,
        )
    )

    assert source_called is True
    assert result.status == "CAPTURED"
    assert result.capture_asset_id == "asset-direct-fallback-001"
    assert json.loads(result.algorithm_summary)["capture"] == {
        "mode": "DIRECT_FALLBACK",
        "buffer_error_code": "STREAM_BUFFER_EMPTY",
    }


def test_algorithm_result_preserves_capture_diagnostics():
    task = SimpleNamespace(
        algorithm_summary=json.dumps(
            {
                "capture": {
                    "mode": "DIRECT_FALLBACK",
                    "buffer_error_code": "STREAM_BUFFER_SEGMENT_GAP",
                }
            }
        )
    )

    serialized = algorithm_task_service._algorithm_summary(
        task,
        modules=[{"module": "GAIT", "status": "SUCCESS"}],
        observation_count=2,
        evidence_count=1,
    )
    summary = json.loads(serialized)

    assert summary["capture"]["mode"] == "DIRECT_FALLBACK"
    assert summary["capture"]["buffer_error_code"] == "STREAM_BUFFER_SEGMENT_GAP"
    assert summary["evidence_count"] == 1
