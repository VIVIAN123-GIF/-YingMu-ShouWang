import asyncio
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import pytest
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
from backend.db.models import (AlarmProcessingTask, DeviceInfo, Evidence, InterventionResult,
                               RiskAlarm, RiskEvent, RuleTrace)
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
    angle_observation = observation(
        resident_id, f"obs-{prefix}-angle", "stable_trunk_angle_deg", 3.6, timestamp,
        data_quality=data_quality,
    )
    angle_observation["unit"] = "degree"
    angle_observation["confidence"] = confidence
    evidence_payload = evidence(
        resident_id, f"evi-{prefix}", observation_payload["observation_id"], "posture_recovered", timestamp,
        data_quality=data_quality,
    )
    evidence_payload.update({
        "severity": 0.0,
        "confidence": confidence,
        "current_value": current_value,
        "baseline_value": 15.0,
        "baseline_deviation": (current_value - 15.0) / 15.0,
        "observation_ids": [observation_payload["observation_id"], angle_observation["observation_id"]],
        "explanation": f"躯干最大偏角3.6度，连续稳定{current_value}秒，恢复阈值15秒",
    })
    assert client.post("/api/v1/observations", json=observation_payload).status_code == 201
    assert client.post("/api/v1/observations", json=angle_observation).status_code == 201
    response = client.post("/api/v1/evidence", json=evidence_payload)
    return response, evidence_payload


def recorded_asset(
    asset_id: str,
    *,
    device_ref: str = "device-ref-c6c-001",
    camera_position_id: str = "living-room-fixed-001",
    device_model: str = "EZVIZ_C6C",
    authorization_status: str = "AUTHORIZED",
    authorization_record_id: str | None = "auth-ref-001",
    retention_until: str | None = "2026-08-31T23:59:59+08:00",
):
    return {
        "asset_id": asset_id,
        "title": "脱敏C6c测试片段",
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "stream_url": None,
        "fallback_url": None,
        "fallback_kind": "LOCAL_AUTHORIZED_CLIP",
        "available": False,
        "verification_status": "VERIFIED",
        "captured_at": "2026-08-01T09:00:00+08:00",
        "notice": "测试仅保存脱敏资产引用",
        "device_ref": device_ref,
        "device_model": device_model,
        "camera_position_id": camera_position_id,
        "authorization_status": authorization_status,
        "authorization_record_id": authorization_record_id,
        "retention_until": retention_until,
    }


def recorded_observation(
    resident_id: str,
    observation_id: str,
    asset_id: str | None,
    timestamp: str,
    feature_name: str = "sit_to_stand_duration",
    feature_value: float = 3.2,
    *,
    data_quality: float = 0.90,
    simulated: bool = True,
):
    payload = observation(
        resident_id,
        observation_id,
        feature_name,
        feature_value,
        timestamp,
        data_quality=data_quality,
    )
    payload.update({
        "source_mode": "RECORDED_REPLAY",
        "simulated": simulated,
        "asset_id": asset_id,
        "unit": "frame_height_per_second" if feature_name == "relative_gait_speed" else (
            "degree" if feature_name == "stable_trunk_angle_deg" else "second"
        ),
    })
    return payload


def recorded_evidence(
    resident_id: str,
    evidence_id: str,
    observation_ids: list[str],
    timestamp: str,
    *,
    evidence_type: str = "normal_baseline_sample",
    current_value: float = 3.2,
    data_quality: float = 0.90,
    simulated: bool = True,
):
    return {
        "schema_version": "1.0",
        "evidence_id": evidence_id,
        "observation_ids": observation_ids,
        "resident_id": resident_id,
        "timestamp": timestamp,
        "risk_domain": "FALL",
        "evidence_type": evidence_type,
        "severity": 0.0,
        "confidence": 0.92,
        "data_quality": data_quality,
        "baseline_value": None,
        "current_value": current_value,
        "baseline_deviation": None,
        "time_scale": "LONG" if evidence_type == "normal_baseline_sample" else "SHORT",
        "location": "living_room",
        "explanation": "同机位授权C6c安全样本",
        "adapter_version": "baseline-adapter-v1",
        "source_mode": "RECORDED_REPLAY",
        "simulated": simulated,
    }


def post_baseline_day(
    client: TestClient,
    resident_id: str,
    asset_id: str,
    day: int,
    prefix: str,
    *,
    data_quality: float = 0.90,
):
    timestamp = f"2026-08-{day:02d}T09:00:00+08:00"
    metrics = {
        "sit_to_stand_duration": 3.0 + day / 10,
        "relative_gait_speed": 0.42 + day / 100,
        "stable_trunk_angle_deg": 3.5 + day / 10,
    }
    for feature_name, value in metrics.items():
        suffix = feature_name.replace("_", "-")
        observation_id = f"obs-{prefix}-{day}-{suffix}"
        evidence_id = f"evi-{prefix}-{day}-{suffix}"
        observation_response = client.post("/api/v1/observations", json=recorded_observation(
            resident_id, observation_id, asset_id, timestamp, feature_name, value,
            data_quality=data_quality,
        ))
        assert observation_response.status_code == 201
        evidence_response = client.post("/api/v1/evidence", json=recorded_evidence(
            resident_id, evidence_id, [observation_id], timestamp,
            current_value=value, data_quality=data_quality,
        ))
        assert evidence_response.status_code == 201


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
        assert payload["risk_score"] == 0.78
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


def test_public_mock_history_cannot_be_presented_as_personal_device_baseline():
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
        assert baselines["rise_duration"]["median"] is None
        assert baselines["rise_duration"]["distinct_days"] == 0
        assert baselines["rise_duration"]["status"] == "INSUFFICIENT"
        assert response.json()["overall_status"] == "INSUFFICIENT"
        assert "rapid_rise" not in baselines
        assert "trunk_sway" not in baselines


def test_same_authorized_c6c_position_three_dates_forms_provisional_baseline():
    resident_id = "resident-baseline-provisional"
    asset_id = "asset-baseline-provisional"
    with TestClient(app) as client:
        assert client.post("/api/v1/assets", json=recorded_asset(asset_id)).status_code == 201
        for day in (1, 2, 3):
            post_baseline_day(client, resident_id, asset_id, day, "baseline-provisional")
        response = client.get(
            f"/api/v1/residents/{resident_id}/baseline",
            params={"as_of": "2026-08-04T09:00:00+08:00"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["overall_status"] == "PROVISIONAL"
        assert payload["baseline_progress"]["observed_days"] == 3
        assert payload["provenance"] == {
            "device_ref": "device-ref-c6c-001",
            "device_model": "EZVIZ_C6C",
            "camera_position_id": "living-room-fixed-001",
        }
        assert set(payload["baselines"]) == {
            "rise_duration", "relative_gait_speed", "stable_trunk_angle_deg",
        }
        assert all(item["status"] == "PROVISIONAL" for item in payload["baselines"].values())
        assert payload["baselines"]["relative_gait_speed"]["median"] == pytest.approx(0.44)


def test_baseline_never_mixes_camera_positions():
    resident_id = "resident-baseline-mixed-camera"
    asset_a = "asset-baseline-camera-a"
    asset_b = "asset-baseline-camera-b"
    with TestClient(app) as client:
        assert client.post("/api/v1/assets", json=recorded_asset(
            asset_a, camera_position_id="position-a",
        )).status_code == 201
        assert client.post("/api/v1/assets", json=recorded_asset(
            asset_b, camera_position_id="position-b",
        )).status_code == 201
        post_baseline_day(client, resident_id, asset_a, 1, "mixed-camera-a")
        post_baseline_day(client, resident_id, asset_a, 2, "mixed-camera-a")
        post_baseline_day(client, resident_id, asset_b, 3, "mixed-camera-b")
        payload = client.get(
            f"/api/v1/residents/{resident_id}/baseline",
            params={"as_of": "2026-08-04T09:00:00+08:00"},
        ).json()
        assert payload["overall_status"] == "INSUFFICIENT"
        assert payload["baseline_progress"]["observed_days"] == 2
        assert payload["provenance"]["camera_position_id"] == "position-a"
        assert all(item["distinct_days"] == 2 for item in payload["baselines"].values())


def test_low_quality_and_orange_period_samples_cannot_form_baseline():
    resident_id = "resident-baseline-pollution"
    asset_id = "asset-baseline-pollution"
    with TestClient(app) as client:
        assert client.post("/api/v1/assets", json=recorded_asset(asset_id)).status_code == 201
        for day in (1, 2, 3):
            post_baseline_day(
                client, resident_id, asset_id, day, "baseline-low-quality", data_quality=0.69,
            )
        low_quality = client.get(
            f"/api/v1/residents/{resident_id}/baseline",
            params={"as_of": "2026-08-04T09:00:00+08:00"},
        ).json()
        assert low_quality["overall_status"] == "INSUFFICIENT"
        assert low_quality["baseline_progress"]["observed_days"] == 0

        blocked_resident = "resident-baseline-orange-period"
        start_orange_event(client, blocked_resident, "baseline-orange-period")
        for day in (1, 2, 3):
            post_baseline_day(client, blocked_resident, asset_id, day, "baseline-orange-period")
        blocked = client.get(
            f"/api/v1/residents/{blocked_resident}/baseline",
            params={"as_of": "2026-08-04T09:00:00+08:00"},
        ).json()
        assert blocked["overall_status"] == "INSUFFICIENT"
        assert blocked["baseline_progress"]["observed_days"] == 0


def test_dynamic_score_and_trace_are_identical_in_db_log_and_event_api(caplog):
    caplog.set_level("INFO", logger="risk_rule")

    def create_scored_event(client: TestClient, resident_id: str, prefix: str, severity: float):
        timestamp_rapid = "2026-07-31T12:30:01+08:00"
        timestamp_sway = "2026-07-31T12:30:05+08:00"
        rapid_observation = observation(
            resident_id, f"obs-{prefix}-rapid", "sit_to_stand_duration", 1.2, timestamp_rapid,
        )
        sway_observation = observation(
            resident_id, f"obs-{prefix}-sway", "trunk_sway_angle", 18.0, timestamp_sway,
        )
        rapid_evidence = evidence(
            resident_id, f"evi-{prefix}-rapid", rapid_observation["observation_id"],
            "rapid_rise", timestamp_rapid,
        )
        sway_evidence = evidence(
            resident_id, f"evi-{prefix}-sway", sway_observation["observation_id"],
            "trunk_sway", timestamp_sway,
        )
        rapid_evidence["severity"] = severity
        sway_evidence["severity"] = severity
        assert client.post("/api/v1/observations", json=rapid_observation).status_code == 201
        assert client.post("/api/v1/evidence", json=rapid_evidence).status_code == 201
        assert client.post("/api/v1/observations", json=sway_observation).status_code == 201
        response = client.post("/api/v1/evidence", json=sway_evidence)
        assert response.status_code == 201
        return response.json()["evaluation"]["event_id"], sway_evidence["evidence_id"]

    async def persisted_trace(evidence_id: str):
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(RuleTrace)
                .where(RuleTrace.evidence_id == evidence_id)
                .order_by(RuleTrace.id.desc())
            )).scalars().first()
            return json.loads(row.trace_payload)

    with TestClient(app) as client:
        low_event, _ = create_scored_event(
            client, "resident-score-low", "score-low", 0.55,
        )
        high_event, high_evidence_id = create_scored_event(
            client, "resident-score-high", "score-high", 0.95,
        )
        low_detail = client.get(f"/api/v1/events/{low_event}").json()
        high_detail = client.get(f"/api/v1/events/{high_event}").json()
        assert low_detail["risk_score"] != high_detail["risk_score"]
        assert high_detail["risk_score"] > low_detail["risk_score"]
        assert high_detail["risk_score"] != 0.82

        api_trace = next(
            item for item in high_detail["rule_traces"]
            if item["evidence_id"] == high_evidence_id and item["matched_rule"] == "R-FALL-02"
        )
        db_trace = asyncio.run(persisted_trace(high_evidence_id))
        log_trace = next(
            json.loads(record.message) for record in reversed(caplog.records)
            if record.name == "risk_rule"
            and json.loads(record.message).get("evidence_id") == high_evidence_id
        )
        assert api_trace == db_trace == log_trace
        assert api_trace["thresholds"]["data_quality"] == 0.70
        assert api_trace["quality_snapshot"]
        assert api_trace["baseline_snapshot"]["overall_status"] == "INSUFFICIENT"
        assert api_trace["score_components"]["final_score"] == high_detail["risk_score"]


def test_baseline_endpoint_returns_pre_fall_summary():
    resident_id = "resident-prefall-summary"
    with TestClient(app) as client:
        post_pair(
            client,
            resident_id,
            "prefall-rapid",
            "rapid_rise",
            "2026-07-31T03:07:01+08:00",
        )
        post_pair(
            client,
            resident_id,
            "prefall-sway",
            "trunk_sway",
            "2026-07-31T03:07:05+08:00",
        )
        response = client.get(
            f"/api/v1/residents/{resident_id}/baseline",
            params={"as_of": "2026-07-31T03:07:05+08:00"},
        )
        assert response.status_code == 200
        summary = response.json()["pre_fall_summary"]
        assert summary["risk_level"] == "ORANGE"
        assert summary["instant_risk"] >= 0.7
        assert summary["risk_30s"] >= 0.7
        assert summary["trend_3min"] >= 0.7
        assert "personal_baseline_deviation" in summary["dominant_factors"]
        assert summary["recommended_intervention"] == "执行低打扰语音或灯光提醒，并进入恢复观察。"


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


@pytest.mark.parametrize(
    ("case", "asset_changes", "observation_asset_id", "expected_code"),
    [
        ("asset-required", None, None, "ASSET_REQUIRED"),
        ("asset-not-found", None, "asset-gate-missing", "ASSET_NOT_FOUND"),
        ("non-c6c", {"device_model": "OTHER_CAMERA"}, "asset-gate-non-c6c", "ASSET_DEVICE_MISMATCH"),
        (
            "unauthorized",
            {"authorization_status": "PENDING", "authorization_record_id": None},
            "asset-gate-unauthorized",
            "ASSET_NOT_AUTHORIZED",
        ),
        (
            "expired",
            {"retention_until": "2026-07-31T23:59:59+08:00"},
            "asset-gate-expired",
            "ASSET_AUTHORIZATION_EXPIRED",
        ),
        (
            "retention-required",
            {"retention_until": None},
            "asset-gate-retention-required",
            "ASSET_RETENTION_REQUIRED",
        ),
        (
            "asset-source-mismatch",
            {"source_mode": "MOCK"},
            "asset-gate-asset-source-mismatch",
            "ASSET_SOURCE_MISMATCH",
        ),
    ],
)
def test_recorded_fall_asset_gate_rejects_untraceable_inputs(
    case, asset_changes, observation_asset_id, expected_code,
):
    resident_id = f"resident-gate-{case}"
    timestamp = "2026-08-01T10:00:00+08:00"
    with TestClient(app) as client:
        if asset_changes is not None:
            asset_payload = recorded_asset(observation_asset_id)
            asset_payload.update(asset_changes)
            assert client.post("/api/v1/assets", json=asset_payload).status_code == 201
        observation_id = f"obs-gate-{case}"
        assert client.post("/api/v1/observations", json=recorded_observation(
            resident_id, observation_id, observation_asset_id, timestamp,
        )).status_code == 201
        response = client.post("/api/v1/evidence", json=recorded_evidence(
            resident_id,
            f"evi-gate-{case}",
            [observation_id],
            timestamp,
            evidence_type="rapid_rise",
            current_value=1.2,
        ))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == expected_code


def test_recorded_fall_gate_rejects_resident_and_source_mismatches():
    timestamp = "2026-08-01T10:10:00+08:00"
    with TestClient(app) as client:
        asset_id = "asset-gate-contract-mismatch"
        assert client.post("/api/v1/assets", json=recorded_asset(asset_id)).status_code == 201

        resident_observation = recorded_observation(
            "resident-gate-owner", "obs-gate-resident", asset_id, timestamp,
        )
        assert client.post("/api/v1/observations", json=resident_observation).status_code == 201
        wrong_resident = recorded_evidence(
            "resident-gate-other", "evi-gate-resident", ["obs-gate-resident"], timestamp,
            evidence_type="rapid_rise", current_value=1.2,
        )
        response = client.post("/api/v1/evidence", json=wrong_resident)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "RESIDENT_MISMATCH"

        source_observation = recorded_observation(
            "resident-gate-source", "obs-gate-source", asset_id, timestamp,
        )
        assert client.post("/api/v1/observations", json=source_observation).status_code == 201
        wrong_source = recorded_evidence(
            "resident-gate-source", "evi-gate-source", ["obs-gate-source"], timestamp,
            evidence_type="rapid_rise", current_value=1.2, simulated=False,
        )
        response = client.post("/api/v1/evidence", json=wrong_source)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SOURCE_MISMATCH"


def test_recorded_recovery_accepts_two_observations_on_one_authorized_asset_and_rejects_old_angle_payload():
    resident_id = "resident-recorded-recovery-semantics"
    timestamp = "2026-08-01T10:20:00+08:00"
    asset_id = "asset-recorded-recovery-semantics"
    with TestClient(app) as client:
        assert client.post("/api/v1/assets", json=recorded_asset(asset_id)).status_code == 201
        duration = recorded_observation(
            resident_id, "obs-recorded-duration", asset_id, timestamp,
            "stable_posture_duration", 15.0,
        )
        angle = recorded_observation(
            resident_id, "obs-recorded-angle", asset_id, timestamp,
            "stable_trunk_angle_deg", 3.613,
        )
        assert client.post("/api/v1/observations", json=duration).status_code == 201
        assert client.post("/api/v1/observations", json=angle).status_code == 201

        old_payload = recorded_evidence(
            resident_id, "evi-old-angle-semantics", [angle["observation_id"]], timestamp,
            evidence_type="posture_recovered", current_value=3.613,
        )
        old_payload.update({"baseline_value": 15.0, "baseline_deviation": (3.613 - 15) / 15})
        rejected = client.post("/api/v1/evidence", json=old_payload)
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "EVIDENCE_SEMANTICS_INVALID"

        valid_payload = recorded_evidence(
            resident_id,
            "evi-recorded-recovery-valid",
            [duration["observation_id"], angle["observation_id"]],
            timestamp,
            evidence_type="posture_recovered",
            current_value=15.0,
        )
        valid_payload.update({
            "baseline_value": 15.0,
            "baseline_deviation": 0.0,
            "explanation": "最大稳定躯干角度3.613度，连续稳定15秒，达到15秒阈值",
        })
        accepted = client.post("/api/v1/evidence", json=valid_payload)
        assert accepted.status_code == 201


def test_quality_boundary_at_point_seven_allows_combo_upgrade():
    resident_id = "resident-quality-boundary-pass"
    with TestClient(app) as client:
        post_pair(
            client, resident_id, "quality-pass-rapid", "rapid_rise",
            "2026-07-31T12:00:01+08:00", data_quality=0.70,
        )
        _, response, _ = post_pair(
            client, resident_id, "quality-pass-sway", "trunk_sway",
            "2026-07-31T12:00:05+08:00", data_quality=0.70,
        )
        assert response.status_code == 201
        assert response.json()["evaluation"]["matched_rule"] == "R-FALL-02"
        assert response.json()["evaluation"]["risk_level"] == "ORANGE"


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
        assert short.json()["evaluation"]["matched_rule"] == "NO_MATCH"
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
        assert before_window.json()["matched_rule"] == "NO_MATCH"
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
            tasks = (await db.execute(select(AlarmProcessingTask).where(
                AlarmProcessingTask.alarm_msg_id == "alarm-real-contract-001"
            ))).scalars().all()
            return len(rows), rows[0].raw_callback_json, tasks

    async def process_queued_alarm():
        from backend.service.alarm_task_service import claim_next_task, process_claimed_task

        async def fake_capture():
            return {"asset_id": "asset-mock-snapshot-001"}

        async with AsyncSessionLocal() as db:
            task = await claim_next_task(db)
            assert task is not None
            assert task.alarm_msg_id == "alarm-real-contract-001"
            return await process_claimed_task(db, task, capture_snapshot=fake_capture)

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
        count, saved, tasks = asyncio.run(persisted_alarm())
        assert count == 1
        assert len(tasks) == 1
        assert tasks[0].status == "PENDING"
        processing = client.get("/api/v1/alarms/processing", params={"resident_id": "resident-ezviz-alarm"})
        assert processing.status_code == 200
        task_payload = processing.json()[0]
        assert task_payload["task_id"].startswith("alarm-task-")
        assert task_payload["status"] == "PENDING"
        assert "device_sn" not in task_payload
        assert "alarm_msg_id" not in task_payload
        assert "device-password-must-not-persist" not in saved
        assert "https://private.example/image" not in saved
        assert '\"checksum\":\"***\"' in saved
        assert '\"url\":\"***\"' in saved

        processed = asyncio.run(process_queued_alarm())
        assert processed.status == "WAITING_ALGORITHM"
        assert processed.capture_asset_id == "asset-mock-snapshot-001"

        invalid = client.post(
            "/api/v1/webhooks/ezviz", content=raw_body,
            headers={**headers, "signature": "incorrect"},
        )
        assert invalid.status_code == 401
        error = invalid.json()["error"]
        assert error["code"] == "EZVIZ_WEBHOOK_SIGNATURE_INVALID"
        assert error["debug"] == {
            "path": "/api/v1/webhooks/ezviz",
            "content_type": "application/json",
            "message_type_header": "ys.alarm",
            "signature_present": True,
            "timestamp_present": True,
            "body_bytes": len(raw_body),
            "json_valid": True,
            "top_level_keys": ["body", "header"],
            "header_keys": ["channelNo", "deviceId", "messageId", "messageTime", "type"],
            "body_keys": ["alarmId", "alarmTime", "alarmType", "checksum", "pictureList"],
            "payload_kind": "none",
        }
        assert "device-password-must-not-persist" not in json.dumps(error)
        assert "https://private.example/image" not in json.dumps(error)


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


def test_ezviz_console_test_message_is_acknowledged_without_creating_an_alarm():
    """The console's ys.test.msg verifies transport, not a physical alarm."""
    envelope = {
        "body": "console test",
        "header": {
            "channelNo": 0,
            "deviceId": "not-a-real-device",
            "messageId": "console-test-message-001",
            "messageTime": int(time.time() * 1000),
            "type": "ys.test.msg",
        },
    }
    raw_body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time() * 1000))
    signature = hmac.new(
        b"test-webhook-secret", raw_body + timestamp.encode("utf-8"), hashlib.sha1
    ).hexdigest()

    async def alarm_count():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(func.count()).select_from(RiskAlarm))).scalar_one()

    with TestClient(app) as client:
        before = asyncio.run(alarm_count())
        response = client.post("/api/v1/webhooks/ezviz", content=raw_body, headers={
            "content-type": "application/json", "message_type": "ys.test.msg",
            "t": timestamp, "signature": signature,
        })
        assert response.status_code == 200
        assert response.json() == {"messageId": "console-test-message-001"}
        assert asyncio.run(alarm_count()) == before


def test_ezviz_shadow_change_is_acknowledged_without_creating_an_alarm():
    """Device state synchronization must not be treated as a risk alarm."""
    envelope = {
        "header": {
            "channelNo": 1,
            "deviceId": "not-a-real-device",
            "messageId": "shadow-change-message-001",
            "messageTime": int(time.time() * 1000),
            "type": "ys.shadow.change",
        },
        "body": {
            "attribute": "onlineStatus",
            "deviceSerial": "not-a-real-device",
            "domainId": "basic",
            "localIndex": "0",
            "resourceType": "device",
            "statusValue": "1",
        },
    }
    raw_body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time() * 1000))
    signature = hmac.new(
        b"test-webhook-secret", raw_body + timestamp.encode("utf-8"), hashlib.sha1
    ).hexdigest()

    async def alarm_count():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(func.count()).select_from(RiskAlarm))).scalar_one()

    with TestClient(app) as client:
        before = asyncio.run(alarm_count())
        response = client.post("/api/v1/webhooks/ezviz", content=raw_body, headers={
            "content-type": "application/json", "message_type": "ys.shadow.change",
            "t": timestamp, "signature": signature,
        })
        assert response.status_code == 200
        assert response.json() == {"messageId": "shadow-change-message-001"}
        assert asyncio.run(alarm_count()) == before


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
