from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from backend.api.v1 import assets as assets_api
from backend.api.v1 import device as device_api
from backend.db.database import AsyncSessionLocal
from backend.db.models import Asset
from backend.main import app
from backend.service import snapshot_asset_service
from backend.service.serialization import cn_now_naive
from contracts.v1.platform import PlatformSnapshotResult


JPEG_BYTES = b"\xff\xd8\xff\xe0private-image"


async def _insert_private_image(asset_id: str, storage_key: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Asset).where(Asset.asset_id == asset_id))
        db.add(Asset(
            asset_id=asset_id,
            title="Private snapshot",
            source_mode="LIVE_DEVICE",
            simulated=False,
            stream_url=None,
            fallback_url=None,
            fallback_kind="SERVER_MANAGED_SNAPSHOT",
            available=True,
            verification_status="VERIFIED_LIVE_CAPTURE",
            captured_at=cn_now_naive(),
            notice="Authorized private image",
            device_ref="device-private-media-test",
            device_model="EZVIZ_C6C",
            camera_position_id="position-private-media-test",
            authorization_status="AUTHORIZED",
            authorization_record_id="authorization-private-media-test",
            retention_until=cn_now_naive() + timedelta(days=1),
            content_sha256=hashlib.sha256(JPEG_BYTES).hexdigest(),
            content_type="image/jpeg",
            byte_size=len(JPEG_BYTES),
            storage_key=storage_key,
        ))
        await db.commit()


async def _expire_asset(asset_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(update(Asset).where(Asset.asset_id == asset_id).values(
            retention_until=cn_now_naive() - timedelta(days=1),
        ))
        await db.commit()


def test_private_image_proxy_requires_token_and_checks_integrity(monkeypatch, tmp_path):
    media_root = tmp_path / "private-media"
    media_root.mkdir()
    storage_key = "asset-private-media-test.jpg"
    image_path = media_root / storage_key
    image_path.write_bytes(JPEG_BYTES)
    monkeypatch.setattr(snapshot_asset_service, "YINGMU_PRIVATE_MEDIA_ROOT", str(media_root))
    monkeypatch.setattr(assets_api, "YINGMU_MEDIA_ACCESS_TOKEN", "media-test-token")

    with TestClient(app) as client:
        asyncio.run(_insert_private_image("asset-private-media-test", storage_key))

        assert client.get("/api/v1/assets/asset-private-media-test/content").status_code == 401

        response = client.get(
            "/api/v1/assets/asset-private-media-test/content",
            headers={"Authorization": "Bearer media-test-token"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/jpeg")
        assert response.headers["cache-control"] == "private, no-store"
        assert response.content == JPEG_BYTES
        assert str(media_root) not in response.text

        image_path.write_bytes(b"tampered")
        assert client.get(
            "/api/v1/assets/asset-private-media-test/content",
            headers={"Authorization": "Bearer media-test-token"},
        ).status_code == 409

        asyncio.run(_expire_asset("asset-private-media-test"))
        assert client.get(
            "/api/v1/assets/asset-private-media-test/content",
            headers={"Authorization": "Bearer media-test-token"},
        ).status_code == 410


def test_persist_snapshot_endpoint_returns_asset_without_provider_url(monkeypatch):
    captured = PlatformSnapshotResult(
        schema_version="platform-snapshot/1.0",
        request_id="manual-snapshot-test-request",
        device_ref="device-manual-snapshot-test",
        channel_no=1,
        captured_at="2026-08-28T12:00:00+08:00",
        source_mode="LIVE_DEVICE",
        simulated=False,
        temporary_url="https://provider.example/private-snapshot.jpg",
        expires_at=None,
        provider_latency_ms=123,
    )
    saved = {
        "asset_id": "asset-manual-snapshot-test",
        "source_mode": "LIVE_DEVICE",
        "simulated": False,
        "content_type": "image/jpeg",
    }

    async def capture_snapshot():
        return captured

    async def persist(_db, snapshot, *, task_id):
        assert snapshot.temporary_url == captured.temporary_url
        assert task_id.startswith("manual-snapshot-")
        return saved, False

    monkeypatch.setattr(device_api.device_adapter, "capture_snapshot", capture_snapshot)
    monkeypatch.setattr(device_api, "persist_snapshot_asset", persist)

    with TestClient(app) as client:
        response = client.post("/api/v1/device/snapshot")

    assert response.status_code == 201
    assert response.json() == {"asset": saved, "idempotent": False}
    assert str(captured.temporary_url) not in response.text
