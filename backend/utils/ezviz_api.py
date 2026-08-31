from typing import Dict, Any, Optional
from backend.config import EZVIZ_CAPTURE_TIMEOUT_SECONDS, EZVIZ_LIVE_QUALITY
from backend.utils.ezviz_auth import EzvizAuth


class EzvizAPI:
    """
    萤石开放平台业务接口封装层
    所有接口统一底层复用EzvizAuth.request，自动处理token、重试、网络异常
    接口路径、出入参完全对齐ys7_mock V2 Mock服务与线上lapp标准
    """

    # ===================== 设备管理接口 =====================
    @staticmethod
    async def get_device_list(page_start: int = 0, page_size: int = 20) -> Dict[str, Any]:
        """获取设备分页列表"""
        return await EzvizAuth.request(
            path="/device/list",
            body={
                "pageStart": page_start,
                "pageSize": page_size
            }
        )

    @staticmethod
    async def get_device_status(device_serial: str) -> Dict[str, Any]:
        """查询单台设备在线状态"""
        return await EzvizAuth.request(
            path="/device/status/get",
            body={"deviceSerial": device_serial}
        )

    @staticmethod
    async def get_device_info(device_serial: str) -> Dict[str, Any]:
        """获取设备完整详情（型号、固件、在线状态）"""
        return await EzvizAuth.request(
            path="/device/info",
            body={"deviceSerial": device_serial}
        )

    # ===================== 直播取流接口 =====================
    @staticmethod
    async def get_live_address(
        device_serial: str,
        channel_no: int = 1,
        protocol: int = 2,
        expire_time: int = 3600,
        quality: int = EZVIZ_LIVE_QUALITY,
        code: str = "",
    ) -> Dict[str, Any]:
        """
        获取设备直播播放地址
        protocol: 1 ezopen / 2 hls / 3 rtmp / 4 flv / 5 lhls
        quality: 1高清（主码流）/ 2流畅（子码流）
        expire_time: 链接有效期，单位秒
        """
        body = {
            "deviceSerial": device_serial,
            "channelNo": channel_no,
            "protocol": protocol,
            "expireTime": expire_time,
            "quality": quality,
        }
        if code:
            body["code"] = code
        return await EzvizAuth.request(
            path="/v2/live/address/get",
            body=body,
        )

    # ===================== 设备截图接口 =====================
    @staticmethod
    async def capture_device_image(
        device_serial: str,
        channel_no: int = 1
    ) -> Dict[str, Any]:
        """设备实时截图，返回图片临时访问链接"""
        return await EzvizAuth.request(
            path="/device/capture",
            body={
                "deviceSerial": device_serial,
                "channelNo": channel_no
            },
            timeout_seconds=EZVIZ_CAPTURE_TIMEOUT_SECONDS,
        )

    # ===================== 语音喊话接口 =====================
    @staticmethod
    async def voice_broadcast(
        device_serial: str,
        text: str
    ) -> Dict[str, Any]:
        """设备远程语音喊话"""
        return await EzvizAuth.request(
            path="/voice/broadcast",
            body={
                "deviceSerial": device_serial,
                "content": text
            }
        )

    # ===================== 历史告警查询接口 =====================
    @staticmethod
    async def get_alarm_list(
        device_serial: Optional[str] = None,
        page_start: int = 0,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """分页查询设备历史告警记录"""
        body = {
            "pageStart": page_start,
            "pageSize": page_size
        }
        if device_serial:
            body["deviceSerial"] = device_serial

        return await EzvizAuth.request(
            path="/alarm/list",
            body=body
        )
