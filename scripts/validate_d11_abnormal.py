"""Build a redacted D11 abnormal-scenario acceptance package.

All newly executed scenarios use controlled transports. The script never
contacts Ezviz or the configured language-model provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.service.agent_explanation_service import AgentExplanationService
from backend.service.agent_provider import OpenAICompatibleLLMProvider
from backend.utils import ezviz_auth as auth_module
from backend.utils.ezviz_auth import EzvizAuth, EzvizTokenInvalidError
from contracts.v1.agent import AgentExplanationRequest


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "deliverables" / "zhang-d11-abnormal"
CAPTURE_DIR = ROOT / "deliverables" / "zhang-d2-snapshot-2026-08-15" / "batch-1"
QWEN_DIR = ROOT / "deliverables" / "zhang-d3-agent-llm"
QWEN_TIMEOUT = QWEN_DIR / "ezviz-qwen-live-validation-timeout-15.json"
QWEN_SUCCESS = QWEN_DIR / "ezviz-qwen-live-validation-final.json"
AGENT_REQUEST = ROOT / "contracts" / "v1" / "examples" / "agent_explanation_request.json"
TZ = timezone(timedelta(hours=8))

URL_PATTERN = re.compile(r"(?i)(?:https?|ezopen)://")
WINDOWS_PATH_PATTERN = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\r\n]+")
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|app[_-]?secret|access[_-]?token|device[_-]?serial|"
    r"media[_-]?(?:url|locator)|stream[_-]?url|playback[_-]?url)\b\s*[:=]\s*"
    r"(?!false\b|null\b|none\b|\[redacted\])[^\s,;]+"
)
FORBIDDEN_JSON_KEYS = {
    "api_key", "app_key", "app_secret", "access_token", "device_serial",
    "media_url", "media_locator", "temporary_url", "stream_url",
    "playback_url", "storage_key",
}


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="milliseconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if URL_PATTERN.search(serialized) or WINDOWS_PATH_PATTERN.search(serialized):
        raise ValueError("D11 report contains a URL or absolute path")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")


def report_flags() -> dict[str, Any]:
    return {
        "source_mode": "MOCK",
        "simulated": True,
        "contains_credentials": False,
        "contains_media_url": False,
    }


class FakeResponse:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


class QueuedAsyncClient:
    def __init__(self, payloads: list[dict[str, Any]], request_stages: list[str], **_kwargs):
        self.payloads = payloads
        self.request_stages = request_stages

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def _request(self, url: str) -> FakeResponse:
        if not self.payloads:
            raise AssertionError("controlled response queue is empty")
        self.request_stages.append(url.rsplit("/", 1)[-1])
        return FakeResponse(self.payloads.pop(0))

    async def post(self, url: str, **_kwargs):
        return await self._request(url)

    async def get(self, url: str, **_kwargs):
        return await self._request(url)


async def run_auth_case(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    queue = list(payloads)
    request_stages: list[str] = []
    token_calls = 0
    retry_sleeps = 0
    original_client = auth_module.httpx.AsyncClient
    original_get_token = EzvizAuth.get_valid_token
    original_sleep = auth_module.asyncio.sleep
    original_store = auth_module._TOKEN_STORE
    original_rejected = auth_module._ENV_TOKEN_REJECTED

    async def get_token() -> str:
        nonlocal token_calls
        token_calls += 1
        return f"controlled-token-{token_calls}"

    async def no_sleep(_seconds: float) -> None:
        nonlocal retry_sleeps
        retry_sleeps += 1

    auth_module.httpx.AsyncClient = lambda **kwargs: QueuedAsyncClient(
        queue, request_stages, **kwargs
    )
    EzvizAuth.get_valid_token = staticmethod(get_token)
    auth_module.asyncio.sleep = no_sleep
    auth_module._TOKEN_STORE = {"token": "controlled-cached", "expire_time": 9999999999}
    auth_module._ENV_TOKEN_REJECTED = False
    started = time.perf_counter()
    result = None
    error_code = None
    provider_code = None
    try:
        result = await EzvizAuth.request(
            "/device/info",
            body={"deviceSerial": "controlled-device"},
        )
    except EzvizTokenInvalidError as exc:
        error_code = exc.error_code
        provider_code = exc.provider_code
    finally:
        latency_ms = round((time.perf_counter() - started) * 1000)
        auth_module.httpx.AsyncClient = original_client
        EzvizAuth.get_valid_token = staticmethod(original_get_token)
        auth_module.asyncio.sleep = original_sleep
        auth_module._TOKEN_STORE = original_store
        auth_module._ENV_TOKEN_REJECTED = original_rejected
    return {
        "result_payload": result,
        "error_code": error_code,
        "provider_code": provider_code,
        "token_acquisitions": token_calls,
        "token_refresh_count": max(0, token_calls - 1),
        "request_count": len(request_stages),
        "request_stages": request_stages,
        "generic_retry_sleep_count": retry_sleeps,
        "latency_ms": latency_ms,
    }


async def token_invalid_report() -> dict[str, Any]:
    recovered = await run_auth_case([
        {"code": "10002", "msg": "invalid"},
        {"code": "200", "data": {"status": 1}},
    ])
    terminal = await run_auth_case([
        {"code": "10002", "msg": "invalid"},
        {"code": "10018", "msg": "expired"},
    ])
    recovered_passed = (
        recovered["result_payload"] == {"code": "200", "data": {"status": 1}}
        and recovered["token_refresh_count"] == 1
        and recovered["request_count"] == 2
        and recovered["generic_retry_sleep_count"] == 0
    )
    terminal_passed = (
        terminal["error_code"] == "EZVIZ_TOKEN_INVALID_AFTER_REFRESH"
        and terminal["provider_code"] == "10018"
        and terminal["token_refresh_count"] == 1
        and terminal["request_count"] == 2
        and terminal["generic_retry_sleep_count"] == 0
    )
    return {
        "schema_version": "1.0",
        "test_kind": "D11_TOKEN_INVALID_CONTROLLED_MOCK",
        "generated_at": now_iso(),
        "result": "PASS" if recovered_passed and terminal_passed else "FAIL",
        "refresh_then_success": {
            "result": "PASS" if recovered_passed else "FAIL",
            "initial_business_code": "10002",
            "final_business_code": (
                recovered["result_payload"].get("code")
                if isinstance(recovered["result_payload"], dict) else None
            ),
            **{key: recovered[key] for key in (
                "token_refresh_count", "request_count", "generic_retry_sleep_count", "latency_ms"
            )},
        },
        "refresh_then_invalid": {
            "result": "PASS" if terminal_passed else "FAIL",
            "initial_business_code": "10002",
            "final_business_code": terminal["provider_code"],
            "error_code": terminal["error_code"],
            **{key: terminal[key] for key in (
                "token_refresh_count", "request_count", "generic_retry_sleep_count", "latency_ms"
            )},
        },
        **report_flags(),
    }


async def device_offline_report() -> dict[str, Any]:
    case = await run_auth_case([{"code": "200", "data": {"status": 0}}])
    payload = case["result_payload"] if isinstance(case["result_payload"], dict) else {}
    online = payload.get("data", {}).get("status") not in {0, "0", False, "offline"}
    passed = (
        payload.get("code") == "200"
        and online is False
        and case["request_count"] == 1
        and case["generic_retry_sleep_count"] == 0
    )
    return {
        "schema_version": "1.0",
        "test_kind": "D11_DEVICE_OFFLINE_CONTROLLED_MOCK",
        "generated_at": now_iso(),
        "result": "PASS" if passed else "FAIL",
        "business_code": payload.get("code"),
        "online": online,
        "failure_reason": "DEVICE_OFFLINE" if online is False else "DEVICE_STATUS_UNEXPECTED",
        "status_request_count": case["request_count"],
        "generic_retry_sleep_count": case["generic_retry_sleep_count"],
        "snapshot_request_count": 0,
        "playback_request_count": 0,
        "latency_ms": case["latency_ms"],
        **report_flags(),
    }


async def qwen_invalid_json_report() -> dict[str, Any]:
    request = AgentExplanationRequest.model_validate(read_json(AGENT_REQUEST))
    raw_invalid = "controlled-invalid-json-private-content"
    provider_calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": raw_invalid}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider(
        base_url="https://controlled.invalid/v1",
        api_key="controlled-key",
        model="controlled-model",
        client=client,
    )
    service = AgentExplanationService(provider=provider)
    started = time.perf_counter()
    response = await service.explain(request)
    latency_ms = round((time.perf_counter() - started) * 1000)
    await client.aclose()
    serialized = response.model_dump_json()
    passed = (
        response.generated_by == "template-fallback-v1"
        and response.fallback_used is True
        and provider_calls == 1
        and raw_invalid not in serialized
    )
    return {
        "schema_version": "1.0",
        "test_kind": "D11_QWEN_INVALID_JSON_CONTROLLED_MOCK",
        "generated_at": now_iso(),
        "result": "PASS" if passed else "FAIL",
        "provider_request_count": provider_calls,
        "generated_by": response.generated_by,
        "fallback_used": response.fallback_used,
        "invalid_content_exposed": raw_invalid in serialized,
        "latency_ms": latency_ms,
        **report_flags(),
    }


async def run_mocks(output_dir: Path = OUTPUT_DIR) -> dict[str, dict[str, Any]]:
    reports = {
        "token": await token_invalid_report(),
        "device": await device_offline_report(),
        "qwen": await qwen_invalid_json_report(),
    }
    write_json(output_dir / "token-invalid-mock.json", reports["token"])
    write_json(output_dir / "device-offline-mock.json", reports["device"])
    write_json(output_dir / "qwen-invalid-json-mock.json", reports["qwen"])
    return reports


def capture_timeout_summary() -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    run_files = sorted(CAPTURE_DIR.glob("ezviz-live-validation-run-*.json"))
    for path in run_files:
        report = read_json(path)
        snapshot = next(
            (stage for stage in report.get("stages", []) if stage.get("stage") == "device_snapshot"),
            None,
        )
        if snapshot and snapshot.get("failure_reason") == "REQUEST_TIMEOUT":
            failures.append({
                "run_index": report.get("run_index"),
                "failure_reason": "REQUEST_TIMEOUT",
                "latency_ms": snapshot.get("latency_ms"),
            })
    return {
        "result": "PASS" if len(failures) == 4 else "FAIL",
        "attempt_count": len(run_files),
        "timeout_count": len(failures),
        "failures": failures,
        "evidence_source": "deliverables/zhang-d2-snapshot-2026-08-15/batch-1",
    }


def qwen_summary(path: Path, expected_result: str) -> dict[str, Any]:
    report = read_json(path)
    passed = report.get("result") == expected_result
    if expected_result == "SUCCESS":
        passed = passed and report.get("fallback_used") is False
    else:
        passed = (
            passed
            and report.get("fallback_used") is True
            and report.get("generated_by") == "template-fallback-v1"
        )
    return {
        "result": "PASS" if passed else "FAIL",
        "observed_result": report.get("result"),
        "model": report.get("model"),
        "generated_by": report.get("generated_by"),
        "fallback_used": report.get("fallback_used"),
        "failure_reason": report.get("failure_reason"),
        "latency_ms": report.get("latency_ms"),
        "evidence_source": path.relative_to(ROOT).as_posix(),
        "response_body_copied": False,
    }


def write_readme(summary: dict[str, Any], output_dir: Path) -> None:
    rows = []
    labels = {
        "token_invalid": "Token失效",
        "device_offline": "设备离线",
        "capture_timeout": "抓拍超时",
        "qwen_timeout": "Qwen超时",
        "qwen_invalid_json": "Qwen非法JSON",
        "qwen_success": "Qwen正常",
        "sensitive_information": "敏感信息检查",
    }
    for key, value in summary["scenarios"].items():
        rows.append(f"| {labels[key]} | {value['result']} | {value.get('evidence_source', '本目录报告')} |")
    text = "\n".join([
        "# D11异常场景验收报告",
        "",
        f"生成时间：{summary['generated_at']}",
        "",
        "本次新增异常场景全部使用受控Mock，不修改真实平台配置、不操作真实设备、不调用真实Qwen。抓拍超时和Qwen成功/超时仅引用已有脱敏记录。",
        "",
        "| 场景 | 结果 | 证据 |",
        "|---|---|---|",
        *rows,
        "",
        f"最终结果：`{summary['overall_result']}`",
        "",
        "能力边界：Mock结果只证明错误处理、有限重试和模板降级逻辑可复现，不代表重新执行了真实平台异常。",
        "",
    ])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "D11异常场景验收报告.md").write_text(text, encoding="utf-8")


def assemble(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    token = read_json(output_dir / "token-invalid-mock.json")
    device = read_json(output_dir / "device-offline-mock.json")
    invalid_json = read_json(output_dir / "qwen-invalid-json-mock.json")
    scenarios = {
        "token_invalid": {
            "result": token.get("result"),
            "refresh_count": token.get("refresh_then_success", {}).get("token_refresh_count"),
            "terminal_error_code": token.get("refresh_then_invalid", {}).get("error_code"),
            "evidence_source": "deliverables/zhang-d11-abnormal/token-invalid-mock.json",
        },
        "device_offline": {
            "result": device.get("result"),
            "status_request_count": device.get("status_request_count"),
            "snapshot_request_count": device.get("snapshot_request_count"),
            "failure_reason": device.get("failure_reason"),
            "evidence_source": "deliverables/zhang-d11-abnormal/device-offline-mock.json",
        },
        "capture_timeout": capture_timeout_summary(),
        "qwen_timeout": qwen_summary(QWEN_TIMEOUT, "FALLBACK"),
        "qwen_invalid_json": {
            "result": invalid_json.get("result"),
            "generated_by": invalid_json.get("generated_by"),
            "fallback_used": invalid_json.get("fallback_used"),
            "invalid_content_exposed": invalid_json.get("invalid_content_exposed"),
            "evidence_source": "deliverables/zhang-d11-abnormal/qwen-invalid-json-mock.json",
        },
        "qwen_success": qwen_summary(QWEN_SUCCESS, "SUCCESS"),
        "sensitive_information": {
            "result": "PENDING",
            "findings": None,
            "evidence_source": "deliverables/zhang-d11-abnormal/sensitive-scan.json",
        },
    }
    summary = {
        "schema_version": "1.0",
        "test_kind": "D11_ABNORMAL_ACCEPTANCE_SUMMARY",
        "generated_at": now_iso(),
        "execution_policy": "CONTROLLED_MOCK_WITH_EXISTING_REDACTED_EVIDENCE",
        "new_live_platform_calls": 0,
        "new_live_qwen_calls": 0,
        "scenarios": scenarios,
        "overall_result": "INCOMPLETE",
    }
    write_json(output_dir / "d11-summary.json", summary)
    write_readme(summary, output_dir)
    return summary


def inspect_json(value: Any, file_name: str, findings: list[dict[str, str]], prefix: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}"
            if key.lower() in FORBIDDEN_JSON_KEYS:
                findings.append({"file": file_name, "rule": "FORBIDDEN_JSON_KEY", "location": path})
            inspect_json(item, file_name, findings, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            inspect_json(item, file_name, findings, f"{prefix}[{index}]")
    elif isinstance(value, str):
        if URL_PATTERN.search(value):
            findings.append({"file": file_name, "rule": "URL_VALUE", "location": prefix})
        if WINDOWS_PATH_PATTERN.search(value):
            findings.append({"file": file_name, "rule": "ABSOLUTE_PATH_VALUE", "location": prefix})


def scan_deliverables(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    scanned: list[str] = []
    for path in sorted(output_dir.glob("*")):
        if not path.is_file() or path.name == "sensitive-scan.json":
            continue
        scanned.append(path.name)
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            try:
                inspect_json(json.loads(text), path.name, findings)
            except json.JSONDecodeError:
                findings.append({"file": path.name, "rule": "INVALID_JSON", "location": "$"})
        else:
            if URL_PATTERN.search(text):
                findings.append({"file": path.name, "rule": "URL_TEXT", "location": "text"})
            if WINDOWS_PATH_PATTERN.search(text):
                findings.append({"file": path.name, "rule": "ABSOLUTE_PATH_TEXT", "location": "text"})
            if SENSITIVE_ASSIGNMENT.search(text):
                findings.append({"file": path.name, "rule": "SENSITIVE_ASSIGNMENT", "location": "text"})
    report = {
        "schema_version": "1.0",
        "test_kind": "D11_SENSITIVE_INFORMATION_SCAN",
        "generated_at": now_iso(),
        "result": "PASS" if not findings else "FAIL",
        "scanned_file_count": len(scanned),
        "scanned_files": scanned,
        "findings_count": len(findings),
        "findings": findings,
        "contains_credentials": False,
        "contains_media_url": False,
    }
    write_json(output_dir / "sensitive-scan.json", report)

    summary_path = output_dir / "d11-summary.json"
    if summary_path.exists():
        summary = read_json(summary_path)
        scenario = summary["scenarios"]["sensitive_information"]
        scenario["result"] = report["result"]
        scenario["findings"] = len(findings)
        results = [item.get("result") for item in summary["scenarios"].values()]
        summary["overall_result"] = "PASS" if all(item == "PASS" for item in results) else "FAIL"
        summary["generated_at"] = now_iso()
        write_json(summary_path, summary)
        write_readme(summary, output_dir)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build controlled D11 abnormal acceptance reports.")
    parser.add_argument("command", choices=("run-mocks", "assemble", "scan"))
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    if args.command == "run-mocks":
        reports = asyncio.run(run_mocks(output_dir))
        passed = all(report.get("result") == "PASS" for report in reports.values())
        print(f"command=run-mocks result={'PASS' if passed else 'FAIL'}")
        return 0 if passed else 1
    if args.command == "assemble":
        summary = assemble(output_dir)
        passed = all(
            item.get("result") == "PASS"
            for key, item in summary["scenarios"].items()
            if key != "sensitive_information"
        )
        print(f"command=assemble result={'PASS' if passed else 'FAIL'}")
        return 0 if passed else 1
    report = scan_deliverables(output_dir)
    print(f"command=scan result={report['result']} findings={report['findings_count']}")
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
