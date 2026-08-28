"""Browser-facing media session endpoints.

The long-lived media access token stays in the API process. Browsers receive
only a short-lived, HttpOnly signed session cookie and image bytes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Cookie, Depends, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import (
    YINGMU_BFF_COOKIE_SECURE,
    YINGMU_BFF_PASSWORD_SHA256,
    YINGMU_BFF_SESSION_SECRET,
    YINGMU_BFF_SESSION_TTL_SECONDS,
    YINGMU_BFF_USERNAME,
    EZVIZ_LIVE_PROTOCOL,
    YINGMU_AUTHORIZATION_RECORD_ID,
    YINGMU_CAMERA_POSITION_ID,
    YINGMU_LIVE_STREAM_TIMEOUT_SECONDS,
    YINGMU_LIVE_VIEW_ENABLED,
    YINGMU_MEDIA_ACCESS_TOKEN,
    YINGMU_RETENTION_UNTIL,
)
from backend.db.database import get_db
from backend.service.asset_service import get_private_image_content
from backend.service.device_adapter import device_adapter
from backend.service.errors import ServiceError

SESSION_COOKIE = "yingmu_media_session"
session_router = APIRouter(prefix="/media", tags=["media-session"])
proxy_router = APIRouter(prefix="/media", tags=["media-proxy"])


class MediaSessionLogin(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


def _session_key() -> bytes:
    if not YINGMU_BFF_SESSION_SECRET:
        raise ServiceError(503, "MEDIA_SESSION_NOT_CONFIGURED", "media session is not configured")
    return YINGMU_BFF_SESSION_SECRET.encode("utf-8")


def _sign(payload: bytes) -> str:
    signature = hmac.new(_session_key(), payload, hashlib.sha256).digest()
    return urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def _issue_session(username: str) -> str:
    expires_at = int(time.time()) + YINGMU_BFF_SESSION_TTL_SECONDS
    payload = f"{username}|{expires_at}|{secrets.token_urlsafe(18)}".encode("utf-8")
    encoded = urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{encoded}.{_sign(payload)}"


def _decode_session(cookie: str | None) -> str:
    if not cookie or "." not in cookie:
        raise ServiceError(401, "MEDIA_SESSION_REQUIRED", "an authenticated media session is required")
    encoded, supplied_signature = cookie.split(".", 1)
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = urlsafe_b64decode(padded.encode("ascii"))
        username, expires_at, _nonce = payload.decode("utf-8").split("|", 2)
        expires = int(expires_at)
    except (ValueError, UnicodeError, TypeError):
        raise ServiceError(401, "MEDIA_SESSION_INVALID", "the media session is invalid") from None
    if not hmac.compare_digest(_sign(payload), supplied_signature):
        raise ServiceError(401, "MEDIA_SESSION_INVALID", "the media session is invalid")
    if expires <= int(time.time()):
        raise ServiceError(401, "MEDIA_SESSION_EXPIRED", "the media session has expired")
    if not hmac.compare_digest(username, YINGMU_BFF_USERNAME):
        raise ServiceError(401, "MEDIA_SESSION_INVALID", "the media session is invalid")
    return username


def require_media_session(
    yingmu_media_session: str | None = Cookie(default=None),
) -> str:
    return _decode_session(yingmu_media_session)


def _require_live_authorization() -> None:
    if not YINGMU_AUTHORIZATION_RECORD_ID or not YINGMU_CAMERA_POSITION_ID:
        raise ServiceError(403, "LIVE_VIEW_FORBIDDEN", "live view is not authorized")
    try:
        retention = datetime.fromisoformat(YINGMU_RETENTION_UNTIL.replace("Z", "+00:00"))
    except ValueError:
        raise ServiceError(403, "LIVE_VIEW_FORBIDDEN", "live view is not authorized") from None
    if retention.tzinfo is None or retention <= datetime.now(timezone.utc):
        raise ServiceError(410, "LIVE_VIEW_AUTHORIZATION_EXPIRED", "live view authorization has expired")


@session_router.post("/session")
async def create_media_session(payload: MediaSessionLogin, response: Response):
    if not YINGMU_BFF_USERNAME or not YINGMU_BFF_PASSWORD_SHA256:
        raise ServiceError(503, "MEDIA_SESSION_NOT_CONFIGURED", "media session is not configured")
    supplied_hash = hashlib.sha256(payload.password.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(payload.username, YINGMU_BFF_USERNAME) or not hmac.compare_digest(
        supplied_hash, YINGMU_BFF_PASSWORD_SHA256
    ):
        raise ServiceError(401, "MEDIA_SESSION_FORBIDDEN", "账号或密码不正确")
    response.set_cookie(
        SESSION_COOKIE,
        _issue_session(payload.username),
        max_age=YINGMU_BFF_SESSION_TTL_SECONDS,
        httponly=True,
        secure=YINGMU_BFF_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return {"authenticated": True, "expires_in": YINGMU_BFF_SESSION_TTL_SECONDS}


@session_router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media_session(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")


@proxy_router.get("/assets/{asset_id}", response_class=FileResponse)
async def read_media_proxy(
    asset_id: str,
    _username: str = Depends(require_media_session),
    db: AsyncSession = Depends(get_db),
):
    if not YINGMU_MEDIA_ACCESS_TOKEN:
        raise ServiceError(503, "MEDIA_ACCESS_TOKEN_NOT_CONFIGURED", "media access is not configured")
    path, content_type = await get_private_image_content(db, asset_id)
    return FileResponse(
        path,
        media_type=content_type,
        filename=f"{asset_id}{path.suffix}",
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@proxy_router.get("/live")
async def read_live_proxy(
    _username: str = Depends(require_media_session),
):
    if not YINGMU_LIVE_VIEW_ENABLED:
        raise ServiceError(503, "LIVE_VIEW_DISABLED", "live view is not enabled")
    if EZVIZ_LIVE_PROTOCOL != 4:
        raise ServiceError(503, "LIVE_PROTOCOL_UNSUPPORTED", "the live BFF requires HTTP-FLV protocol")
    _require_live_authorization()
    try:
        source = await device_adapter.capture_video_source()
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError(503, "LIVE_SOURCE_UNAVAILABLE", "live source is temporarily unavailable") from exc
    if not source.temporary_url:
        raise ServiceError(503, "LIVE_SOURCE_UNAVAILABLE", "live source is temporarily unavailable")

    timeout_seconds = YINGMU_LIVE_STREAM_TIMEOUT_SECONDS
    timeout = httpx.Timeout(timeout_seconds, connect=timeout_seconds, read=timeout_seconds)
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    try:
        request = client.build_request(
            "GET", str(source.temporary_url), headers={"Accept": "video/x-flv"}
        )
        upstream = await client.send(request, stream=True)
    except (httpx.HTTPError, OSError, TimeoutError) as exc:
        await client.aclose()
        raise ServiceError(503, "LIVE_SOURCE_UNAVAILABLE", "live source is temporarily unavailable") from exc

    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise ServiceError(503, "LIVE_SOURCE_UNAVAILABLE", "live source is temporarily unavailable")

    async def stream_bytes():
        try:
            async for chunk in upstream.aiter_bytes(64 * 1024):
                yield chunk
        except (httpx.HTTPError, OSError, TimeoutError):
            return
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_bytes(),
        media_type="video/x-flv",
        headers={"Cache-Control": "no-store, no-cache", "X-Content-Type-Options": "nosniff"},
    )
