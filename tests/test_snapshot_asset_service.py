from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.models import Asset as AssetRow
from backend.service.alarm_task_service import process_claimed_task
from backend.service.snapshot_asset_service import (
    SnapshotAssetError,
    VideoProbe,
    download_snapshot,
    persist_snapshot_asset,
)
from backend.service import snapshot_asset_service as snapshot_service
from contracts.v1.platform import PlatformSnapshotResult


PRIVATE_URL = "https://snapshot.example/private/capture.jpg"
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"d2-snapshot"


def live_snapshot() -> PlatformSnapshotResult:
    return PlatformSnapshotResult(
        schema_version="platform-snapshot/1.0",
        request_id="ezviz-capture-d2-test-001",
        device_ref="device-d2-test-001",
        channel_no=1,
        captured_at="2026-08-15T13:00:00+08:00",
        source_mode="LIVE_DEVICE",
        simulated=False,
        temporary_url=PRIVATE_URL,
        expires_at=None,
        provider_latency_ms=123,
    )


def async_client(status: int = 200, content_type: str = "image/jpeg",
                 body: bytes = JPEG_BYTES) -> httpx.AsyncClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == PRIVATE_URL
        return httpx.Response(status, headers={"content-type": content_type}, content=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_valid_snapshot_is_hashed_and_atomically_stored(tmp_path):
    async def run():
        async with async_client() as client:
            return await download_snapshot(
                live_snapshot(), asset_id="asset-live-test",
                media_root=str(tmp_path), client=client,
            )

    stored = asyncio.run(run())

    assert stored.content_type == "image/jpeg"
    assert stored.byte_size == len(JPEG_BYTES)
    assert len(stored.content_sha256) == 64
    assert (tmp_path / stored.storage_key).read_bytes() == JPEG_BYTES
    assert not list(tmp_path.glob("*.part"))
    assert PRIVATE_URL not in repr(stored)


@pytest.mark.parametrize(
    ("content_type", "body", "max_bytes", "error_code", "retryable"),
    [
        ("text/html", b"not an image", 1024, "SNAPSHOT_CONTENT_TYPE_INVALID", True),
        ("image/jpeg", b"", 1024, "SNAPSHOT_EMPTY", True),
        ("image/jpeg", b"not-a-jpeg", 1024, "SNAPSHOT_SIGNATURE_INVALID", True),
        ("image/jpeg", JPEG_BYTES, 4, "SNAPSHOT_TOO_LARGE", False),
    ],
)
def test_invalid_snapshot_is_rejected_and_partial_file_removed(
    tmp_path, content_type, body, max_bytes, error_code, retryable
):
    async def run():
        async with async_client(content_type=content_type, body=body) as client:
            return await download_snapshot(
                live_snapshot(), asset_id="asset-invalid",
                media_root=str(tmp_path), max_bytes=max_bytes, client=client,
            )

    with pytest.raises(SnapshotAssetError) as caught:
        asyncio.run(run())

    assert caught.value.code == error_code
    assert caught.value.retryable is retryable
    assert PRIVATE_URL not in str(caught.value)
    assert not list(tmp_path.iterdir())


def test_repository_path_is_rejected_before_download():
    unsafe_root = snapshot_service.REPOSITORY_ROOT / "private-media"

    async def run():
        async with async_client() as client:
            return await download_snapshot(
                live_snapshot(), asset_id="asset-unsafe",
                media_root=str(unsafe_root), client=client,
            )

    with pytest.raises(SnapshotAssetError) as caught:
        asyncio.run(run())
    assert caught.value.code == "PRIVATE_MEDIA_ROOT_UNSAFE"
    assert not unsafe_root.exists()


@pytest.mark.parametrize(
    ("authorization_id", "camera_position", "retention", "error_code"),
    [
        ("", "living-room-c6c-v1", "2026-09-30T23:59:59+08:00",
         "SNAPSHOT_AUTHORIZATION_REQUIRED"),
        ("consent-d2-001", "", "2026-09-30T23:59:59+08:00",
         "CAMERA_POSITION_REQUIRED"),
        ("consent-d2-001", "living-room-c6c-v1", "2026-08-15T12:59:59+08:00",
         "SNAPSHOT_AUTHORIZATION_EXPIRED"),
    ],
)
def test_authorization_metadata_is_required_before_persistence(
    monkeypatch, authorization_id, camera_position, retention, error_code
):
    monkeypatch.setattr(snapshot_service, "YINGMU_AUTHORIZATION_RECORD_ID", authorization_id)
    monkeypatch.setattr(snapshot_service, "YINGMU_CAMERA_POSITION_ID", camera_position)

    with pytest.raises(SnapshotAssetError) as caught:
        snapshot_service._authorized_retention(
            retention, live_snapshot().captured_at
        )

    assert caught.value.code == error_code
    assert caught.value.retryable is False


def test_persisted_asset_exposes_hash_but_not_storage_key(monkeypatch, tmp_path):
    database_path = tmp_path / "asset-test.db"
    media_root = tmp_path / "private"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(snapshot_service, "YINGMU_PRIVATE_MEDIA_ROOT", str(media_root))
    monkeypatch.setattr(snapshot_service, "YINGMU_CAMERA_POSITION_ID", "living-room-c6c-v1")
    monkeypatch.setattr(snapshot_service, "YINGMU_AUTHORIZATION_RECORD_ID", "consent-d2-001")
    monkeypatch.setattr(snapshot_service, "YINGMU_RETENTION_UNTIL", "2026-09-30T23:59:59+08:00")

    async def run():
        async with engine.begin() as connection:
            await connection.run_sync(AssetRow.__table__.create)
        async with session_factory() as db, async_client() as client:
            public, idempotent = await persist_snapshot_asset(
                db, live_snapshot(), task_id="alarm-task-d2-001", client=client
            )
            await db.commit()
            repeated, repeated_idempotent = await persist_snapshot_asset(
                db, live_snapshot(), task_id="alarm-task-d2-001", client=client
            )
            row = (await db.execute(select(AssetRow))).scalar_one()
            return public, idempotent, repeated, repeated_idempotent, row.storage_key

    public, idempotent, repeated, repeated_idempotent, storage_key = asyncio.run(run())
    asyncio.run(engine.dispose())

    assert idempotent is False
    assert repeated_idempotent is True
    assert repeated == public
    assert public["verification_status"] == "VERIFIED_LIVE_CAPTURE"
    assert public["content_sha256"]
    assert public["byte_size"] == len(JPEG_BYTES)
    assert "storage_key" not in public
    assert storage_key
    assert (media_root / storage_key).is_file()


class FakeSession:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def refresh(self, _):
        return None


def processing_task():
    return SimpleNamespace(
        task_id="alarm-task-d2-worker-001",
        attempt_count=1,
        max_attempts=3,
        capture_asset_id=None,
        status="PROCESSING",
        finished_at=None,
        available_at=None,
        error_code=None,
        error_message=None,
    )


def test_worker_waits_for_persisted_asset_before_algorithm_handoff():
    task = processing_task()
    session = FakeSession()

    async def capture():
        return live_snapshot()

    async def store(db, snapshot, task_id):
        assert db is session
        assert snapshot.temporary_url is not None
        assert task_id == task.task_id
        return {"asset_id": "asset-live-worker-001"}

    result = asyncio.run(process_claimed_task(
        session, task, capture_snapshot=capture, store_snapshot_asset=store
    ))

    assert result.status == "CAPTURED"
    assert result.capture_asset_id == "asset-live-worker-001"
    assert result.error_code is None
    assert session.commits == 1


@pytest.mark.parametrize(
    ("retryable", "expected_status"), [(True, "RETRY"), (False, "FAILED")]
)
def test_worker_classifies_snapshot_asset_failures(retryable, expected_status):
    task = processing_task()
    session = FakeSession()

    async def capture():
        return live_snapshot()

    async def fail_store(_db, _snapshot, _task_id):
        raise SnapshotAssetError(
            "SNAPSHOT_TEST_FAILURE", "Safe snapshot failure", retryable=retryable
        )

    result = asyncio.run(process_claimed_task(
        session, task, capture_snapshot=capture, store_snapshot_asset=fail_store
    ))

    assert result.status == expected_status
    assert result.capture_asset_id is None
    assert result.error_code == "SNAPSHOT_TEST_FAILURE"
    assert PRIVATE_URL not in result.error_message


@pytest.mark.parametrize(
    ("probe", "error_code"),
    [
        (VideoProbe(duration_seconds=4.0, frame_rate=2.0, frame_count=8),
         "VIDEO_DURATION_INSUFFICIENT"),
        (VideoProbe(duration_seconds=8.0, frame_rate=2.0, frame_count=16),
         "VIDEO_FRAME_RATE_INSUFFICIENT"),
        (VideoProbe(duration_seconds=8.0, frame_rate=15.0, frame_count=12),
         "VIDEO_FRAME_COUNT_INSUFFICIENT"),
    ],
)
def test_provider_placeholder_or_incomplete_video_is_rejected(probe, error_code):
    with pytest.raises(SnapshotAssetError) as caught:
        snapshot_service._validate_recorded_video(probe, expected_seconds=8)

    assert caught.value.code == error_code
    assert caught.value.retryable is True


def test_video_with_sufficient_duration_and_frames_is_accepted():
    snapshot_service._validate_recorded_video(
        VideoProbe(duration_seconds=8.0, frame_rate=15.0, frame_count=120),
        expected_seconds=8,
    )
