import asyncio
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from sqlalchemy import func, select


TEST_DB = Path("test_risk_api.db")
os.environ["YINGMU_DB_PATH"] = str(TEST_DB)
os.environ["YINGMU_ENV"] = "mock"
os.environ["YINGMU_CONTROL_TOKEN"] = "test-control-token"
os.environ["EZVIZ_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST"] = "false"
os.environ["MIN_EVIDENCE_QUALITY"] = "0.7"
os.environ["MIN_EVIDENCE_CONFIDENCE"] = "0.8"

from fastapi.testclient import TestClient

from backend.db.database import AsyncSessionLocal, engine
from backend.db.models import DeviceInfo, Evidence, InterventionResult, RiskAlarm, RiskEvent, RuleTrace
from backend.main import app
from contracts.v1.mock_memory_data import safe_history


def observation(
    resident_id: str,
    observation_id: str,
    feature_name: str,
    feature_value: float,
    timestamp: str,
    *,
    data_quality: float = 0.88,
):
    return {
        "schema_version": "1.0",
        "observation_id": observation_id,
        "resident_id": resident_id,
        "timestamp": timestamp,
        "source": "pose",
        "feature_name": feature_name,
        "feature_value": feature_value,
        "unit": "second",
        "location": "living_room",
        "confidence": 0.92,
        "data_quality": data_quality,
        "source_mode": "MOCK",
        "asset_id": "asset-mock-fall-001",
        "simulated": True,
        "metadata": {"model_version": "mock-v1"},
    }


def evidence(
    resident_id: str,
    evidence_id: str,
    observation_id: str,
    evidence_type: str,
    timestamp: str,
    *,
    data_quality: float = 0.88,
):
    return {
        "schema_version": "1.0",
        "evidence_id": evidence_id,
        "observation_ids": [observation_id],
        "resident_id": resident_id,
        "timestamp": timestamp,
        "risk_domain": "FALL",
        "evidence_type": evidence_type,
        "severity": 0.78,
        "confidence": 0.92,
        "data_quality": data_quality,
        "baseline_value": 5.0 if evidence_type == "trunk_sway" else 3.5,
        "current_value": 18.0 if evidence_type == "trunk_sway" else 1.2,
        "baseline_deviation": 2.8 if evidence_type == "trunk_sway" else -2.1,
        "time_scale": "SHORT",
        "location": "living_room",
        "explanation": evidence_type,
        "adapter_version": "fall-adapter-v1",
        "source_mode": "MOCK",
        "simulated": True,
    }


def post_pair(
    client: TestClient,
    resident_id: str,
    prefix: str,
    evidence_type: str,
    timestamp: str,
    *,
    data_quality: float = 0.88,
):
    observation_payload = observation(
        resident_id,
        f"obs-{prefix}",
        "sit_to_stand_duration" if evidence_type == "rapid_rise" else "trunk_sway_angle",
        1.2 if evidence_type == "rapid_rise" else 18.0,
        timestamp,
        data_quality=data_quality,
    )
    evidence_payload = evidence(
        resident_id,
        f"evi-{prefix}",
        observation_payload["observation_id"],
        evidence_type,
        timestamp,
        data_quality=data_quality,
    )
    observation_response = client.post("/api/v1/observations", json=observation_payload)
    evidence_response = client.post("/api/v1/evidence", json=evidence_payload)
    return observation_response, evidence_response, evidence_payload


def start_orange_event(client: TestClient, resident_id: str, prefix: str) -> str:
    post_pair(client, resident_id, f"{prefix}-rapid", "rapid_rise", "2026-07-31T03:07:01+08:00")
    _, response, _ = post_pair(client, resident_id, f"{prefix}-sway", "trunk_sway", "2026-07-31T03:07:05+08:00")
    assert response.status_code == 201
    assert response.json()["evaluation"]["matched_rule"] == "R-FALL-02"
    return response.json()["evaluation"]["event_id"]


def post_recovery(
    client: TestClient,
    resident_id: str,
    prefix: str,
    *,
    current_value: float = 15.0,
    data_quality: float = 0.90,
    confidence: float = 0.94,
    timestamp: str = "2026-07-31T03:07:29+08:00",
):
    observation_payload = observation(
        resident_id, f"obs-{prefix}", "stable_posture_duration", current_value, timestamp,
        data_quality=data_quality,
    )
    observation_payload["confidence"] = confidence
    evidence_payload = evidence(
        resident_id, f"evi-{prefix}", observation_payload["observation_id"], "posture_recovered", timestamp,
        data_quality=data_quality,
    )
    evidence_payload.update({
        "severity": 0.12,
        "confidence": confidence,
        "current_value": current_value,
        "baseline_value": None,
        "baseline_deviation": None,
        "explanation": "stable posture recovered",
    })
    assert client.post("/api/v1/observations", json=observation_payload).status_code == 201
    response = client.post("/api/v1/evidence", json=evidence_payload)
    return response, evidence_payload


async def resident_counts(resident_id: str):
    async with AsyncSessionLocal() as db:
        event_ids = list((await db.execute(
            select(RiskEvent.event_id).where(RiskEvent.resident_id == resident_id)
        )).scalars().all())
        event_count = len(event_ids)
        intervention_count = 0
        if event_ids:
            intervention_count = (await db.execute(
                select(func.count())
                .select_from(InterventionResult)
                .where(InterventionResult.event_id.in_(event_ids))
            )).scalar_one()
        return event_count, intervention_count


def setup_module():
    TEST_DB.unlink(missing_ok=True)


def teardown_module():
    asyncio.run(engine.dispose())
    TEST_DB.unlink(missing_ok=True)


def test_single_rapid_rise_stays_green_without_event_or_tool():
    resident_id = "resident-rapid-only"
    with TestClient(app) as client:
        _, response, _ = post_pair(
            client,
            resident_id,
            "rapid-only",
            "rapid_rise",
            "2026-07-31T03:07:01+08:00",
        )
        assert response.status_code == 201
        evaluation = response.json()["evaluation"]
        assert evaluation["risk_level"] == "GREEN"
        assert evaluation["event_created"] is False
        assert evaluation["matched_rule"] == "R-FALL-01"
        assert asyncio.run(resident_counts(resident_id)) == (0, 0)


def test_rapid_rise_and_trunk_sway_create_traceable_orange_event():
    resident_id = "resident-mock-001"
    with TestClient(app) as client:
        post_pair(
            client,
            resident_id,
            "mock-rapid-rise-001",
            "rapid_rise",
            "2026-07-31T03:07:01+08:00",
        )
        _, response, _ = post_pair(
            client,
            resident_id,
            "mock-trunk-sway-001",
            "trunk_sway",
            "2026-07-31T03:07:05+08:00",
        )
        evaluation = response.json()["evaluation"]
        assert evaluation == {
            "risk_level": "ORANGE",
            "event_created": True,
            "event_id": "event-mock-fall-001",
            "matched_rule": "R-FALL-02",
            "ruleset_version": "ruleset-v1.0",
            "system_evidence_id": None,
        }
        detail = client.get("/api/v1/events/event-mock-fall-001")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["event_id"] == "event-mock-fall-001"
        assert payload["status"] == "INTERVENING"
        assert payload["risk_score"] == 0.82
        assert payload["evidence_ids"] == [
            "evi-mock-rapid-rise-001",
            "evi-mock-trunk-sway-001",
        ]
        assert len(payload["evidences"]) == 2
        assert len(payload["observations"]) == 2
        assert len(payload["rule_traces"]) >= 2
        assert payload["interventions"] == []


def test_low_quality_trunk_sway_creates_system_evidence_without_orange():
    resident_id = "resident-low-quality"
    with TestClient(app) as client:
        post_pair(
            client,
            resident_id,
            "low-quality-rapid",
            "rapid_rise",
            "2026-07-31T03:07:01+08:00",
        )
        _, response, _ = post_pair(
            client,
            resident_id,
            "low-quality-sway",
            "trunk_sway",
            "2026-07-31T03:07:05+08:00",
            data_quality=0.69,
        )
        assert response.status_code == 201
        evaluation = response.json()["evaluation"]
        assert evaluation["risk_level"] == "GREEN"
        assert evaluation["event_created"] is False
        assert evaluation["matched_rule"] == "R-FALL-03"
        assert evaluation["system_evidence_id"] == "sys-quality-evi-low-quality-sway"
        assert asyncio.run(resident_counts(resident_id)) == (0, 0)

        async def quality_evidence_exists():
            async with AsyncSessionLocal() as db:
                row = (await db.execute(select(Evidence).where(
                    Evidence.evidence_id == "sys-quality-evi-low-quality-sway"
                ))).scalar_one_or_none()
                trace = (await db.execute(select(RuleTrace).where(
                    RuleTrace.evidence_id == "evi-low-quality-sway"
                ).order_by(RuleTrace.id.desc()))).scalars().first()
                return row, trace

        row, trace = asyncio.run(quality_evidence_exists())
        assert row is not None and row.risk_domain == "SYSTEM"
        assert row.evidence_type == "quality_gate_failed"
        assert trace is not None and trace.matched_rule == "R-FALL-03"


def test_duplicate_evidence_is_idempotent_without_new_event_or_tool():
    resident_id = "resident-duplicate"
    with TestClient(app) as client:
        post_pair(
            client,
            resident_id,
            "duplicate-rapid",
            "rapid_rise",
            "2026-07-31T03:07:01+08:00",
        )
        _, response, sway_payload = post_pair(
            client,
            resident_id,
            "duplicate-sway",
            "trunk_sway",
            "2026-07-31T03:07:05+08:00",
        )
        event_id = response.json()["evaluation"]["event_id"]
        before = asyncio.run(resident_counts(resident_id))
        duplicate = client.post("/api/v1/evidence", json=sway_payload)
        after = asyncio.run(resident_counts(resident_id))
        assert duplicate.status_code == 200
        payload = duplicate.json()
        assert payload["idempotent"] is True
        assert payload["evaluation"]["event_created"] is False
        assert payload["evaluation"]["event_id"] == event_id
        assert payload["evaluation"]["matched_rule"] == "R-SYSTEM-01"
        assert before == after == (1, 0)


def test_baseline_uses_only_safe_high_quality_samples():
    history = safe_history()
    rise_pairs = [
        (observation_payload, evidence_payload)
        for observation_payload, evidence_payload in zip(
            history["observations"], history["evidence"]
        )
        if evidence_payload["evidence_type"] == "rise_duration_baseline_sample"
    ]
    with TestClient(app) as client:
        for observation_payload, evidence_payload in rise_pairs:
            assert client.post(
                "/api/v1/observations", json=observation_payload
            ).status_code == 201
            assert client.post(
                "/api/v1/evidence", json=evidence_payload
            ).status_code == 201
        response = client.get(
            "/api/v1/residents/resident-mock-001/baseline",
            params={"as_of": "2026-07-25T12:00:00+08:00"},
        )
        assert response.status_code == 200
        baselines = response.json()["baselines"]
        assert baselines["rise_duration"]["median"] == 3.5
        assert baselines["rise_duration"]["distinct_days"] == 7
        assert baselines["rise_duration"]["status"] == "STABLE"
        assert "rapid_rise" not in baselines
        assert "trunk_sway" not in baselines


def test_validation_and_missing_reference():
    with TestClient(app) as client:
        invalid_time = observation(
            "resident-validation",
            "obs-bad-time",
            "sit_to_stand_duration",
            1.0,
            "2026-07-31T03:07:01",
        )
        assert client.post(
            "/api/v1/observations", json=invalid_time
        ).status_code == 422
        missing_confidence = observation(
            "resident-validation",
            "obs-no-confidence",
            "sit_to_stand_duration",
            1.0,
            "2026-07-31T03:07:01+08:00",
        )
        missing_confidence.pop("confidence")
        assert client.post(
            "/api/v1/observations", json=missing_confidence
        ).status_code == 422
        missing = evidence(
            "resident-validation",
            "evi-missing",
            "obs-does-not-exist",
            "rapid_rise",
            "2026-07-31T03:07:01+08:00",
        )
        assert client.post("/api/v1/evidence", json=missing).status_code == 409
        assert client.get("/api/v1/events/not-found").status_code == 404


def test_event_list_intervention_result_feedback_and_contract_validation():
    with TestClient(app) as client:
        event_id = "event-mock-fall-001"
        events = client.get("/api/v1/events", params={"resident_id": "resident-mock-001"})
        assert events.status_code == 200
        assert any(item["event_id"] == event_id for item in events.json())

        intervention = client.post(f"/api/v1/events/{event_id}/intervene")
        assert intervention.status_code == 200
        assert intervention.json()["tool_name"] == "mock_voice"
        assert intervention.json()["delivery_status"] == "SUCCESS"
        assert intervention.json()["source_mode"] == "MOCK"
        assert intervention.json()["simulated"] is True
        assert client.get(f"/api/v1/events/{event_id}").json()["status"] == "INTERVENING"

        feedback_payload = {"feedback_id": "result-family-feedback-001",
                            "feedback_type": "care", "value": "contacted", "operator": "family"}
        feedback = client.post(f"/api/v1/events/{event_id}/feedback", json=feedback_payload)
        assert feedback.status_code == 201
        repeated = client.post(f"/api/v1/events/{event_id}/feedback", json=feedback_payload)
        assert repeated.status_code == 200
        assert client.get(f"/api/v1/events/{event_id}").json()["status"] == "INTERVENING"

        wrong_name = evidence("resident-mock-001", "evi-invalid-name",
                              "obs-mock-rapid-rise-001", "fall_score",
                              "2026-07-31T03:07:01+08:00")
        invalid = client.post("/api/v1/evidence", json=wrong_name)
        assert invalid.status_code == 422


def test_recovery_requires_usable_evidence_and_fifteen_stable_seconds():
    with TestClient(app) as client:
        low_quality_event = start_orange_event(client, "resident-recovery-low-quality", "recovery-low-quality")
        low_quality, _ = post_recovery(
            client, "resident-recovery-low-quality", "recovery-low-quality", data_quality=0.69,
        )
        assert low_quality.status_code == 201
        assert low_quality.json()["evaluation"]["matched_rule"] == "R-FALL-03"
        assert client.get(f"/api/v1/events/{low_quality_event}").json()["status"] == "INTERVENING"

        short_event = start_orange_event(client, "resident-recovery-too-short", "recovery-too-short")
        short, _ = post_recovery(
            client, "resident-recovery-too-short", "recovery-too-short", current_value=14.9,
        )
        assert short.status_code == 201
        assert short.json()["evaluation"]["matched_rule"] == "R-FALL-02"
        assert client.get(f"/api/v1/events/{short_event}").json()["status"] == "INTERVENING"


def test_recovery_observation_resolves_and_updates_successful_intervention():
    resident_id = "resident-recovery-success"
    with TestClient(app) as client:
        event_id = start_orange_event(client, resident_id, "recovery-success")
        intervention = client.post(f"/api/v1/events/{event_id}/intervene")
        assert intervention.status_code == 200
        recovered, recovered_payload = post_recovery(client, resident_id, "recovery-success")
        assert recovered.status_code == 201
        assert recovered.json()["evaluation"]["matched_rule"] == "R-FALL-04"
        observing = client.get(f"/api/v1/events/{event_id}").json()
        assert observing["status"] == "OBSERVING"
        assert recovered_payload["evidence_id"] in observing["evidence_ids"]

        before_window = client.post("/api/v1/risk/evaluate", json={
            "resident_id": resident_id, "evaluated_at": "2026-07-31T03:08:28+08:00",
        })
        assert before_window.status_code == 200
        assert before_window.json()["matched_rule"] == "R-FALL-02"
        assert before_window.json()["risk_level"] == "ORANGE"

        resolved = client.post("/api/v1/risk/evaluate", json={
            "resident_id": resident_id, "evaluated_at": "2026-07-31T03:08:29+08:00",
        })
        assert resolved.status_code == 200
        assert resolved.json()["matched_rule"] == "R-FALL-05"
        assert resolved.json()["risk_level"] == "GREEN"
        detail = client.get(f"/api/v1/events/{event_id}").json()
        assert detail["status"] == "RESOLVED"
        assert len(detail["interventions"]) == 1
        assert detail["interventions"][0]["resolved"] is True
        assert detail["interventions"][0]["risk_after"] == 0.24
        transition = [item for item in detail["rule_traces"] if item["matched_rule"] == "R-FALL-05"][-1]
        assert transition["previous_status"] == "OBSERVING"
        assert transition["next_status"] == "RESOLVED"


def test_observing_danger_restarts_intervention_and_duplicate_recovery_is_idempotent():
    resident_id = "resident-recovery-danger"
    with TestClient(app) as client:
        event_id = start_orange_event(client, resident_id, "recovery-danger")
        assert client.post(f"/api/v1/events/{event_id}/intervene").status_code == 200
        recovered, recovered_payload = post_recovery(client, resident_id, "recovery-danger")
        assert recovered.json()["evaluation"]["matched_rule"] == "R-FALL-04"
        repeated = client.post("/api/v1/evidence", json=recovered_payload)
        assert repeated.status_code == 200
        assert repeated.json()["idempotent"] is True
        assert client.get(f"/api/v1/events/{event_id}").json()["status"] == "OBSERVING"

        _, danger, _ = post_pair(
            client, resident_id, "recovery-danger-new-sway", "trunk_sway", "2026-07-31T03:07:35+08:00",
        )
        assert danger.status_code == 201
        assert danger.json()["evaluation"]["matched_rule"] == "R-FALL-06"
        detail = client.get(f"/api/v1/events/{event_id}").json()
        assert detail["status"] == "INTERVENING"
        transition = [item for item in detail["rule_traces"] if item["matched_rule"] == "R-FALL-06"][-1]
        assert transition["previous_status"] == "OBSERVING"
        assert transition["next_status"] == "INTERVENING"
        late = client.post("/api/v1/risk/evaluate", json={
            "resident_id": resident_id, "evaluated_at": "2026-07-31T03:09:00+08:00",
        })
        assert late.json()["risk_level"] == "ORANGE"
        assert client.get(f"/api/v1/events/{event_id}").json()["status"] == "INTERVENING"


def test_external_result_cannot_mark_event_resolved():
    with TestClient(app) as client:
        event_id = start_orange_event(client, "resident-result-forbidden", "result-forbidden")
        response = client.post(f"/api/v1/events/{event_id}/results", json={
            "schema_version": "1.0", "result_id": "result-forbidden", "event_id": event_id,
            "started_at": "2026-07-31T03:07:06+08:00", "completed_at": "2026-07-31T03:07:06+08:00",
            "action_type": "voice", "tool_name": "mock_voice", "delivery_status": "SUCCESS",
            "resident_response": "stable", "family_feedback": None, "risk_after": 0.24,
            "resolved": True, "resolution_reason": "external bypass", "operator": "system",
            "source_mode": "MOCK", "simulated": True,
        })
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "RESULT_RESOLUTION_FORBIDDEN"


def test_frontend_assets_weekly_and_authorized_stop_contracts():
    with TestClient(app) as client:
        asset = {
            "asset_id": "asset-fall-authorized", "title": "授权事件片段",
            "source_mode": "RECORDED_REPLAY", "simulated": True,
            "stream_url": None, "fallback_url": None, "fallback_kind": "AUTHORIZED_CLIP",
            "available": False, "verification_status": "PENDING_ASSET",
            "captured_at": "2026-07-24T03:07:00+08:00",
            "notice": "当前演示包未附带视频文件。"
        }
        assert client.post("/api/v1/assets", json=asset).status_code == 201
        assert client.post("/api/v1/assets", json=asset).status_code == 200
        loaded = client.get("/api/v1/assets/asset-fall-authorized")
        assert loaded.status_code == 200
        assert loaded.json()["source_mode"] == "RECORDED_REPLAY"

        report = client.get("/api/v1/reports/weekly", params={"resident_id": "resident-mock-001"})
        assert report.status_code == 200
        assert report.json()["resident_id"] == "resident-mock-001"
        assert report.json()["risk_level"] in {"GREEN", "YELLOW", "ORANGE", "RED"}

        assert client.post("/api/v1/device/stop").status_code == 403
        stopped = client.post("/api/v1/device/stop",
                              headers={"X-Control-Token": "test-control-token"})
        assert stopped.status_code == 200
        assert stopped.json()["collection_active"] is False


def test_ezviz_alarm_webhook_verifies_signature_redacts_and_is_idempotent():
    device_serial = "test-ezviz-alarm-device"

    async def register_device():
        async with AsyncSessionLocal() as db:
            db.add(DeviceInfo(
                resident_id="resident-ezviz-alarm",
                device_sn=device_serial,
                channel_no=1,
                device_name="test-ezviz-device",
                adapter_mode="MOCK",
            ))
            await db.commit()

    async def persisted_alarm():
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(RiskAlarm).where(
                RiskAlarm.alarm_msg_id == "alarm-real-contract-001"
            ))).scalars().all()
            return len(rows), rows[0].raw_callback_json

    envelope = {
        "header": {
            "type": "ys.alarm",
            "deviceId": device_serial,
            "channelNo": 1,
            "messageId": "message-real-contract-001",
            "messageTime": int(time.time() * 1000),
        },
        "body": {
            "alarmId": "alarm-real-contract-001",
            "alarmTime": "2026-07-30T20:00:00",
            "alarmType": "alarmMove",
            "checksum": "device-password-must-not-persist",
            "pictureList": [{"id": "picture-id-only", "url": "https://private.example/image"}],
        },
    }
    raw_body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time() * 1000))
    signature = hmac.new(
        b"test-webhook-secret", raw_body + timestamp.encode("utf-8"), hashlib.sha1
    ).hexdigest()

    with TestClient(app) as client:
        asyncio.run(register_device())
        headers = {
            "content-type": "application/json",
            "t": timestamp,
            "signature": signature,
            "message_type": "ys.alarm",
        }
        response = client.post("/api/v1/webhooks/ezviz", content=raw_body, headers=headers)
        assert response.status_code == 200
        assert response.json() == {"messageId": "message-real-contract-001"}
        repeated = client.post("/api/v1/webhooks/ezviz", content=raw_body, headers=headers)
        assert repeated.status_code == 200
        assert repeated.json() == {"messageId": "message-real-contract-001"}
        count, saved = asyncio.run(persisted_alarm())
        assert count == 1
        assert "device-password-must-not-persist" not in saved
        assert "https://private.example/image" not in saved
        assert '\"checksum\":\"***\"' in saved
        assert '\"url\":\"***\"' in saved

        invalid = client.post(
            "/api/v1/webhooks/ezviz", content=raw_body,
            headers={**headers, "signature": "incorrect"},
        )
        assert invalid.status_code == 401
        assert invalid.json()["error"]["code"] == "EZVIZ_WEBHOOK_SIGNATURE_INVALID"


def test_ezviz_iot_webhook_is_adapted_to_raw_alarm():
    device_serial = "test-ezviz-iot-device"

    async def register_device():
        async with AsyncSessionLocal() as db:
            db.add(DeviceInfo(
                resident_id="resident-ezviz-iot",
                device_sn=device_serial,
                channel_no=1,
                device_name="test-ezviz-iot-device",
                adapter_mode="MOCK",
            ))
            await db.commit()

    async def persisted_alarm():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(RiskAlarm).where(
                RiskAlarm.alarm_msg_id == "iot-alarm-001"
            ))).scalar_one()

    envelope = {
        "header": {
            "type": "ys.iot", "deviceId": device_serial,
            "messageId": "iot-message-001", "messageTime": int(time.time() * 1000),
        },
        "body": {
            "deviceId": device_serial, "resourceType": "gb_alarm",
            "identifier": "motion_detected",
            "payload": json.dumps({
                "basic": {"UUID": "iot-alarm-001", "dateTime": "2026-08-08T17:22:56+08:00"},
                "intelligentTag": {"pictures": [{"id": "iot-picture-001", "url": "https://private.example/iot"}]},
                "serviceInfo": {},
            }),
        },
    }
    raw_body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time() * 1000))
    signature = hmac.new(
        b"test-webhook-secret", raw_body + timestamp.encode("utf-8"), hashlib.sha1
    ).hexdigest()

    with TestClient(app) as client:
        asyncio.run(register_device())
        response = client.post("/api/v1/webhooks/ezviz", content=raw_body, headers={
            "content-type": "application/json", "message_type": "ys.iot",
            "t": timestamp, "signature": signature,
        })
        assert response.status_code == 200
        assert response.json() == {"messageId": "iot-message-001"}
        alarm = asyncio.run(persisted_alarm())
        assert alarm.resident_id == "resident-ezviz-iot"
        assert alarm.alarm_type == "motion_detected"
        assert "https://private.example/iot" not in alarm.raw_callback_json


def test_all_frozen_routes_are_exposed_without_unfrozen_stream_route():
    routes = {(method, route.path) for route in app.routes
              for method in getattr(route, "methods", set())}
    expected = {
        ("POST", "/api/v1/observations"), ("POST", "/api/v1/evidence"),
        ("GET", "/api/v1/residents/{resident_id}/baseline"),
        ("POST", "/api/v1/risk/evaluate"), ("GET", "/api/v1/events"),
        ("GET", "/api/v1/events/{event_id}"),
        ("POST", "/api/v1/events/{event_id}/intervene"),
        ("POST", "/api/v1/events/{event_id}/results"),
        ("POST", "/api/v1/events/{event_id}/feedback"),
        ("GET", "/api/v1/reports/weekly"), ("GET", "/api/v1/device/status"),
        ("GET", "/api/v1/device/snapshot"), ("POST", "/api/v1/assets"),
        ("GET", "/api/v1/assets/{asset_id}"), ("POST", "/api/v1/device/stop"),
    }
    assert expected <= routes
    assert ("GET", "/api/v1/device/live-address") not in routes
