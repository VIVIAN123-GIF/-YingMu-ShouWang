import asyncio
import json

import pytest

from scripts import validate_ezviz_live as validator
from backend.service import device_adapter as device_module


@pytest.mark.parametrize("raw_status", [0, "0", False, "offline"])
def test_offline_status_is_failed_and_mock(monkeypatch, raw_status):
    async def fake_call_stage(path, payload):
        assert path == "/device/info"
        return {"code": "200", "msg": "操作成功", "data": {"status": raw_status}}, 200, 12, "操作成功"

    monkeypatch.setattr(validator, "call_stage", fake_call_stage)
    record = asyncio.run(validator.validate_status())

    assert record["api_call_succeeded"] is True
    assert record["online"] is False
    assert record["result"] == "FAILED"
    assert record["source_mode"] == "MOCK"
    assert record["failure_reason"] == "DEVICE_OFFLINE"


@pytest.mark.parametrize("raw_status", [1, "1", True, "online"])
def test_online_status_is_successful(monkeypatch, raw_status):
    async def fake_call_stage(path, payload):
        return {"code": "200", "msg": "操作成功", "data": {"status": raw_status}}, 200, 8, "操作成功"

    monkeypatch.setattr(validator, "call_stage", fake_call_stage)
    record = asyncio.run(validator.validate_status())

    assert record["online"] is True
    assert record["result"] == "SUCCESS"
    assert record["source_mode"] == "LIVE_DEVICE"
    assert record["failure_reason"] is None


def test_offline_status_skips_snapshot_and_playback(monkeypatch):
    monkeypatch.setattr(validator, "ENV_MODE", "live")
    monkeypatch.setattr(validator, "EZVIZ_DEVICE_SERIAL", "test-device")

    async def fake_status():
        return {"stage": "device_status", "result": "FAILED", "online": False,
                "source_mode": "MOCK", "failure_reason": "DEVICE_OFFLINE"}

    async def must_not_run():
        raise AssertionError("downstream stage should have been skipped")

    monkeypatch.setattr(validator, "validate_status", fake_status)
    monkeypatch.setattr(validator, "validate_snapshot", must_not_run)
    monkeypatch.setattr(validator, "validate_live_address", must_not_run)

    report = asyncio.run(validator.run_once(1))

    assert report["overall_result"] == "INCOMPLETE"
    assert [stage["result"] for stage in report["stages"]] == ["FAILED", "SKIPPED", "SKIPPED"]
    assert report["stages"][1]["source_mode"] == "MOCK"


def test_business_error_has_code_specific_reason_and_safe_message(monkeypatch):
    monkeypatch.setattr(validator, "EZVIZ_LIVE_PROTOCOL", 2)
    async def fake_call_stage(path, payload):
        message = "权限失败 token=[REDACTED] 地址=[URL_REDACTED]"
        return {"code": "60019", "msg": "raw is not persisted"}, 200, 29, message

    monkeypatch.setattr(validator, "call_stage", fake_call_stage)
    record = asyncio.run(validator.validate_live_address())

    assert record["result"] == "FAILED"
    assert record["business_code"] == "60019"
    assert record["business_message"] == "权限失败 token=[REDACTED] 地址=[URL_REDACTED]"
    assert record["failure_reason"] == "EZVIZ_BUSINESS_ERROR_60019"
    assert record["source_mode"] == "MOCK"


def test_live_address_uses_local_verify_code_without_persisting_it(monkeypatch):
    verify_code = "verify-code-private"
    captured = []

    async def fake_call_stage(path, payload):
        captured.append(dict(payload))
        return {"code": "60019", "msg": f"code={verify_code}"}, 200, 29, "code=[REDACTED]"

    monkeypatch.setattr(validator, "EZVIZ_DEVICE_VERIFY_CODE", verify_code)
    monkeypatch.setattr(validator, "EZVIZ_LIVE_PROTOCOL", 2)
    monkeypatch.setattr(validator, "call_stage", fake_call_stage)
    record = asyncio.run(validator.validate_live_address())

    assert [item["protocol"] for item in captured] == [2, 1]
    assert all(item["code"] == verify_code for item in captured)
    assert verify_code not in json.dumps(record, ensure_ascii=False)
    assert record["business_message"] == "code=[REDACTED]"
    assert record["fallback_attempted"] is True


def test_encrypted_hls_falls_back_to_ezopen_without_storing_address(monkeypatch):
    responses = iter([
        ({"code": "60019", "msg": "加密已开启"}, 200, 20, "加密已开启"),
        ({"code": "200", "msg": "操作成功", "data": {"url": "ezopen://private-address"}},
         200, 30, "操作成功"),
    ])

    async def fake_call_stage(path, payload):
        return next(responses)

    monkeypatch.setattr(validator, "EZVIZ_DEVICE_VERIFY_CODE", "local-only-code")
    monkeypatch.setattr(validator, "EZVIZ_LIVE_PROTOCOL", 2)
    monkeypatch.setattr(validator, "call_stage", fake_call_stage)
    record = asyncio.run(validator.validate_live_address())

    assert record["result"] == "SUCCESS"
    assert record["selected_protocol"] == "ezopen"
    assert record["address_attempt"]["business_code"] == "60019"
    assert record["business_code"] == "200"
    assert record["latency_ms"] == 50
    assert record["temporary_address_obtained"] is True
    assert "private-address" not in json.dumps(record, ensure_ascii=False)


def test_flv_stream_probe_records_valid_private_clip(monkeypatch):
    requested = []

    async def fake_call_stage(path, payload):
        requested.append(dict(payload))
        return ({"code": "200", "data": {"url": "https://example.test/live.flv"}},
                200, 20, "操作成功")

    async def fake_probe(address):
        assert address == "https://example.test/live.flv"
        return {
            "result": "SUCCESS", "duration_seconds": 8.0, "frame_rate": 15.0,
            "frame_count": 120, "codec_name": "h264", "byte_size": 1024,
            "content_sha256": "a" * 64,
            "media_retained": False, "failure_reason": None,
        }

    monkeypatch.setattr(validator, "EZVIZ_LIVE_PROTOCOL", 4)
    monkeypatch.setattr(validator, "EZVIZ_LIVE_QUALITY", 1)
    monkeypatch.setattr(validator, "call_stage", fake_call_stage)
    monkeypatch.setattr(validator, "probe_live_stream", fake_probe)

    record = asyncio.run(validator.validate_live_address(stream_probe=True))

    assert requested[0]["protocol"] == 4
    assert requested[0]["quality"] == 1
    assert record["result"] == "SUCCESS"
    assert record["selected_protocol"] == "flv"
    assert record["stream_probe_executed"] is True
    assert record["stream_probe"]["duration_seconds"] == 8.0
    assert record["stream_probe"]["codec_name"] == "h264"
    assert record["stream_probe"]["media_retained"] is False


def test_product_video_source_uses_configured_protocol_and_verify_code(monkeypatch):
    captured = {}

    async def fake_get_live_address(serial, channel, **kwargs):
        captured.update({"serial": serial, "channel": channel, **kwargs})
        return {"data": {"url": "https://example.test/live.flv"}}

    monkeypatch.setattr(device_module, "ENV_MODE", "live")
    monkeypatch.setattr(device_module, "EZVIZ_DEVICE_SERIAL", "test-device")
    monkeypatch.setattr(device_module, "EZVIZ_CHANNEL_NO", 1)
    monkeypatch.setattr(device_module, "EZVIZ_LIVE_PROTOCOL", 4)
    monkeypatch.setattr(device_module, "EZVIZ_LIVE_QUALITY", 1)
    monkeypatch.setattr(device_module, "EZVIZ_DEVICE_VERIFY_CODE", "private-code")
    monkeypatch.setattr(device_module.EzvizAPI, "get_live_address", fake_get_live_address)

    source = asyncio.run(device_module.DeviceAdapter().capture_video_source())

    assert captured == {
        "serial": "test-device", "channel": 1,
        "protocol": 4, "quality": 1, "code": "private-code",
    }
    assert str(source.temporary_url) == "https://example.test/live.flv"


def test_stream_probe_rejects_repeated_static_recording(monkeypatch, tmp_path):
    async def fake_run_once(run_index, stream_probe=False):
        assert stream_probe is True
        return {
            "schema_version": "1.0", "test_kind": "EZVIZ_LIVE_ACCEPTANCE",
            "generated_at": f"2026-08-20T19:00:0{run_index}+08:00",
            "run_index": run_index, "acceptance_mode": "STREAM_PROBE",
            "token_acquisition_mode": "APP_SECRET", "contains_credentials": False,
            "contains_permanent_public_url": False, "contains_temporary_url": False,
            "stages": [{
                "stage": "temporary_playback_address", "executed": True,
                "result": "SUCCESS", "business_code": "200", "online": None,
                "source_mode": "LIVE_DEVICE", "failure_reason": None,
                "stream_probe_executed": True,
                "stream_probe": {"result": "SUCCESS", "content_sha256": "a" * 64},
            }],
            "overall_result": "SUCCESS",
        }

    monkeypatch.setattr(validator, "run_once", fake_run_once)

    summary = asyncio.run(validator.run_many(
        2, interval_seconds=0, output_dir=tmp_path, stream_probe=True,
    ))

    assert summary["stream_probe_successes"] == 2
    assert summary["stream_unique_recordings"] == 1
    assert summary["stream_continuous"] is False
    assert summary["overall_result"] == "INCOMPLETE"


def test_stream_probe_does_not_require_snapshot(monkeypatch):
    async def fake_status():
        return {"stage": "device_status", "result": "SUCCESS"}

    async def fail_if_snapshot_called():
        raise AssertionError("stream probe must not depend on snapshot capture")

    async def fake_live_address(stream_probe=False):
        assert stream_probe is True
        return {"stage": "temporary_playback_address", "result": "SUCCESS"}

    monkeypatch.setattr(validator, "ENV_MODE", "live")
    monkeypatch.setattr(validator, "EZVIZ_DEVICE_SERIAL", "test-device")
    monkeypatch.setattr(validator, "validate_status", fake_status)
    monkeypatch.setattr(validator, "validate_snapshot", fail_if_snapshot_called)
    monkeypatch.setattr(validator, "validate_live_address", fake_live_address)

    report = asyncio.run(validator.run_once(1, stream_probe=True))

    assert [stage["stage"] for stage in report["stages"]] == [
        "device_status", "temporary_playback_address",
    ]
    assert report["overall_result"] == "SUCCESS"


def test_business_message_redacts_credentials_network_and_urls(monkeypatch):
    app_key = "appkey-1234567890abcdef"
    app_secret = "secret-1234567890abcdef"
    access_token = "token-1234567890abcdef"
    serial = "SERIAL-PRIVATE-1234"
    monkeypatch.setattr(validator, "EZVIZ_APP_KEY", app_key)
    monkeypatch.setattr(validator, "EZVIZ_APP_SECRET", app_secret)
    monkeypatch.setattr(validator, "EZVIZ_ACCESS_TOKEN", access_token)
    monkeypatch.setattr(validator, "EZVIZ_DEVICE_SERIAL", serial)
    payload = {
        "msg": (
            f"AppKey={app_key} appSecret={app_secret} accessToken={access_token} "
            f"deviceSerial={serial} url=https://192.168.1.20/live/index.m3u8 "
            "router=10.0.0.1 mac=AA:BB:CC:DD:EE:FF opaque=abcdefghijklmnopqrstu"
        )
    }

    message = validator.safe_business_message(payload)

    assert message is not None
    for value in (app_key, app_secret, access_token, serial, "192.168.1.20", "10.0.0.1",
                  "AA:BB:CC:DD:EE:FF", "https://"):
        assert value not in message
    assert "abcdefghijklmnopqrstu" not in message
    assert len(message) <= validator.MAX_BUSINESS_MESSAGE_LENGTH


def test_three_runs_are_retained_and_incomplete_exit_is_one(monkeypatch, tmp_path):
    async def fake_run_once(run_index):
        result = "FAILED" if run_index == 2 else "SUCCESS"
        return {
            "schema_version": "1.0",
            "test_kind": "EZVIZ_LIVE_ACCEPTANCE",
            "generated_at": f"2026-07-30T16:00:0{run_index}+08:00",
            "run_index": run_index,
            "token_acquisition_mode": "APP_SECRET",
            "contains_credentials": False,
            "contains_permanent_public_url": False,
            "stages": [{
                "stage": "device_status", "executed": True, "result": result,
                "business_code": "200", "online": result == "SUCCESS",
                "source_mode": "LIVE_DEVICE" if result == "SUCCESS" else "MOCK",
                "failure_reason": None if result == "SUCCESS" else "DEVICE_OFFLINE",
            }],
            "overall_result": result if result == "SUCCESS" else "INCOMPLETE",
        }

    monkeypatch.setattr(validator, "run_once", fake_run_once)
    summary = asyncio.run(validator.run_many(3, interval_seconds=0, output_dir=tmp_path))

    for run_index in range(1, 4):
        path = tmp_path / f"ezviz-live-validation-run-{run_index}.json"
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8"))["run_index"] == run_index
    assert json.loads((tmp_path / "ezviz-live-validation.json").read_text(encoding="utf-8"))["run_index"] == 3
    assert (tmp_path / "ezviz-live-validation-summary.json").exists()
    assert summary["runs"] == 3
    assert summary["successful_runs"] == 2
    assert summary["consistent"] is False
    assert summary["overall_result"] == "INCOMPLETE"
    assert validator.exit_code(summary) == 1
