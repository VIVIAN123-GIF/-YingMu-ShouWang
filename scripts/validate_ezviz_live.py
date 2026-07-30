"""Run the ordered, redacted Ezviz live-device acceptance check.

This script never writes a token, AppSecret, device serial, image, or playback
URL.  Its JSON report is safe to retain with the delivery materials.
"""

import asyncio
import hashlib
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import (ENV_MODE, EZVIZ_BASE_URL, EZVIZ_CHANNEL_NO,
                            EZVIZ_DEVICE_SERIAL)
from backend.utils import ezviz_auth as auth_module
from backend.utils.ezviz_auth import EzvizAuth


REPORT_PATH = (Path(__file__).resolve().parents[1] / "deliverables" /
               "backend-2026-07-31" / "ezviz-live-validation.json")
TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="milliseconds")


def device_alias() -> str:
    digest = hashlib.sha256(EZVIZ_DEVICE_SERIAL.encode()).hexdigest()[:10]
    return f"device-{digest}"


def safe_failure(exc: Exception) -> str:
    """Keep exception output from becoming a credential or device-data leak."""
    if isinstance(exc, httpx.TimeoutException):
        return "REQUEST_TIMEOUT"
    if isinstance(exc, httpx.HTTPError):
        return "HTTP_REQUEST_ERROR"
    if isinstance(exc, ValueError):
        return "EZVIZ_BUSINESS_ERROR"
    return "UNEXPECTED_CLIENT_ERROR"


def business_code(payload: Any) -> str | None:
    return str(payload.get("code")) if isinstance(payload, dict) and payload.get("code") is not None else None


async def call_stage(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    """Make one request, refreshing an explicitly rejected cached token once."""
    started = time.perf_counter()
    for attempt in range(2):
        token = await EzvizAuth.get_valid_token()
        form = {**payload, "accessToken": token}
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(f"{EZVIZ_BASE_URL}{path}", data=form)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if business_code(body) not in {"10002", "10018"} or attempt == 1:
            return body, response.status_code, round((time.perf_counter() - started) * 1000)
        # Match the production client's invalid-token recovery without logging its value.
        auth_module._TOKEN_STORE = None
        auth_module._ENV_TOKEN_REJECTED = True
    raise RuntimeError("unreachable")


def skipped(stage: str, reason: str) -> dict[str, Any]:
    return {"stage": stage, "executed": False, "result": "SKIPPED", "reason": reason,
            "source_mode": "MOCK"}


async def validate_status() -> dict[str, Any]:
    record: dict[str, Any] = {"stage": "device_status", "executed": True,
                              "requested_at": now_iso(), "device_alias": device_alias()}
    started = time.perf_counter()
    try:
        body, http_status, _ = await call_stage(
            "/device/info", {"deviceSerial": EZVIZ_DEVICE_SERIAL})
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        code = business_code(body)
        data = body.get("data") if isinstance(body, dict) else None
        online = data.get("status") if isinstance(data, dict) else None
        success = http_status == 200 and code == "200" and online is not None
        record.update({"result": "SUCCESS" if success else "FAILED", "http_status": http_status,
                       "business_code": code, "latency_ms": elapsed_ms,
                       "online": bool(online) if online is not None else None,
                       "source_mode": "LIVE_DEVICE" if success else "MOCK",
                       "failure_reason": None if success else "DEVICE_STATUS_NOT_CONFIRMED"})
    except Exception as exc:
        record.update({"result": "FAILED", "http_status": None, "business_code": None,
                       "latency_ms": round((time.perf_counter() - started) * 1000),
                       "online": None, "source_mode": "MOCK",
                       "failure_reason": safe_failure(exc)})
    return record


async def validate_snapshot() -> dict[str, Any]:
    record: dict[str, Any] = {"stage": "device_snapshot", "executed": True,
                              "requested_at": now_iso(), "device_alias": device_alias()}
    started = time.perf_counter()
    try:
        body, http_status, _ = await call_stage(
            "/device/capture", {"deviceSerial": EZVIZ_DEVICE_SERIAL, "channelNo": EZVIZ_CHANNEL_NO})
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        code = business_code(body)
        data = body.get("data") if isinstance(body, dict) else None
        # 萤石抓图返回在不同版本中可能为 picUrl 或 url；两者都是短期授权地址。
        image_url = (data.get("picUrl") or data.get("url")) if isinstance(data, dict) else None
        valid_image = isinstance(image_url, str) and urlparse(image_url).scheme in {"http", "https"}
        authorized = False
        image_http_status = None
        if valid_image:
            # 只验证短期授权地址的响应头与首个数据块，不写入图片或 URL。
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                async with client.stream("GET", image_url) as image_response:
                    image_http_status = image_response.status_code
                    content_type = image_response.headers.get("content-type", "").lower()
                    first_chunk = await anext(image_response.aiter_bytes(), b"")
                    authorized = (
                        200 <= image_http_status < 300
                        and content_type.startswith("image/")
                        and bool(first_chunk)
                    )
        success = http_status == 200 and code == "200" and valid_image and authorized
        record.update({"result": "SUCCESS" if success else "FAILED", "http_status": http_status,
                       "business_code": code, "latency_ms": elapsed_ms,
                       "valid_image_obtained": valid_image,
                       "image_http_status": image_http_status,
                       "authorization_status": "AUTHORIZED" if authorized else "NOT_CONFIRMED",
                       "image_url_stored": False,
                       "source_mode": "LIVE_DEVICE" if success else "MOCK",
                       "failure_reason": None if success else "SNAPSHOT_NOT_CONFIRMED"})
    except Exception as exc:
        record.update({"result": "FAILED", "http_status": None, "business_code": None,
                       "latency_ms": round((time.perf_counter() - started) * 1000),
                       "valid_image_obtained": False,
                       "authorization_status": "NOT_CONFIRMED", "image_url_stored": False,
                       "source_mode": "MOCK", "failure_reason": safe_failure(exc)})
    return record


async def validate_live_address() -> dict[str, Any]:
    record: dict[str, Any] = {"stage": "temporary_playback_address", "executed": True,
                              "requested_at": now_iso(), "device_alias": device_alias()}
    started = time.perf_counter()
    try:
        body, http_status, _ = await call_stage(
            "/v2/live/address/get",
            {"deviceSerial": EZVIZ_DEVICE_SERIAL, "channelNo": EZVIZ_CHANNEL_NO,
             "protocol": 2, "expireTime": 3600, "quality": 2})
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        code = business_code(body)
        data = body.get("data") if isinstance(body, dict) else None
        address = (data.get("url") or data.get("hls") or data.get("liveAddress")) if isinstance(data, dict) else None
        valid_address = isinstance(address, str) and urlparse(address).scheme in {"http", "https"}
        success = http_status == 200 and code == "200" and valid_address
        record.update({"result": "SUCCESS" if success else "FAILED", "http_status": http_status,
                       "business_code": code, "latency_ms": elapsed_ms,
                       "temporary_address_obtained": valid_address, "temporary_address_stored": False,
                       "source_mode": "LIVE_DEVICE" if success else "MOCK",
                       "failure_reason": None if success else "PLAYBACK_ADDRESS_NOT_CONFIRMED"})
    except Exception as exc:
        record.update({"result": "FAILED", "http_status": None, "business_code": None,
                       "latency_ms": round((time.perf_counter() - started) * 1000),
                       "temporary_address_obtained": False,
                       "temporary_address_stored": False, "source_mode": "MOCK",
                       "failure_reason": safe_failure(exc)})
    return record


async def main() -> int:
    report: dict[str, Any] = {"schema_version": "1.0", "test_kind": "EZVIZ_LIVE_ACCEPTANCE",
                              "generated_at": now_iso(), "device_alias": device_alias() if EZVIZ_DEVICE_SERIAL else None,
                              "contains_credentials": False, "contains_permanent_public_url": False,
                              "stages": []}
    if ENV_MODE != "live" or not EZVIZ_DEVICE_SERIAL:
        report["stages"] = [skipped("device_status", "LIVE_CONFIGURATION_REQUIRED"),
                            skipped("device_snapshot", "DEVICE_STATUS_NOT_SUCCESSFUL"),
                            skipped("temporary_playback_address", "SNAPSHOT_NOT_SUCCESSFUL")]
    else:
        status = await validate_status()
        report["stages"].append(status)
        if status["result"] != "SUCCESS":
            report["stages"].extend([skipped("device_snapshot", "DEVICE_STATUS_NOT_SUCCESSFUL"),
                                     skipped("temporary_playback_address", "SNAPSHOT_NOT_SUCCESSFUL")])
        else:
            snapshot = await validate_snapshot()
            report["stages"].append(snapshot)
            if snapshot["result"] != "SUCCESS":
                report["stages"].append(skipped("temporary_playback_address", "SNAPSHOT_NOT_SUCCESSFUL"))
            else:
                report["stages"].append(await validate_live_address())

    report["overall_result"] = "SUCCESS" if all(stage.get("result") == "SUCCESS" for stage in report["stages"]) else "INCOMPLETE"
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"report={REPORT_PATH.relative_to(Path.cwd())} overall_result={report['overall_result']}")
    return 0 if report["overall_result"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
