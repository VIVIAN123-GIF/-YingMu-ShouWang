import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.config import (
    ENV_MODE,
    EZVIZ_CHANNEL_NO,
    EZVIZ_DEVICE_SERIAL,
    EZVIZ_DEVICE_VERIFY_CODE,
    EZVIZ_LIVE_PROTOCOL,
    EZVIZ_STATUS_TIMEOUT_SECONDS,
)
from backend.service.errors import ServiceError
from backend.utils.ezviz_api import EzvizAPI
from contracts.v1.platform import PlatformSnapshotResult, PlatformVideoSource


TZ = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)


class DeviceAdapter:
    def __init__(self):
        self.collection_active = True
        self._last_status: dict | None = None

    @staticmethod
    def _configured_serial() -> str:
        if not EZVIZ_DEVICE_SERIAL:
            raise ServiceError(503, "DEVICE_NOT_CONFIGURED", "EZVIZ_DEVICE_SERIAL is not configured")
        return EZVIZ_DEVICE_SERIAL

    @staticmethod
    def _device_ref(device_serial: str) -> str:
        digest = hashlib.sha256(device_serial.encode("utf-8")).hexdigest()[:12]
        return f"device-{digest}"

    async def status(self):
        if ENV_MODE == "mock":
            return {"online": True, "adapter_mode": "MOCK", "source_mode": "MOCK",
                    "device_alias": "camera-mock-001", "simulated": True,
                    "collection_active": self.collection_active}
        try:
            # 官方 status/get 是设备详细运行参数；在线状态以 device/info 的 status=1 为准。
            result = await asyncio.wait_for(
                EzvizAPI.get_device_info(self._configured_serial()),
                timeout=EZVIZ_STATUS_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning("Ezviz device status unavailable; returning last known state: %s", type(exc).__name__)
            if self._last_status is not None:
                return {**self._last_status, "status_stale": True}
            return {
                "online": False,
                "adapter_mode": "EZVIZ_CLOUD",
                "source_mode": "LIVE_DEVICE",
                "device_alias": "camera-live-001",
                "simulated": False,
                "collection_active": self.collection_active,
                "status_stale": True,
            }
        data = result.get("data", result)
        status = {"online": bool(data.get("status", data.get("online", 0))),
                  "adapter_mode": "EZVIZ_CLOUD", "source_mode": "LIVE_DEVICE",
                  "device_alias": "camera-live-001", "simulated": False,
                  "collection_active": self.collection_active,
                  "status_stale": False}
        self._last_status = status
        return status

    async def stop(self):
        self.collection_active = False
        live = ENV_MODE == "live"
        return {"online": None, "adapter_mode": "EZVIZ_CLOUD" if live else "MOCK",
                "source_mode": "LIVE_DEVICE" if live else "MOCK",
                "device_alias": "camera-live-001" if live else "camera-mock-001",
                "simulated": not live, "collection_active": False}

    async def capture_snapshot(
        self, *, request_id: str | None = None
    ) -> PlatformSnapshotResult:
        """Return the frozen internal contract; callers must not serialize its URL."""
        request_id = request_id or f"ezviz-capture-{uuid4().hex}"
        if ENV_MODE == "mock":
            return PlatformSnapshotResult(
                schema_version="platform-snapshot/1.0",
                request_id=request_id,
                device_ref="device-mock-001",
                channel_no=EZVIZ_CHANNEL_NO,
                captured_at=datetime.now(TZ),
                source_mode="MOCK",
                simulated=True,
                temporary_url=None,
                expires_at=None,
                provider_latency_ms=0,
            )
        device_serial = self._configured_serial()
        started = time.perf_counter()
        try:
            result = await EzvizAPI.capture_device_image(device_serial, EZVIZ_CHANNEL_NO)
        except Exception as exc:
            raise ServiceError(503, "EZVIZ_SNAPSHOT_UNAVAILABLE",
                               "Ezviz snapshot is temporarily unavailable") from exc
        data = result.get("data", result)
        temporary_url = data.get("picUrl") or data.get("url")
        try:
            return PlatformSnapshotResult(
                schema_version="platform-snapshot/1.0",
                request_id=request_id,
                device_ref=self._device_ref(device_serial),
                channel_no=EZVIZ_CHANNEL_NO,
                captured_at=datetime.now(TZ),
                source_mode="LIVE_DEVICE",
                simulated=False,
                temporary_url=temporary_url,
                expires_at=None,
                provider_latency_ms=round((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            raise ServiceError(
                503,
                "EZVIZ_SNAPSHOT_INVALID",
                "Ezviz returned an invalid snapshot response",
            ) from exc

    async def capture_video_source(
        self, *, request_id: str | None = None
    ) -> PlatformVideoSource:
        """Return a short-lived live stream source for private Worker recording."""
        if ENV_MODE != "live":
            raise ServiceError(503, "VIDEO_SOURCE_LIVE_REQUIRED", "live video requires live device mode")
        request_id = request_id or f"ezviz-video-{uuid4().hex}"
        device_serial = self._configured_serial()
        started = time.perf_counter()
        try:
            result = await EzvizAPI.get_live_address(
                device_serial,
                EZVIZ_CHANNEL_NO,
                protocol=EZVIZ_LIVE_PROTOCOL,
                code=EZVIZ_DEVICE_VERIFY_CODE,
            )
            data = result.get("data", result)
            temporary_url = data.get("url") or data.get("liveAddress") or data.get("hls")
            return PlatformVideoSource(
                schema_version="platform-video/1.0",
                request_id=request_id,
                device_ref=self._device_ref(device_serial),
                channel_no=EZVIZ_CHANNEL_NO,
                captured_at=datetime.now(TZ),
                source_mode="LIVE_DEVICE",
                simulated=False,
                temporary_url=temporary_url,
                expires_at=datetime.now(TZ) + timedelta(seconds=300),
                provider_latency_ms=round((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            raise ServiceError(503, "EZVIZ_VIDEO_SOURCE_UNAVAILABLE", "Ezviz live video source is unavailable") from exc

    async def snapshot(self) -> dict:
        """Run a capture and return a browser-safe audit view."""
        result = await self.capture_snapshot()
        public = result.model_dump(mode="json", exclude={"temporary_url"})
        public["temporary_url_stored"] = False
        return public

    async def live_address(self):
        try:
            result = await EzvizAPI.get_live_address(self._configured_serial(), EZVIZ_CHANNEL_NO)
        except Exception as exc:
            raise ServiceError(503, "EZVIZ_STREAM_UNAVAILABLE",
                               "Ezviz live stream is temporarily unavailable") from exc
        data = result.get("data", result)
        return {"source_mode": "LIVE_DEVICE", "simulated": False,
                "expires_in": 3600, "temporary_url": data.get("url") or data.get("liveAddress")
                or data.get("hls") or data.get("flv")}


device_adapter = DeviceAdapter()
