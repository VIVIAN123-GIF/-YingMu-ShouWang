from backend.config import ENV_MODE, EZVIZ_CHANNEL_NO, EZVIZ_DEVICE_SERIAL
from backend.service.errors import ServiceError
from backend.utils.ezviz_api import EzvizAPI


class DeviceAdapter:
    def __init__(self):
        self.collection_active = True

    @staticmethod
    def _configured_serial() -> str:
        if not EZVIZ_DEVICE_SERIAL:
            raise ServiceError(503, "DEVICE_NOT_CONFIGURED", "EZVIZ_DEVICE_SERIAL is not configured")
        return EZVIZ_DEVICE_SERIAL

    async def status(self):
        if ENV_MODE == "mock" and not EZVIZ_DEVICE_SERIAL:
            return {"online": True, "adapter_mode": "MOCK", "source_mode": "MOCK",
                    "device_alias": "camera-mock-001", "simulated": True,
                    "collection_active": self.collection_active}
        try:
            # 官方 status/get 是设备详细运行参数；在线状态以 device/info 的 status=1 为准。
            result = await EzvizAPI.get_device_info(self._configured_serial())
        except Exception as exc:
            raise ServiceError(503, "EZVIZ_STATUS_UNAVAILABLE",
                               "Ezviz device status is temporarily unavailable") from exc
        data = result.get("data", result)
        return {"online": bool(data.get("status", data.get("online", 0))),
                "adapter_mode": "EZVIZ_CLOUD", "source_mode": "LIVE_DEVICE",
                "device_alias": "camera-live-001", "simulated": False,
                "collection_active": self.collection_active}

    async def stop(self):
        self.collection_active = False
        live = ENV_MODE == "live"
        return {"online": None, "adapter_mode": "EZVIZ_CLOUD" if live else "MOCK",
                "source_mode": "LIVE_DEVICE" if live else "MOCK",
                "device_alias": "camera-live-001" if live else "camera-mock-001",
                "simulated": not live, "collection_active": False}

    async def snapshot(self):
        if ENV_MODE == "mock" and not EZVIZ_DEVICE_SERIAL:
            return {"source_mode": "MOCK", "simulated": True, "asset_id": "asset-mock-snapshot-001",
                    "temporary_url": None}
        try:
            result = await EzvizAPI.capture_device_image(self._configured_serial(), EZVIZ_CHANNEL_NO)
        except Exception as exc:
            raise ServiceError(503, "EZVIZ_SNAPSHOT_UNAVAILABLE",
                               "Ezviz snapshot is temporarily unavailable") from exc
        data = result.get("data", result)
        return {"source_mode": "LIVE_DEVICE", "simulated": False,
                "asset_id": data.get("id", "asset-live-snapshot"),
                "temporary_url": data.get("picUrl") or data.get("url")}

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
