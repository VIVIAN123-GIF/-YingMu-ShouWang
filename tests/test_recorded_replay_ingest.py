from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.database import Base
from backend.db.models import AlarmProcessingTask, Asset as AssetRow, RiskAlarm
from backend.schemas.asset import Asset, AssetCreate
from backend.service.asset_service import asset_dict
from backend.service.errors import ServiceError
from backend.service.recorded_replay_ingest_service import (
    REPOSITORY_ROOT,
    RecordedReplayIngestError,
    enqueue_recorded_replay,
)


CAPTURED_AT = datetime(2026, 8, 17, 12, 10, tzinfo=timezone.utc)
RETENTION_UNTIL = datetime.now(timezone.utc) + timedelta(days=30)


def _mp4(path: Path) -> None:
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128)


def _asset_payload(content_type: str) -> dict:
    return {
        "asset_id": "asset-video-contract-001",
        "title": "authorized replay",
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "stream_url": None,
        "fallback_url": None,
        "fallback_kind": "private_storage",
        "available": True,
        "verification_status": "VERIFIED_REPLAY",
        "captured_at": CAPTURED_AT,
        "notice": "private test replay",
        "device_ref": "device-ref-test",
        "device_model": "EZVIZ_C6C",
        "camera_position_id": "living-room-c6c-v1",
        "authorization_status": "AUTHORIZED",
        "authorization_record_id": "authorization-test",
        "retention_until": RETENTION_UNTIL,
        "content_sha256": "a" * 64,
        "content_type": content_type,
        "byte_size": 140,
    }


async def _with_database(path: Path, operation):
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as db:
            return await operation(db)
    finally:
        await engine.dispose()


def test_video_mp4_asset_contract_is_serializable():
    payload = AssetCreate.model_validate(_asset_payload("video/mp4"))
    assert payload.content_type == "video/mp4"
    Asset.model_validate(payload.model_dump())
    with pytest.raises(ValidationError):
        AssetCreate.model_validate(_asset_payload("video/webm"))


def test_recorded_replay_ingest_is_private_traceable_and_idempotent(tmp_path: Path):
    media = tmp_path / "authorized.mp4"
    private_root = tmp_path / "private"
    _mp4(media)

    async def operation(db):
        kwargs = {
            "input_path": media,
            "resident_id": "resident-replay-001",
            "captured_at": CAPTURED_AT,
            "private_media_root": str(private_root),
            "camera_position_id": "living-room-c6c-v1",
            "authorization_record_id": "authorization-private-test",
            "retention_until": RETENTION_UNTIL,
        }
        first = await enqueue_recorded_replay(db, **kwargs)
        second = await enqueue_recorded_replay(db, **kwargs)
        asset = (await db.execute(select(AssetRow).where(
            AssetRow.asset_id == first["asset_id"]
        ))).scalar_one()
        alarm = (await db.execute(select(RiskAlarm))).scalar_one()
        task = (await db.execute(select(AlarmProcessingTask))).scalar_one()
        counts = {
            "asset": (await db.execute(select(func.count(AssetRow.asset_id)))).scalar_one(),
            "alarm": (await db.execute(select(func.count(RiskAlarm.id)))).scalar_one(),
            "task": (await db.execute(select(func.count(AlarmProcessingTask.id)))).scalar_one(),
        }
        Asset.model_validate(asset_dict(asset))
        return first, second, asset, alarm, task, counts

    first, second, asset, alarm, task, counts = asyncio.run(
        _with_database(tmp_path / "replay.db", operation)
    )
    assert first["result"] == "CREATED"
    assert second["result"] == "EXISTING"
    assert first["task_id"] == second["task_id"]
    assert counts == {"asset": 1, "alarm": 1, "task": 1}
    assert asset.content_type == "video/mp4"
    assert asset.source_mode == "RECORDED_REPLAY"
    assert asset.simulated is True
    assert asset.stream_url is None and asset.fallback_url is None
    assert Path(asset.storage_key).name == asset.storage_key
    assert (private_root / asset.storage_key).is_file()
    assert task.status == "CAPTURED"
    assert task.capture_asset_id == asset.asset_id
    assert str(media) not in alarm.raw_callback_json
    assert "authorization-private-test" not in alarm.raw_callback_json
    assert str(media) not in str(first)
    assert str(private_root) not in str(first)


@pytest.mark.parametrize(
    ("filename", "content", "error_code"),
    [
        ("authorized.avi", b"\x00\x00\x00\x18ftypmp42", "REPLAY_FORMAT_INVALID"),
        ("authorized.mp4", b"not-an-mp4", "REPLAY_SIGNATURE_INVALID"),
    ],
)
def test_recorded_replay_rejects_invalid_media(
    tmp_path: Path,
    filename: str,
    content: bytes,
    error_code: str,
):
    media = tmp_path / filename
    media.write_bytes(content)

    async def operation(db):
        with pytest.raises(RecordedReplayIngestError) as caught:
            await enqueue_recorded_replay(
                db,
                input_path=media,
                resident_id="resident-replay-001",
                captured_at=CAPTURED_AT,
                private_media_root=str(tmp_path / "private"),
                camera_position_id="living-room-c6c-v1",
                authorization_record_id="authorization-test",
                retention_until=RETENTION_UNTIL,
            )
        return caught.value.code

    assert asyncio.run(_with_database(tmp_path / "invalid.db", operation)) == error_code


def test_recorded_replay_rejects_expired_authorization(tmp_path: Path):
    media = tmp_path / "authorized.mp4"
    _mp4(media)

    async def operation(db):
        with pytest.raises(RecordedReplayIngestError) as caught:
            await enqueue_recorded_replay(
                db,
                input_path=media,
                resident_id="resident-replay-001",
                captured_at=CAPTURED_AT,
                private_media_root=str(tmp_path / "private"),
                camera_position_id="living-room-c6c-v1",
                authorization_record_id="authorization-test",
                retention_until=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
        return caught.value.code

    result = asyncio.run(_with_database(tmp_path / "expired.db", operation))
    assert result == "REPLAY_AUTHORIZATION_EXPIRED"


def test_recorded_replay_rejects_private_object_content_conflict(tmp_path: Path):
    media = tmp_path / "authorized.mp4"
    private_root = tmp_path / "private"
    _mp4(media)

    async def operation(db):
        kwargs = {
            "input_path": media,
            "resident_id": "resident-replay-001",
            "captured_at": CAPTURED_AT,
            "private_media_root": str(private_root),
            "camera_position_id": "living-room-c6c-v1",
            "authorization_record_id": "authorization-test",
            "retention_until": RETENTION_UNTIL,
        }
        first = await enqueue_recorded_replay(db, **kwargs)
        asset = (await db.execute(select(AssetRow).where(
            AssetRow.asset_id == first["asset_id"]
        ))).scalar_one()
        (private_root / asset.storage_key).write_bytes(b"tampered")
        with pytest.raises(RecordedReplayIngestError) as caught:
            await enqueue_recorded_replay(db, **kwargs)
        return caught.value.code

    result = asyncio.run(_with_database(tmp_path / "content-conflict.db", operation))
    assert result == "PRIVATE_MEDIA_CONFLICT"


def test_recorded_replay_rejects_asset_id_content_conflict(tmp_path: Path):
    media = tmp_path / "authorized.mp4"
    private_root = tmp_path / "private"
    _mp4(media)

    async def operation(db):
        kwargs = {
            "input_path": media,
            "resident_id": "resident-replay-001",
            "captured_at": CAPTURED_AT,
            "private_media_root": str(private_root),
            "camera_position_id": "living-room-c6c-v1",
            "authorization_record_id": "authorization-test",
            "retention_until": RETENTION_UNTIL,
        }
        first = await enqueue_recorded_replay(db, **kwargs)
        asset = (await db.execute(select(AssetRow).where(
            AssetRow.asset_id == first["asset_id"]
        ))).scalar_one()
        asset.title = "conflicting title"
        await db.commit()
        with pytest.raises(ServiceError) as caught:
            await enqueue_recorded_replay(db, **kwargs)
        return caught.value.code

    result = asyncio.run(_with_database(tmp_path / "asset-conflict.db", operation))
    assert result == "ASSET_ID_CONFLICT"


def test_recorded_replay_rejects_private_root_inside_repository(tmp_path: Path):
    media = tmp_path / "authorized.mp4"
    _mp4(media)

    async def operation(db):
        with pytest.raises(RecordedReplayIngestError) as caught:
            await enqueue_recorded_replay(
                db,
                input_path=media,
                resident_id="resident-replay-001",
                captured_at=CAPTURED_AT,
                private_media_root=str(REPOSITORY_ROOT / "private-media-test"),
                camera_position_id="living-room-c6c-v1",
                authorization_record_id="authorization-test",
                retention_until=RETENTION_UNTIL,
            )
        return caught.value.code

    result = asyncio.run(_with_database(tmp_path / "unsafe.db", operation))
    assert result == "PRIVATE_MEDIA_ROOT_UNSAFE"
    assert not (REPOSITORY_ROOT / "private-media-test").exists()


@pytest.mark.parametrize(
    ("value", "expected_ok"),
    [("75", True), ("0", False), ("120.1", False)],
)
def test_algorithm_timeout_configuration_bounds(tmp_path: Path, value: str, expected_ok: bool):
    environment = os.environ.copy()
    environment.update({
        "YINGMU_ENV": "mock",
        "YINGMU_ALGORITHM_TIMEOUT_SECONDS": value,
        "PYTHONPATH": str(REPOSITORY_ROOT),
    })
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from backend.config import YINGMU_ALGORITHM_TIMEOUT_SECONDS as value; print(value)",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is expected_ok
    if expected_ok:
        assert result.stdout.strip() == "75.0"
    else:
        assert "YINGMU_ALGORITHM_TIMEOUT_SECONDS must be between 0.1 and 120" in result.stderr


def test_algorithm_timeout_configuration_defaults_to_90(tmp_path: Path):
    environment = os.environ.copy()
    environment.pop("YINGMU_ALGORITHM_TIMEOUT_SECONDS", None)
    environment.update({
        "YINGMU_ENV": "mock",
        "PYTHONPATH": str(REPOSITORY_ROOT),
    })
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from backend.config import YINGMU_ALGORITHM_TIMEOUT_SECONDS as value; print(value)",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "90.0"
