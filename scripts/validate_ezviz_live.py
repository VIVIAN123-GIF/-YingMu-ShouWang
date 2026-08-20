"""Run ordered, redacted Ezviz live-device acceptance checks.

The script never writes a token, AppSecret, complete device serial, image, or
playback URL.  Each run is retained separately and the final run is also
written to the legacy report path for compatibility.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import (ENV_MODE, EZVIZ_ACCESS_TOKEN,
                            EZVIZ_ACCESS_TOKEN_EXPIRES_AT, EZVIZ_APP_KEY,
                            EZVIZ_APP_SECRET, EZVIZ_BASE_URL,
                            EZVIZ_CAPTURE_TIMEOUT_SECONDS,
                            EZVIZ_CHANNEL_NO, EZVIZ_DEVICE_SERIAL,
                            EZVIZ_DEVICE_VERIFY_CODE,
                            YINGMU_SNAPSHOT_DOWNLOAD_TIMEOUT_SECONDS)
from backend.utils import ezviz_auth as auth_module
from backend.utils.ezviz_auth import EzvizAuth
from contracts.v1.platform import PlatformSnapshotResult


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "deliverables" / "backend-2026-07-31"
REPORT_PATH = OUTPUT_DIR / "ezviz-live-validation.json"
SUMMARY_PATH = OUTPUT_DIR / "ezviz-live-validation-summary.json"
TZ = timezone(timedelta(hours=8))
MAX_BUSINESS_MESSAGE_LENGTH = 160

SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(access[_-]?token|app[_-]?secret|app[_-]?key|device[_-]?serial|"
    r"password|passwd|verification[_-]?code)\b\s*[:=]\s*[^\s,;]+"
)
URL_PATTERN = re.compile(r"(?i)https?://[^\s,;]+")
IPV4_PATTERN = re.compile(
    r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])"
)
MAC_PATTERN = re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])")
OPAQUE_VALUE_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{16,}(?![A-Za-z0-9_-])")


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="milliseconds")


def device_alias() -> str:
    digest = hashlib.sha256(EZVIZ_DEVICE_SERIAL.encode()).hexdigest()[:10]
    return f"device-{digest}"


def token_acquisition_mode() -> str:
    if EZVIZ_ACCESS_TOKEN and EZVIZ_ACCESS_TOKEN_EXPIRES_AT:
        return "ENV_TOKEN"
    return "APP_SECRET"


def known_secrets(extra: Iterable[str] = ()) -> tuple[str, ...]:
    values = (EZVIZ_APP_KEY, EZVIZ_APP_SECRET, EZVIZ_ACCESS_TOKEN,
              EZVIZ_DEVICE_SERIAL, EZVIZ_DEVICE_VERIFY_CODE, *extra)
    return tuple(value for value in values if isinstance(value, str) and value)


def safe_business_message(payload: Any, extra_secrets: Iterable[str] = ()) -> str | None:
    """Return a short allowlisted diagnostic without identifiers or URLs."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("msg", payload.get("message"))
    if raw is None:
        return None
    message = str(raw)
    for secret in sorted(known_secrets(extra_secrets), key=len, reverse=True):
        message = message.replace(secret, "[REDACTED]")
    message = SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", message)
    message = URL_PATTERN.sub("[URL_REDACTED]", message)
    message = IPV4_PATTERN.sub("[IP_REDACTED]", message)
    message = MAC_PATTERN.sub("[NETWORK_REDACTED]", message)
    message = OPAQUE_VALUE_PATTERN.sub("[REDACTED]", message)
    message = " ".join(message.split())
    return message[:MAX_BUSINESS_MESSAGE_LENGTH] or None


def safe_failure(exc: Exception) -> str:
    """Map exceptions to stable labels without serializing exception text."""
    if isinstance(exc, httpx.TimeoutException):
        return "REQUEST_TIMEOUT"
    if isinstance(exc, httpx.HTTPError):
        return "HTTP_REQUEST_ERROR"
    if isinstance(exc, ValueError):
        return "EZVIZ_BUSINESS_ERROR"
    return "UNEXPECTED_CLIENT_ERROR"


def business_code(payload: Any) -> str | None:
    return str(payload.get("code")) if isinstance(payload, dict) and payload.get("code") is not None else None


def business_failure_reason(code: str | None, fallback: str) -> str:
    if code and code != "200":
        safe_code = re.sub(r"[^A-Za-z0-9_-]", "_", code)[:32]
        return f"EZVIZ_BUSINESS_ERROR_{safe_code}"
    return fallback


def normalize_online(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "online"}:
            return True
        if normalized in {"0", "false", "offline"}:
            return False
    return None


async def call_stage(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int, int, str | None]:
    """Make one request, refreshing an explicitly rejected cached token once."""
    started = time.perf_counter()
    for attempt in range(2):
        token = await EzvizAuth.get_valid_token()
        form = {**payload, "accessToken": token}
        timeout_seconds = EZVIZ_CAPTURE_TIMEOUT_SECONDS if path == "/device/capture" else 12.0
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(f"{EZVIZ_BASE_URL}{path}", data=form)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if business_code(body) not in {"10002", "10018"} or attempt == 1:
            elapsed = round((time.perf_counter() - started) * 1000)
            return body, response.status_code, elapsed, safe_business_message(body, (token,))
        auth_module._TOKEN_STORE = None
        auth_module._ENV_TOKEN_REJECTED = True
    raise RuntimeError("unreachable")


def skipped(stage: str, reason: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "executed": False,
        "result": "SKIPPED",
        "http_status": None,
        "business_code": None,
        "business_message": None,
        "latency_ms": None,
        "source_mode": "MOCK",
        "failure_reason": reason,
    }


async def validate_status() -> dict[str, Any]:
    record: dict[str, Any] = {
        "stage": "device_status", "executed": True,
        "requested_at": now_iso(), "device_alias": device_alias(),
    }
    started = time.perf_counter()
    try:
        body, http_status, elapsed_ms, message = await call_stage(
            "/device/info", {"deviceSerial": EZVIZ_DEVICE_SERIAL})
        code = business_code(body)
        data = body.get("data") if isinstance(body, dict) else None
        online = normalize_online(data.get("status") if isinstance(data, dict) else None)
        api_success = http_status == 200 and code == "200" and online is not None
        success = api_success and online is True
        if success:
            reason = None
        elif api_success and online is False:
            reason = "DEVICE_OFFLINE"
        else:
            reason = business_failure_reason(code, "DEVICE_STATUS_NOT_CONFIRMED")
        record.update({
            "result": "SUCCESS" if success else "FAILED",
            "api_call_succeeded": api_success,
            "http_status": http_status,
            "business_code": code,
            "business_message": message,
            "latency_ms": elapsed_ms,
            "online": online,
            "source_mode": "LIVE_DEVICE" if success else "MOCK",
            "failure_reason": reason,
        })
    except Exception as exc:
        record.update({
            "result": "FAILED", "api_call_succeeded": False,
            "http_status": None, "business_code": None, "business_message": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "online": None, "source_mode": "MOCK", "failure_reason": safe_failure(exc),
        })
    return record


async def validate_snapshot() -> dict[str, Any]:
    record: dict[str, Any] = {
        "stage": "device_snapshot", "executed": True,
        "requested_at": now_iso(), "device_alias": device_alias(),
    }
    started = time.perf_counter()
    try:
        body, http_status, elapsed_ms, message = await call_stage(
            "/device/capture", {"deviceSerial": EZVIZ_DEVICE_SERIAL, "channelNo": EZVIZ_CHANNEL_NO})
        code = business_code(body)
        data = body.get("data") if isinstance(body, dict) else None
        image_url = (data.get("picUrl") or data.get("url")) if isinstance(data, dict) else None
        valid_image = isinstance(image_url, str) and urlparse(image_url).scheme in {"http", "https"}
        captured_at = datetime.now(TZ)
        authorized = False
        image_http_status = None
        if valid_image:
            async with httpx.AsyncClient(
                timeout=YINGMU_SNAPSHOT_DOWNLOAD_TIMEOUT_SECONDS,
                follow_redirects=True,
            ) as client:
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
        contract = None
        if success:
            contract = PlatformSnapshotResult(
                schema_version="platform-snapshot/1.0",
                request_id=f"ezviz-capture-{uuid4().hex}",
                device_ref=device_alias(),
                channel_no=EZVIZ_CHANNEL_NO,
                captured_at=captured_at,
                source_mode="LIVE_DEVICE",
                simulated=False,
                temporary_url=image_url,
                expires_at=None,
                provider_latency_ms=elapsed_ms,
            )
        record.update({
            "result": "SUCCESS" if success else "FAILED",
            "http_status": http_status,
            "business_code": code,
            "business_message": message,
            "latency_ms": elapsed_ms,
            "valid_image_obtained": valid_image,
            "image_http_status": image_http_status,
            "authorization_status": "AUTHORIZED" if authorized else "NOT_CONFIRMED",
            "image_url_stored": False,
            "temporary_url_stored": False,
            "source_mode": "LIVE_DEVICE" if success else "MOCK",
            "simulated": not success,
            "failure_reason": None if success else business_failure_reason(code, "SNAPSHOT_NOT_CONFIRMED"),
        })
        if contract is not None:
            safe_contract = contract.model_dump(mode="json", exclude={"temporary_url"})
            record.update(safe_contract)
            record["temporary_url_stored"] = False
    except Exception as exc:
        record.update({
            "result": "FAILED", "http_status": None, "business_code": None,
            "business_message": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "valid_image_obtained": False, "image_http_status": None,
            "authorization_status": "NOT_CONFIRMED", "image_url_stored": False,
            "temporary_url_stored": False, "source_mode": "MOCK",
            "simulated": True, "failure_reason": safe_failure(exc),
        })
    return record


async def validate_live_address() -> dict[str, Any]:
    record: dict[str, Any] = {
        "stage": "temporary_playback_address", "executed": True,
        "requested_at": now_iso(), "device_alias": device_alias(),
    }
    started = time.perf_counter()
    try:
        request_payload: dict[str, Any] = {
            "deviceSerial": EZVIZ_DEVICE_SERIAL,
            "channelNo": EZVIZ_CHANNEL_NO,
            "protocol": 2,
            "expireTime": 3600,
            "quality": 2,
        }
        if EZVIZ_DEVICE_VERIFY_CODE:
            request_payload["code"] = EZVIZ_DEVICE_VERIFY_CODE
        body, http_status, elapsed_ms, message = await call_stage(
            "/v2/live/address/get", request_payload)
        code = business_code(body)
        hls_attempt = {
            "protocol": "hls",
            "http_status": http_status,
            "business_code": code,
            "business_message": message,
            "latency_ms": elapsed_ms,
        }
        fallback_attempted = False
        selected_protocol = "hls"
        if code == "60019" and EZVIZ_DEVICE_VERIFY_CODE:
            fallback_attempted = True
            selected_protocol = "ezopen"
            fallback_payload = {
                "deviceSerial": EZVIZ_DEVICE_SERIAL,
                "channelNo": EZVIZ_CHANNEL_NO,
                "protocol": 1,
                "quality": 2,
                "code": EZVIZ_DEVICE_VERIFY_CODE,
            }
            body, http_status, fallback_elapsed, message = await call_stage(
                "/v2/live/address/get", fallback_payload)
            elapsed_ms += fallback_elapsed
            code = business_code(body)
        data = body.get("data") if isinstance(body, dict) else None
        address = (data.get("url") or data.get("hls") or data.get("liveAddress")) if isinstance(data, dict) else None
        valid_schemes = {"ezopen"} if selected_protocol == "ezopen" else {"http", "https"}
        valid_address = isinstance(address, str) and urlparse(address).scheme in valid_schemes
        success = http_status == 200 and code == "200" and valid_address
        record.update({
            "result": "SUCCESS" if success else "FAILED",
            "requested_protocol": "hls",
            "fallback_attempted": fallback_attempted,
            "selected_protocol": selected_protocol,
            "hls_attempt": hls_attempt,
            "http_status": http_status,
            "business_code": code,
            "business_message": message,
            "latency_ms": elapsed_ms,
            "temporary_address_obtained": valid_address,
            "temporary_address_stored": False,
            "source_mode": "LIVE_DEVICE" if success else "MOCK",
            "failure_reason": None if success else business_failure_reason(code, "PLAYBACK_ADDRESS_NOT_CONFIRMED"),
        })
    except Exception as exc:
        record.update({
            "result": "FAILED", "http_status": None, "business_code": None,
            "business_message": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "temporary_address_obtained": False, "temporary_address_stored": False,
            "source_mode": "MOCK", "failure_reason": safe_failure(exc),
        })
    return record


async def run_once(run_index: int, capture_only: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "test_kind": "EZVIZ_LIVE_ACCEPTANCE",
        "generated_at": now_iso(),
        "run_index": run_index,
        "acceptance_mode": "CAPTURE_ONLY" if capture_only else "FULL_PLATFORM",
        "token_acquisition_mode": token_acquisition_mode(),
        "device_alias": device_alias() if EZVIZ_DEVICE_SERIAL else None,
        "contains_credentials": False,
        "contains_permanent_public_url": False,
        "contains_temporary_url": False,
        "stages": [],
    }
    if ENV_MODE != "live" or not EZVIZ_DEVICE_SERIAL:
        report["stages"] = [
            skipped("device_status", "LIVE_CONFIGURATION_REQUIRED"),
            skipped("device_snapshot", "DEVICE_STATUS_NOT_SUCCESSFUL"),
        ]
        if not capture_only:
            report["stages"].append(
                skipped("temporary_playback_address", "SNAPSHOT_NOT_SUCCESSFUL")
            )
    else:
        status = await validate_status()
        report["stages"].append(status)
        if status["result"] != "SUCCESS":
            report["stages"].append(
                skipped("device_snapshot", "DEVICE_STATUS_NOT_SUCCESSFUL")
            )
            if not capture_only:
                report["stages"].append(
                    skipped("temporary_playback_address", "SNAPSHOT_NOT_SUCCESSFUL")
                )
        else:
            snapshot = await validate_snapshot()
            report["stages"].append(snapshot)
            if capture_only:
                pass
            elif snapshot["result"] != "SUCCESS":
                report["stages"].append(skipped("temporary_playback_address", "SNAPSHOT_NOT_SUCCESSFUL"))
            else:
                report["stages"].append(await validate_live_address())
    report["overall_result"] = (
        "SUCCESS" if all(stage.get("result") == "SUCCESS" for stage in report["stages"])
        else "INCOMPLETE"
    )
    return report


def semantic_signature(report: dict[str, Any]) -> list[dict[str, Any]]:
    fields = ("stage", "executed", "result", "business_code", "online",
              "source_mode", "failure_reason")
    return [{field: stage.get(field) for field in fields} for stage in report["stages"]]


def write_json(path: Path, payload: object) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for secret in known_secrets():
        if secret in serialized:
            raise ValueError("acceptance report contains a configured secret")
    if URL_PATTERN.search(serialized):
        raise ValueError("acceptance report contains a URL")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")


async def run_many(runs: int, interval_seconds: float = 2.0,
                   output_dir: Path = OUTPUT_DIR,
                   capture_only: bool = False) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for run_index in range(1, runs + 1):
        report = (
            await run_once(run_index, capture_only=True)
            if capture_only else await run_once(run_index)
        )
        reports.append(report)
        write_json(output_dir / f"ezviz-live-validation-run-{run_index}.json", report)
        if run_index < runs and interval_seconds:
            await asyncio.sleep(interval_seconds)

    signatures = [semantic_signature(report) for report in reports]
    capture_stages = [
        stage
        for report in reports
        for stage in report["stages"]
        if stage.get("stage") == "device_snapshot"
    ]
    capture_latencies = [
        stage["provider_latency_ms"]
        for stage in capture_stages
        if stage.get("result") == "SUCCESS"
        and isinstance(stage.get("provider_latency_ms"), int)
    ]
    summary = {
        "schema_version": "1.0",
        "test_kind": "EZVIZ_LIVE_ACCEPTANCE_SUMMARY",
        "generated_at": now_iso(),
        "runs": runs,
        "acceptance_mode": "CAPTURE_ONLY" if capture_only else "FULL_PLATFORM",
        "token_acquisition_mode": token_acquisition_mode(),
        "successful_runs": sum(report["overall_result"] == "SUCCESS" for report in reports),
        "capture_records": len(capture_stages),
        "capture_attempts": sum(stage.get("executed") is True for stage in capture_stages),
        "capture_successes": sum(stage.get("result") == "SUCCESS" for stage in capture_stages),
        "capture_failures": sum(stage.get("result") == "FAILED" for stage in capture_stages),
        "capture_skipped": sum(stage.get("result") == "SKIPPED" for stage in capture_stages),
        "capture_latency_ms": {
            "minimum": min(capture_latencies) if capture_latencies else None,
            "maximum": max(capture_latencies) if capture_latencies else None,
            "average": (
                round(sum(capture_latencies) / len(capture_latencies))
                if capture_latencies else None
            ),
        },
        "consistent": all(signature == signatures[0] for signature in signatures),
        "semantic_signature": signatures[0],
        "contains_credentials": False,
        "contains_permanent_public_url": False,
        "contains_temporary_url": False,
        "overall_result": (
            "SUCCESS" if all(report["overall_result"] == "SUCCESS" for report in reports)
            else "INCOMPLETE"
        ),
    }
    write_json(output_dir / REPORT_PATH.name, reports[-1])
    write_json(output_dir / SUMMARY_PATH.name, summary)
    return summary


def exit_code(summary: dict[str, Any]) -> int:
    return 0 if summary.get("overall_result") == "SUCCESS" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run redacted Ezviz live-device acceptance checks.")
    parser.add_argument("--runs", type=int, default=1, help="number of sequential retained runs")
    parser.add_argument("--interval-seconds", type=float, default=2.0,
                        help="delay between retained runs")
    parser.add_argument(
        "--capture-only", action="store_true",
        help="validate device status and snapshot only; do not request playback",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=OUTPUT_DIR,
        help="directory for retained redacted reports",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.interval_seconds < 0:
        parser.error("--interval-seconds must be non-negative")
    return args


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    summary = asyncio.run(run_many(
        args.runs, args.interval_seconds, output_dir, args.capture_only
    ))
    try:
        display_dir = output_dir.relative_to(ROOT)
    except ValueError:
        display_dir = output_dir
    print(f"reports={display_dir} runs={args.runs} "
          f"overall_result={summary['overall_result']}")
    return exit_code(summary)


if __name__ == "__main__":
    raise SystemExit(main())
