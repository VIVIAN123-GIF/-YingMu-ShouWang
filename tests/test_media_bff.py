from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.api.v1 import media as media_api
from backend.db.database import AsyncSessionLocal
from backend.db.models import Asset
from backend.service import snapshot_asset_service
from backend.service.serialization import cn_now_naive
from backend.main import app
from contracts.v1.platform import PlatformVideoSource


JPEG_BYTES = b"\xff\xd8\xff\xe0bff-image"
PROVIDER_URL = "https://provider.example/live.flv"


async def _insert_asset(root, asset_id="asset-bff-test"):
    storage_key = f"{asset_id}.jpg"
    (root / storage_key).write_bytes(JPEG_BYTES)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Asset).where(Asset.asset_id == asset_id))
        await db.execute(delete(Asset).where(Asset.storage_key == storage_key))
        db.add(Asset(
            asset_id=asset_id, title="BFF test", source_mode="LIVE_DEVICE", simulated=False,
            stream_url=None, fallback_url=None, fallback_kind="SERVER_MANAGED_SNAPSHOT",
            available=True, verification_status="VERIFIED_LIVE_CAPTURE", captured_at=cn_now_naive(),
            notice="test", device_ref="device-test", device_model="EZVIZ_C6C",
            camera_position_id="position-test", authorization_status="AUTHORIZED",
            authorization_record_id="authorization-test", retention_until=cn_now_naive() + timedelta(days=1),
            content_sha256=hashlib.sha256(JPEG_BYTES).hexdigest(), content_type="image/jpeg",
            byte_size=len(JPEG_BYTES), storage_key=storage_key,
        ))
        await db.commit()


def test_bff_session_cookie_protects_private_media(monkeypatch, tmp_path):
    monkeypatch.setattr(media_api, "YINGMU_BFF_USERNAME", "judge")
    monkeypatch.setattr(media_api, "YINGMU_BFF_PASSWORD_SHA256", hashlib.sha256(b"secret").hexdigest())
    monkeypatch.setattr(media_api, "YINGMU_BFF_SESSION_SECRET", "test-session-secret")
    monkeypatch.setattr(media_api, "YINGMU_BFF_SESSION_TTL_SECONDS", 900)
    monkeypatch.setattr(media_api, "YINGMU_BFF_COOKIE_SECURE", False)
    monkeypatch.setattr(media_api, "YINGMU_MEDIA_ACCESS_TOKEN", "server-only-token")
    monkeypatch.setattr(snapshot_asset_service, "YINGMU_PRIVATE_MEDIA_ROOT", str(tmp_path))

    with TestClient(app) as client:
        asyncio.run(_insert_asset(tmp_path))
        assert client.get("/media/assets/asset-bff-test").status_code == 401
        assert client.post("/api/v1/media/session", json={"username": "judge", "password": "wrong"}).status_code == 401
        login = client.post("/api/v1/media/session", json={"username": "judge", "password": "secret"})
        assert login.status_code == 200
        assert "yingmu_media_session" in client.cookies
        image = client.get("/media/assets/asset-bff-test")
        assert image.status_code == 200
        assert image.headers["content-type"].startswith("image/jpeg")
        assert image.content == JPEG_BYTES
        assert client.delete("/api/v1/media/session").status_code == 204
        assert client.get("/media/assets/asset-bff-test").status_code == 401


def _configure_live(monkeypatch):
    monkeypatch.setattr(media_api, "YINGMU_BFF_USERNAME", "judge")
    monkeypatch.setattr(media_api, "YINGMU_BFF_PASSWORD_SHA256", hashlib.sha256(b"secret").hexdigest())
    monkeypatch.setattr(media_api, "YINGMU_BFF_SESSION_SECRET", "test-session-secret")
    monkeypatch.setattr(media_api, "YINGMU_BFF_COOKIE_SECURE", False)
    monkeypatch.setattr(media_api, "YINGMU_LIVE_VIEW_ENABLED", True)
    monkeypatch.setattr(media_api, "EZVIZ_LIVE_PROTOCOL", 4)
    monkeypatch.setattr(media_api, "YINGMU_AUTHORIZATION_RECORD_ID", "authorization-test")
    monkeypatch.setattr(media_api, "YINGMU_CAMERA_POSITION_ID", "position-test")
    monkeypatch.setattr(media_api, "YINGMU_RETENTION_UNTIL", "2099-01-01T00:00:00+00:00")
    monkeypatch.setattr(media_api, "YINGMU_LIVE_STREAM_TIMEOUT_SECONDS", 1.0)

    async def source():
        return PlatformVideoSource(
            schema_version="platform-video/1.0", request_id="live-test-request",
            device_ref="device-live-test", channel_no=1, captured_at=datetime.now(timezone.utc),
            source_mode="LIVE_DEVICE", simulated=False,
            temporary_url=PROVIDER_URL,
            expires_at=None, provider_latency_ms=1,
        )

    monkeypatch.setattr(media_api.device_adapter, "capture_video_source", source)


def _mock_live_upstream(monkeypatch, status_code=200, content=b"FLV\x01private-stream"):
    async_client = httpx.AsyncClient
    mock_transport = httpx.MockTransport

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == PROVIDER_URL
        return httpx.Response(status_code, content=content)

    monkeypatch.setattr(
        media_api.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=mock_transport(handler), **kwargs),
    )


def _login(client: TestClient):
    response = client.post("/api/v1/media/session", json={"username": "judge", "password": "secret"})
    assert response.status_code == 200


def test_live_bff_requires_session_and_proxies_flv_without_provider_url(monkeypatch):
    _configure_live(monkeypatch)
    _mock_live_upstream(monkeypatch)
    with TestClient(app) as client:
        assert client.get("/media/live").status_code == 401
        _login(client)
        streamed = client.get("/media/live")
        assert streamed.status_code == 200
        assert streamed.headers["content-type"].startswith("video/x-flv")
        assert streamed.headers["cache-control"] == "no-store, no-cache"
        assert streamed.content.startswith(b"FLV")
        assert "provider.example" not in streamed.text


def test_live_bff_maps_disabled_and_upstream_errors_to_sanitized_503(monkeypatch):
    _configure_live(monkeypatch)
    _mock_live_upstream(monkeypatch, status_code=403, content=b"provider rejected URL")
    with TestClient(app) as client:
        _login(client)
        monkeypatch.setattr(media_api, "YINGMU_LIVE_VIEW_ENABLED", False)
        disabled = client.get("/media/live")
        assert disabled.status_code == 503
        assert disabled.json()["error"]["code"] == "LIVE_VIEW_DISABLED"

        monkeypatch.setattr(media_api, "YINGMU_LIVE_VIEW_ENABLED", True)
        failed = client.get("/media/live")
        assert failed.status_code == 503
        assert failed.json()["error"]["code"] == "LIVE_SOURCE_UNAVAILABLE"
        assert "provider.example" not in failed.text
        assert "provider rejected" not in failed.text


def test_live_bff_rejects_missing_or_expired_authorization(monkeypatch):
    _configure_live(monkeypatch)
    with TestClient(app) as client:
        _login(client)
        monkeypatch.setattr(media_api, "YINGMU_CAMERA_POSITION_ID", "")
        forbidden = client.get("/media/live")
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "LIVE_VIEW_FORBIDDEN"

        monkeypatch.setattr(media_api, "YINGMU_CAMERA_POSITION_ID", "position-test")
        monkeypatch.setattr(media_api, "YINGMU_RETENTION_UNTIL", "2020-01-01T00:00:00+00:00")
        expired = client.get("/media/live")
        assert expired.status_code == 410
        assert expired.json()["error"]["code"] == "LIVE_VIEW_AUTHORIZATION_EXPIRED"
