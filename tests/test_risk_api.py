import os
from pathlib import Path

TEST_DB = Path("test_risk_api.db")
os.environ["YINGMU_DB_PATH"] = str(TEST_DB)
os.environ["YINGMU_ENV"] = "mock"
os.environ["YINGMU_CONTROL_TOKEN"] = "test-control-token"

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
        assert detail.json()["event_id"] == event_id
        assert len(detail.json()["evidences"]) == 2
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

        feedback_payload = {"feedback_id": "result-family-feedback-001",
                            "feedback_type": "care", "value": "contacted", "operator": "family"}
        feedback = client.post(f"/api/v1/events/{event_id}/feedback", json=feedback_payload)
        assert feedback.status_code == 201
        repeated = client.post(f"/api/v1/events/{event_id}/feedback", json=feedback_payload)
        assert repeated.status_code == 200
        assert client.get(f"/api/v1/events/{event_id}").json()["status"] == "OBSERVING"

        wrong_name = evidence("evi-invalid-name", "obs-mock-rapid-rise-001", "fall_score",
                              "2026-07-31T03:07:01+08:00")
        invalid = client.post("/api/v1/evidence", json=wrong_name)
        assert invalid.status_code == 422


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
