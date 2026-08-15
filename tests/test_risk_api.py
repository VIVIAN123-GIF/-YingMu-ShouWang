import asyncio
import os
from pathlib import Path

from sqlalchemy import func, select


TEST_DB = Path("test_risk_api.db")
os.environ["YINGMU_DB_PATH"] = str(TEST_DB)

from fastapi.testclient import TestClient

from backend.db.database import AsyncSessionLocal, engine
from backend.db.models import Evidence, InterventionResult, RiskEvent, RuleTrace
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
        assert payload["event"]["status"] == "INTERVENING"
        assert payload["event"]["risk_score"] == 0.82
        assert payload["event"]["evidence_ids"] == [
            "evi-mock-rapid-rise-001",
            "evi-mock-trunk-sway-001",
        ]
        assert len(payload["evidence"]) == 2
        assert len(payload["observations"]) == 2
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
