import os
from pathlib import Path

TEST_DB = Path("test_risk_api.db")
os.environ["YINGMU_DB_PATH"] = str(TEST_DB)

from fastapi.testclient import TestClient
from backend.main import app


def observation(obs_id: str, feature: str, value: float, timestamp: str):
    return {"schema_version": "1.0", "observation_id": obs_id,
            "resident_id": "resident-mock-001", "timestamp": timestamp, "source": "pose",
            "feature_name": feature, "feature_value": value, "unit": "second",
            "location": "living_room", "confidence": .92, "data_quality": .88,
            "source_mode": "MOCK", "asset_id": "asset-mock-fall-001", "simulated": True,
            "metadata": {"model_version": "mock-v1"}}


def evidence(evi_id: str, obs_id: str, kind: str, timestamp: str):
    return {"schema_version": "1.0", "evidence_id": evi_id, "observation_ids": [obs_id],
            "resident_id": "resident-mock-001", "timestamp": timestamp, "risk_domain": "FALL",
            "evidence_type": kind, "severity": .78, "confidence": .92, "data_quality": .88,
            "baseline_value": 3.5, "current_value": 1.2, "baseline_deviation": -2.1,
            "time_scale": "SHORT", "location": "living_room", "explanation": kind,
            "adapter_version": "fall-adapter-v1", "source_mode": "MOCK", "simulated": True}


def setup_module():
    TEST_DB.unlink(missing_ok=True)


def teardown_module():
    import asyncio
    from backend.db.database import engine
    asyncio.run(engine.dispose())
    TEST_DB.unlink(missing_ok=True)


def test_complete_green_to_orange_and_idempotency():
    with TestClient(app) as client:
        t1, t2 = "2026-07-31T03:07:01+08:00", "2026-07-31T03:07:05+08:00"
        obs1 = observation("obs-mock-rapid-rise-001", "rise_duration", 1.2, t1)
        obs2 = observation("obs-mock-trunk-sway-001", "trunk_sway", 8.1, t2)
        assert client.post("/api/v1/observations", json=obs1).status_code == 201
        repeat = client.post("/api/v1/observations", json=obs1)
        assert repeat.status_code == 200 and repeat.json()["idempotent"] is True
        assert client.post("/api/v1/observations", json=obs2).status_code == 201

        green = client.post("/api/v1/evidence", json=evidence("evi-mock-rapid-rise-001",
                            "obs-mock-rapid-rise-001", "rapid_rise", t1))
        assert green.status_code == 201
        assert green.json()["evaluation"]["risk_level"] == "GREEN"
        assert green.json()["evaluation"]["event_created"] is False

        orange = client.post("/api/v1/evidence", json=evidence("evi-mock-trunk-sway-001",
                             "obs-mock-trunk-sway-001", "trunk_sway", t2))
        assert orange.status_code == 201
        assert orange.json()["evaluation"]["risk_level"] == "ORANGE"
        event_id = orange.json()["evaluation"]["event_id"]
        assert event_id == "event-mock-fall-001"

        repeated_eval = client.post("/api/v1/risk/evaluate", json={
            "resident_id": "resident-mock-001", "evaluated_at": t2})
        assert repeated_eval.status_code == 200
        assert repeated_eval.json()["event"]["event_id"] == event_id
        assert repeated_eval.json()["event_created"] is False

        detail = client.get(f"/api/v1/events/{event_id}")
        assert detail.status_code == 200
        assert len(detail.json()["evidence"]) == 2
        assert len(detail.json()["observations"]) == 2
        assert len(detail.json()["rule_traces"]) >= 2


def test_validation_and_missing_reference():
    with TestClient(app) as client:
        bad = observation("obs-bad", "rise_duration", 1.0, "2026-07-31T03:07:01")
        assert client.post("/api/v1/observations", json=bad).status_code == 422
        no_confidence = observation("obs-no-confidence", "rise_duration", 1.0,
                                    "2026-07-31T03:07:01+08:00")
        no_confidence.pop("confidence")
        assert client.post("/api/v1/observations", json=no_confidence).status_code == 400
        missing = evidence("evi-missing", "obs-does-not-exist", "rapid_rise",
                           "2026-07-31T03:07:01+08:00")
        assert client.post("/api/v1/evidence", json=missing).status_code == 409
        assert client.get("/api/v1/events/not-found").status_code == 404
