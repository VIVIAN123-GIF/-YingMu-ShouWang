from __future__ import annotations

import asyncio
import json

from scripts import validate_d11_abnormal as validator


def test_controlled_mock_reports_cover_required_failures(tmp_path):
    reports = asyncio.run(validator.run_mocks(tmp_path))

    assert reports["token"]["result"] == "PASS"
    assert reports["token"]["refresh_then_success"]["token_refresh_count"] == 1
    assert reports["token"]["refresh_then_invalid"]["error_code"] == (
        "EZVIZ_TOKEN_INVALID_AFTER_REFRESH"
    )
    assert reports["device"]["result"] == "PASS"
    assert reports["device"]["status_request_count"] == 1
    assert reports["device"]["snapshot_request_count"] == 0
    assert reports["qwen"]["generated_by"] == "template-fallback-v1"
    assert reports["qwen"]["fallback_used"] is True
    assert reports["qwen"]["invalid_content_exposed"] is False


def test_assemble_reuses_existing_metadata_without_response_body(tmp_path):
    asyncio.run(validator.run_mocks(tmp_path))

    summary = validator.assemble(tmp_path)

    assert summary["new_live_platform_calls"] == 0
    assert summary["new_live_qwen_calls"] == 0
    assert summary["scenarios"]["capture_timeout"]["timeout_count"] == 4
    assert summary["scenarios"]["qwen_timeout"]["result"] == "PASS"
    assert summary["scenarios"]["qwen_timeout"]["fallback_used"] is True
    assert summary["scenarios"]["qwen_success"]["result"] == "PASS"
    assert summary["scenarios"]["qwen_success"]["fallback_used"] is False
    serialized = json.dumps(summary, ensure_ascii=False)
    assert "reasoning_points" not in serialized
    assert "recommended_action_text" not in serialized


def test_sensitive_scan_passes_generated_package(tmp_path):
    asyncio.run(validator.run_mocks(tmp_path))
    validator.assemble(tmp_path)

    scan = validator.scan_deliverables(tmp_path)
    summary = validator.read_json(tmp_path / "d11-summary.json")

    assert scan["result"] == "PASS"
    assert scan["findings_count"] == 0
    assert summary["overall_result"] == "PASS"


def test_sensitive_scan_reports_forbidden_values_without_copying_them(tmp_path):
    (tmp_path / "unsafe.json").write_text(
        json.dumps({"media_url": "https://private.invalid/media"}),
        encoding="utf-8",
    )

    scan = validator.scan_deliverables(tmp_path)

    assert scan["result"] == "FAIL"
    assert scan["findings_count"] >= 1
    serialized = json.dumps(scan)
    assert "private.invalid" not in serialized
