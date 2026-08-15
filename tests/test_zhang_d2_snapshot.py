from __future__ import annotations

import asyncio
import json

import pytest

from backend.service import device_adapter as adapter_module
from backend.service.device_adapter import DeviceAdapter
from contracts.v1.platform import PlatformSnapshotResult
from scripts import validate_ezviz_live as validator


def test_live_capture_is_normalized_and_public_view_is_redacted(monkeypatch):
    temporary_url = "https://snapshot.example/private/capture.jpg"

    async def fake_capture(device_serial: str, channel_no: int):
        assert device_serial == "SERIAL-PRIVATE-001"
        assert channel_no == 2
        return {"code": "200", "data": {"picUrl": temporary_url}}

    monkeypatch.setattr(adapter_module, "ENV_MODE", "live")
    monkeypatch.setattr(adapter_module, "EZVIZ_DEVICE_SERIAL", "SERIAL-PRIVATE-001")
    monkeypatch.setattr(adapter_module, "EZVIZ_CHANNEL_NO", 2)
    monkeypatch.setattr(
        adapter_module.EzvizAPI, "capture_device_image", fake_capture
    )
    adapter = DeviceAdapter()

    internal = asyncio.run(adapter.capture_snapshot(request_id="ezviz-capture-test-001"))

    assert isinstance(internal, PlatformSnapshotResult)
    assert internal.source_mode == "LIVE_DEVICE"
    assert internal.simulated is False
    assert str(internal.temporary_url) == temporary_url
    assert internal.device_ref.startswith("device-")
    assert "SERIAL-PRIVATE-001" not in internal.device_ref

    public = asyncio.run(adapter.snapshot())
    serialized = json.dumps(public, ensure_ascii=False)
    assert "temporary_url" not in public
    assert public["temporary_url_stored"] is False
    assert temporary_url not in serialized
    assert "SERIAL-PRIVATE-001" not in serialized
    assert "asset_id" not in public


def test_capture_only_skips_playback_stage(monkeypatch):
    monkeypatch.setattr(validator, "ENV_MODE", "live")
    monkeypatch.setattr(validator, "EZVIZ_DEVICE_SERIAL", "test-device")

    async def fake_status():
        return {
            "stage": "device_status",
            "executed": True,
            "result": "SUCCESS",
            "online": True,
            "source_mode": "LIVE_DEVICE",
            "failure_reason": None,
        }

    async def fake_snapshot():
        return {
            "stage": "device_snapshot",
            "executed": True,
            "result": "SUCCESS",
            "business_code": "200",
            "source_mode": "LIVE_DEVICE",
            "provider_latency_ms": 321,
            "failure_reason": None,
            "temporary_url_stored": False,
        }

    async def must_not_run():
        raise AssertionError("capture-only mode must not request a playback address")

    monkeypatch.setattr(validator, "validate_status", fake_status)
    monkeypatch.setattr(validator, "validate_snapshot", fake_snapshot)
    monkeypatch.setattr(validator, "validate_live_address", must_not_run)

    report = asyncio.run(validator.run_once(1, capture_only=True))

    assert report["acceptance_mode"] == "CAPTURE_ONLY"
    assert report["overall_result"] == "SUCCESS"
    assert [stage["stage"] for stage in report["stages"]] == [
        "device_status",
        "device_snapshot",
    ]


def test_ten_capture_records_are_retained_with_capture_summary(monkeypatch, tmp_path):
    async def fake_run_once(run_index: int, capture_only: bool = False):
        assert capture_only is True
        succeeded = run_index != 4
        return {
            "schema_version": "1.0",
            "test_kind": "EZVIZ_LIVE_ACCEPTANCE",
            "generated_at": f"2026-08-15T10:00:{run_index:02d}+08:00",
            "run_index": run_index,
            "acceptance_mode": "CAPTURE_ONLY",
            "token_acquisition_mode": "APP_SECRET",
            "contains_credentials": False,
            "contains_permanent_public_url": False,
            "contains_temporary_url": False,
            "stages": [{
                "stage": "device_snapshot",
                "executed": True,
                "result": "SUCCESS" if succeeded else "FAILED",
                "business_code": "200" if succeeded else None,
                "online": None,
                "source_mode": "LIVE_DEVICE" if succeeded else "MOCK",
                "failure_reason": None if succeeded else "REQUEST_TIMEOUT",
                "provider_latency_ms": 100 + run_index if succeeded else None,
                "temporary_url_stored": False,
            }],
            "overall_result": "SUCCESS" if succeeded else "INCOMPLETE",
        }

    monkeypatch.setattr(validator, "run_once", fake_run_once)
    summary = asyncio.run(
        validator.run_many(
            10, interval_seconds=0, output_dir=tmp_path, capture_only=True
        )
    )

    assert len(list(tmp_path.glob("ezviz-live-validation-run-*.json"))) == 10
    assert summary["capture_records"] == 10
    assert summary["capture_attempts"] == 10
    assert summary["capture_successes"] == 9
    assert summary["capture_failures"] == 1
    assert summary["capture_skipped"] == 0
    assert summary["contains_temporary_url"] is False
    failed = json.loads(
        (tmp_path / "ezviz-live-validation-run-4.json").read_text(encoding="utf-8")
    )
    assert failed["stages"][0]["failure_reason"] == "REQUEST_TIMEOUT"


@pytest.mark.parametrize(
    "payload",
    [
        {"temporary_url": "https://snapshot.example/private.jpg"},
        {"message": "access-token-private"},
    ],
)
def test_report_writer_rejects_urls_and_configured_secrets(monkeypatch, tmp_path, payload):
    monkeypatch.setattr(validator, "EZVIZ_ACCESS_TOKEN", "access-token-private")

    with pytest.raises(ValueError):
        validator.write_json(tmp_path / "unsafe.json", payload)

    assert not (tmp_path / "unsafe.json").exists()
