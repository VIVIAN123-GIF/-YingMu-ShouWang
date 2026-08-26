import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from adapters.trajectory_adapter import (
    distance_to_zone,
    point_in_polygon,
    segments_intersect,
    trajectory_intersects_zone,
)
from backend.db import init_db
from backend.db.database import Base
from backend.db.models import Evidence, Observation
from backend.main import app
from backend.service.baseline_service import EXPECTED_METRICS, memory_store
from backend.service.forewarning_service import (
    _mad_deviation,
    evaluate_forewarning,
    legacy_pre_fall_summary,
)
from backend.service.risk_service import evaluate as evaluate_risk
from backend.service.serialization import dumps
from contracts.v1.forewarning import ForewarningSnapshot, SceneCalibration, SceneZone
from contracts.v1.ruleset import load_forewarning_ruleset, load_ruleset


CN = timezone(timedelta(hours=8))


async def with_database(tmp_path, operation):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'forewarning-v13.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as db:
            return await operation(db)
    finally:
        await engine.dispose()


def observation_row(
    observation_id: str,
    timestamp: datetime,
    feature_name: str,
    value: float,
    *,
    source_mode: str,
    simulated: bool,
):
    return Observation(
        schema_version="1.0",
        observation_id=observation_id,
        resident_id="resident-source-isolation",
        timestamp=timestamp,
        source="trajectory_adapter" if feature_name in {
            "danger_zone_dwell_s", "trajectory_intersects_obstacle",
        } else "pose",
        feature_name=feature_name,
        feature_value=dumps(value),
        unit="ratio",
        location="living_room",
        confidence=0.9,
        data_quality=0.9,
        source_mode=source_mode,
        asset_id=f"asset-{source_mode.lower()}",
        simulated=simulated,
        extra_metadata=dumps({"scene_config_id": "scene-test-v1"}),
        device_sn=None,
    )


def evidence_row(
    evidence_id: str,
    observation_id: str,
    timestamp: datetime,
    evidence_type: str,
    severity: float,
    *,
    source_mode: str,
    simulated: bool,
    risk_domain: str = "FALL",
):
    return Evidence(
        schema_version="1.0",
        evidence_id=evidence_id,
        observation_ids=dumps([observation_id]),
        resident_id="resident-source-isolation",
        timestamp=timestamp,
        risk_domain=risk_domain,
        evidence_type=evidence_type,
        severity=severity,
        confidence=0.9,
        data_quality=0.9,
        baseline_value=None,
        current_value=severity,
        baseline_deviation=None,
        time_scale="SHORT",
        location="living_room",
        explanation="v1.3 isolation test evidence",
        adapter_version="test-v1",
        source_mode=source_mode,
        simulated=simulated,
    )


def test_forewarning_ruleset_is_independent_from_event_ruleset():
    assert load_ruleset().version == "ruleset-v1.2"
    forewarning = load_forewarning_ruleset()
    assert forewarning.version == "ruleset-v1.3-min"
    assert forewarning.windows["instant_seconds"] == 8
    assert sum(forewarning.forewarning_weights["STABLE"].values()) == pytest.approx(1.0)
    assert forewarning.forewarning_weights["INSUFFICIENT"] == {
        "human_risk": 0.75,
        "personal_deviation": 0.0,
        "environment_risk": 0.10,
        "interaction_risk": 0.15,
    }


def test_core_baseline_metrics_and_mad_deviation_match_approved_plan():
    assert EXPECTED_METRICS == ("rise_duration", "trunk_sway", "relative_gait_speed")
    assert _mad_deviation(current=105.0, center=100.0, mad=1.0) == pytest.approx(0.5)
    assert _mad_deviation(current=110.0, center=100.0, mad=1.0) == pytest.approx(1.0)


def test_forewarning_isolates_source_tracks_and_requires_instant_environment_window(
    monkeypatch, tmp_path,
):
    evaluated_at = datetime(2026, 8, 26, 14, 0, tzinfo=CN)
    recent = evaluated_at - timedelta(seconds=2)
    old = evaluated_at - timedelta(seconds=9)

    async def baseline(*_args, **_kwargs):
        return {"overall_status": "INSUFFICIENT", "baselines": {}}

    monkeypatch.setattr(memory_store, "baseline", baseline)

    async def operation(db):
        rows = [
            observation_row("obs-replay-human", recent, "trunk_sway_angle_deg", 18.0, source_mode="RECORDED_REPLAY", simulated=True),
            evidence_row("evi-replay-human", "obs-replay-human", recent, "trunk_sway", 0.8, source_mode="RECORDED_REPLAY", simulated=True),
            observation_row("obs-replay-light", recent, "illumination_norm", 0.1, source_mode="RECORDED_REPLAY", simulated=True),
            evidence_row("evi-replay-light", "obs-replay-light", recent, "low_illumination", 0.4, source_mode="RECORDED_REPLAY", simulated=True, risk_domain="SYSTEM"),
            observation_row("obs-replay-old-light", old, "illumination_norm", 0.05, source_mode="RECORDED_REPLAY", simulated=True),
            evidence_row("evi-replay-old-light", "obs-replay-old-light", old, "low_illumination", 1.0, source_mode="RECORDED_REPLAY", simulated=True, risk_domain="SYSTEM"),
            observation_row("obs-replay-zone", recent, "danger_zone_dwell_s", 1.2, source_mode="RECORDED_REPLAY", simulated=True),
            evidence_row("evi-replay-zone", "obs-replay-zone", recent, "high_risk_zone_entry", 0.6, source_mode="RECORDED_REPLAY", simulated=True, risk_domain="SYSTEM"),
            observation_row("obs-replay-old-zone", old, "danger_zone_dwell_s", 2.0, source_mode="RECORDED_REPLAY", simulated=True),
            evidence_row("evi-replay-old-zone", "obs-replay-old-zone", old, "high_risk_zone_entry", 1.0, source_mode="RECORDED_REPLAY", simulated=True, risk_domain="SYSTEM"),
            observation_row("obs-live-human", recent, "trunk_sway_angle_deg", 13.0, source_mode="LIVE_DEVICE", simulated=False),
            evidence_row("evi-live-human", "obs-live-human", recent, "trunk_sway", 0.2, source_mode="LIVE_DEVICE", simulated=False),
        ]
        db.add_all(rows)
        await db.commit()
        replay = await evaluate_forewarning(
            db,
            "resident-source-isolation",
            evaluated_at,
            source_mode="RECORDED_REPLAY",
            simulated=True,
        )
        live = await evaluate_forewarning(
            db,
            "resident-source-isolation",
            evaluated_at,
            source_mode="LIVE_DEVICE",
            simulated=False,
        )
        return replay, live

    replay, live = asyncio.run(with_database(tmp_path, operation))
    assert replay.source_mode.value == "RECORDED_REPLAY"
    assert replay.simulated is True
    assert "evi-live-human" not in replay.evidence_ids
    assert replay.components.human_risk == pytest.approx(0.8)
    assert replay.components.environment_risk == pytest.approx(0.4)
    assert replay.components.interaction_risk == pytest.approx(0.6)
    assert live.source_mode.value == "LIVE_DEVICE"
    assert live.simulated is False
    assert live.evidence_ids == ["evi-live-human"]
    assert live.components.human_risk == pytest.approx(0.2)
    assert live.components.environment_risk == 0.0
    assert live.components.interaction_risk == 0.0


def test_scene_contract_and_geometry_are_normalized_and_deterministic():
    zone = SceneZone(
        zone_id="zone-a", zone_type="HIGH_RISK",
        polygon_norm=[(0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)],
    )
    assert point_in_polygon((0.3, 0.3), zone.polygon_norm)
    assert not point_in_polygon((0.7, 0.3), zone.polygon_norm)
    assert distance_to_zone((0.3, 0.3), zone) == 0
    assert distance_to_zone((0.7, 0.3), zone) == pytest.approx(0.2)
    with pytest.raises(ValueError):
        SceneZone(zone_id="bad", zone_type="SAFE", polygon_norm=[(0, 0), (2, 0), (0, 1)])


def test_obstacle_intersection_detects_crossing_and_boundary_contact_between_frames():
    zone = SceneZone(
        zone_id="obstacle-a",
        zone_type="OBSTACLE",
        polygon_norm=[(0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)],
    )
    assert segments_intersect((0.2, 0.5), (0.8, 0.5), (0.4, 0.4), (0.4, 0.6))
    assert segments_intersect((0.2, 0.4), (0.8, 0.4), (0.4, 0.4), (0.6, 0.4))
    assert not segments_intersect((0.1, 0.1), (0.2, 0.2), (0.4, 0.4), (0.6, 0.4))
    assert trajectory_intersects_zone(
        [(0.0, 0.2, 0.5, 0.9), (0.2, 0.8, 0.5, 0.9)],
        zone,
    )
    assert not trajectory_intersects_zone(
        [(0.0, 0.1, 0.1, 0.9), (0.2, 0.2, 0.2, 0.9)],
        zone,
    )


def test_scene_calibration_api_exposes_sanitized_configuration():
    with TestClient(app) as client:
        response = client.get("/api/v1/scene-calibrations/scene-living-room-v1")
        assert response.status_code == 200
        payload = response.json()
        assert payload["schema_version"] == "scene-calibration/1.0"
        assert {item["zone_type"] for item in payload["zones"]} == {"HIGH_RISK", "SUPPORT", "OBSTACLE"}
        assert "device_ref" not in payload


def test_missing_forewarning_is_null_or_empty_without_fabricated_green():
    with TestClient(app) as client:
        latest = client.get("/api/v1/residents/resident-without-data/forewarning/latest")
        history = client.get("/api/v1/residents/resident-without-data/forewarning")
        assert latest.status_code == 200 and latest.json() is None
        assert history.status_code == 200 and history.json() == []


def test_insufficient_legacy_view_preserves_unknown_instead_of_green():
    snapshot = ForewarningSnapshot.model_validate({
        "schema_version": "forewarning-snapshot/1.0",
        "snapshot_id": "forewarning-insufficient-test",
        "resident_id": "resident-insufficient-test",
        "evaluated_at": "2026-08-26T14:00:00+08:00",
        "phase": "PERIODIC",
        "assessment_status": "INSUFFICIENT",
        "confidence_level": "LOW",
        "baseline_status": "INSUFFICIENT",
        "components": {
            "human_risk": 0, "personal_deviation": None,
            "environment_risk": 0, "interaction_risk": 0,
        },
        "instant": {"window_seconds": 8, "engineering_index": 0, "attention_level": "UNKNOWN"},
        "short_30s": {"window_seconds": 30, "engineering_index": 0, "attention_level": "UNKNOWN"},
        "trend_3min": {"window_seconds": 180, "engineering_index": 0, "attention_level": "UNKNOWN"},
        "dominant_factors": [], "degradation_reasons": ["HUMAN_EVIDENCE_INSUFFICIENT"],
        "evidence_ids": [], "observation_ids": [], "recommended_action": "等待合格人体证据。",
        "ruleset_version": "ruleset-v1.3-min", "source_mode": "MOCK", "simulated": True,
    })

    assert legacy_pre_fall_summary(snapshot)["risk_level"] == "UNKNOWN"


def test_scene_calibration_rejects_camera_unsafe_shapes():
    with pytest.raises(ValueError):
        SceneCalibration(
            schema_version="scene-calibration/1.0",
            scene_config_id="scene-invalid",
            camera_position_id="camera-a",
            location="living_room",
            frame_width=1920,
            frame_height=1080,
            zones=[SceneZone(zone_id="flat", zone_type="SAFE", polygon_norm=[(0, 0), (0.5, 0), (1, 0)])],
            effective_from=datetime(2026, 8, 26, tzinfo=CN),
        )


def test_environment_only_is_unknown_and_cannot_create_fall_event(monkeypatch, tmp_path):
    evaluated_at = datetime(2026, 8, 26, 15, 0, tzinfo=CN)

    async def baseline(*_args, **_kwargs):
        return {"overall_status": "INSUFFICIENT", "baselines": {}}

    monkeypatch.setattr(memory_store, "baseline", baseline)

    async def operation(db):
        observation = observation_row(
            "obs-environment-only",
            evaluated_at,
            "illumination_norm",
            0.05,
            source_mode="LIVE_DEVICE",
            simulated=False,
        )
        evidence = evidence_row(
            "evi-environment-only",
            observation.observation_id,
            evaluated_at,
            "low_illumination",
            0.9,
            source_mode="LIVE_DEVICE",
            simulated=False,
            risk_domain="SYSTEM",
        )
        db.add_all([observation, evidence])
        await db.commit()
        snapshot = await evaluate_forewarning(
            db,
            "resident-source-isolation",
            evaluated_at,
            source_mode="LIVE_DEVICE",
            simulated=False,
        )
        decision = await evaluate_risk(
            db,
            "resident-source-isolation",
            evaluated_at,
            evidence.evidence_id,
        )
        return snapshot, decision

    snapshot, decision = asyncio.run(with_database(tmp_path, operation))
    assert snapshot.assessment_status == "INSUFFICIENT"
    assert snapshot.instant.attention_level == "UNKNOWN"
    assert snapshot.components.human_risk == 0.0
    assert snapshot.components.environment_risk == pytest.approx(0.9)
    assert decision["event_created"] is False
    assert decision["event"] is None


def test_init_tables_creates_and_verifies_v13_schema(monkeypatch, tmp_path):
    async def operation():
        database = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'schema.db'}")
        monkeypatch.setattr(init_db, "engine", database)
        try:
            await init_db.init_tables()
            async with database.connect() as connection:
                await init_db.assert_schema_ready(connection)
                return (await connection.execute(text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'forewarning_snapshot'"
                ))).scalar_one_or_none()
        finally:
            await database.dispose()

    assert asyncio.run(operation()) == "forewarning_snapshot"
