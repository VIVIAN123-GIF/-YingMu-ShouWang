import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.database import Base
from backend.db.models import (
    AlarmProcessingTask,
    Asset,
    Evidence,
    ForewarningSnapshot,
    InterventionResult,
    Observation,
    RiskEvent,
    RiskEventEvidence,
    RuleTrace,
)
from backend.schemas.field_run import FieldRunSummary
from backend.service.field_run_service import list_live_field_runs
from backend.service.serialization import dumps


CN_TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 2, 10, 0, tzinfo=CN_TZ)


def asset(asset_id: str, captured_at: datetime, *, source_mode: str = "LIVE_DEVICE", simulated: bool = False):
    return Asset(
        asset_id=asset_id, title=asset_id, source_mode=source_mode, simulated=simulated,
        stream_url=None, fallback_url=None, fallback_kind="private_storage", available=True,
        verification_status="VERIFIED_LIVE_BUFFER_CAPTURE", captured_at=captured_at,
        notice="authorized field run", device_ref="same-c6c-device", device_model="EZVIZ_C6C",
        camera_position_id="C6c-pos01", authorization_status="AUTHORIZED",
        authorization_record_id="AUTH-P01", retention_until=NOW + timedelta(days=1),
    )


def task(task_id: str, asset_id: str, snapshot_id: str, created_at: datetime):
    return AlarmProcessingTask(
        task_id=task_id, alarm_msg_id=f"alarm-{task_id}", resident_id="resident-p01",
        device_sn="private-device-serial", status="COMPLETED", attempt_count=1,
        max_attempts=3, capture_asset_id=asset_id, algorithm_attempt_count=1,
        algorithm_summary=dumps({
            "modules": [{"module": "GAIT", "status": "SUCCESS", "elapsed_ms": 120, "error_code": None}],
            "observation_count": 2, "evidence_count": 2,
            "forewarning_snapshot_id": snapshot_id,
        }),
        available_at=created_at, create_time=created_at, update_time=created_at,
    )


def observation(observation_id: str, asset_id: str, feature_name: str, value: float, unit: str, captured_at: datetime):
    return Observation(
        schema_version="1.0", observation_id=observation_id, resident_id="resident-p01",
        timestamp=captured_at, source="gait_adapter", feature_name=feature_name,
        feature_value=dumps(value), unit=unit, location="living_room", confidence=0.95,
        data_quality=0.94, source_mode="LIVE_DEVICE", asset_id=asset_id, simulated=False,
        extra_metadata=dumps({"scene_config_id": "living-room-c6c-20260831", "camera_position_id": "C6c-pos01"}),
        device_sn=None,
    )


def evidence(evidence_id: str, observation_id: str, evidence_type: str, value: float, captured_at: datetime):
    return Evidence(
        schema_version="1.0", evidence_id=evidence_id, observation_ids=dumps([observation_id]),
        resident_id="resident-p01", timestamp=captured_at, risk_domain="FALL",
        evidence_type=evidence_type, severity=0.84, confidence=0.95, data_quality=0.94,
        baseline_value=4.0, current_value=value, baseline_deviation=2.0,
        time_scale="SHORT", location="living_room", explanation=evidence_type,
        adapter_version="gait-adapter-test", source_mode="LIVE_DEVICE", simulated=False,
    )


def snapshot(
    snapshot_id: str,
    captured_at: datetime,
    score: float,
    *,
    phase: str,
    event_id: str | None = None,
    source_mode: str = "LIVE_DEVICE",
    simulated: bool = False,
):
    return ForewarningSnapshot(
        snapshot_id=snapshot_id, resident_id="resident-p01", evaluated_at=captured_at,
        phase=phase, assessment_status="VALID", confidence_level="HIGH", baseline_status="STABLE",
        instant_index=score, short_30s_index=max(score - 0.02, 0), trend_3min_index=max(score - 0.04, 0),
        components_payload=dumps({"human_risk": score, "personal_deviation": 0.1, "environment_risk": 0.0, "interaction_risk": 0.0}),
        factors_payload=dumps([{"factor": "human_instability", "contribution": score, "evidence_ids": []}]),
        degradation_payload=dumps([]), evidence_ids=dumps([]), observation_ids=dumps([]),
        scene_config_id="living-room-c6c-20260831", event_id=event_id,
        intervention_result_id=None, recommended_action="continue observation",
        ruleset_version="ruleset-v1.5", source_mode=source_mode, simulated=simulated,
    )


def test_field_runs_exclude_replay_and_keep_low_and_high_real_outputs(tmp_path):
    async def operation():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'field-runs.db'}")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        try:
            async with factory() as db:
                low_time = NOW.replace(tzinfo=None)
                high_time = (NOW + timedelta(minutes=5)).replace(tzinfo=None)
                db.add_all([
                    asset("asset-low", low_time), asset("asset-high", high_time),
                    asset("asset-replay", high_time, source_mode="RECORDED_REPLAY", simulated=True),
                    task("run-low", "asset-low", "snapshot-low", low_time),
                    task("run-high", "asset-high", "snapshot-high-final", high_time),
                    task("run-replay", "asset-replay", "snapshot-replay", high_time),
                    observation("obs-low-rise", "asset-low", "sit_to_stand_duration", 2.4, "s", low_time),
                    observation("obs-low-sway", "asset-low", "trunk_sway_angle", 4.2, "degree", low_time),
                    observation("obs-high-rise", "asset-high", "sit_to_stand_duration", 1.1, "s", high_time),
                    observation("obs-high-sway", "asset-high", "trunk_sway_angle", 18.6, "degree", high_time),
                    evidence("evi-high-rise", "obs-high-rise", "rapid_rise", 1.1, high_time),
                    evidence("evi-high-sway", "obs-high-sway", "trunk_sway", 18.6, high_time),
                    snapshot("snapshot-low", low_time, 0.12, phase="PERIODIC"),
                    snapshot("snapshot-high-pre", high_time, 0.84, phase="PRE_INTERVENTION", event_id="event-high"),
                    snapshot("snapshot-high-final", high_time + timedelta(seconds=5), 0.82, phase="PERIODIC"),
                    snapshot("snapshot-high-post", high_time + timedelta(seconds=70), 0.18, phase="POST_INTERVENTION", event_id="event-high"),
                    snapshot(
                        "snapshot-replay-contamination", high_time + timedelta(seconds=80), 0.99,
                        phase="POST_INTERVENTION", event_id="event-high",
                        source_mode="RECORDED_REPLAY", simulated=True,
                    ),
                ])
                event = RiskEvent(
                    schema_version="1.0", event_id="event-high", resident_id="resident-p01",
                    created_at=high_time, updated_at=high_time + timedelta(seconds=70), primary_domain="FALL",
                    related_domains=dumps([]), risk_level="GREEN", risk_score=0.0,
                    evidence_ids=dumps(["evi-high-rise", "evi-high-sway"]),
                    evidence_summary=dumps([]), time_horizon="IMMINENT", recommended_action="sit steadily",
                    intervention_policy="fall-orange-gentle-v1", status="RESOLVED",
                    ruleset_version="ruleset-v1.5", source_mode="LIVE_DEVICE", simulated=False,
                )
                db.add_all([
                    event,
                    RiskEventEvidence(event_id="event-high", evidence_id="evi-high-rise"),
                    RiskEventEvidence(event_id="event-high", evidence_id="evi-high-sway"),
                    RuleTrace(
                        trace_id="trace-high", event_id="event-high", resident_id="resident-p01",
                        evidence_id="evi-high-sway", evaluated_at=high_time, ruleset_version="ruleset-v1.5",
                        matched_rule="R-FALL-03", previous_state="GREEN", next_state="ORANGE",
                        previous_status=None, next_status="INTERVENING", event_created=True,
                        trace_payload=dumps({
                            "trace_id": "trace-high", "event_id": "event-high", "evidence_id": "evi-high-sway",
                            "evaluated_at": high_time.replace(tzinfo=CN_TZ).isoformat(), "matched_rule": "R-FALL-03",
                            "previous_state": "GREEN", "next_state": "ORANGE",
                        }),
                    ),
                    InterventionResult(
                        schema_version="1.0", result_id="result-high", event_id="event-high",
                        started_at=high_time, completed_at=high_time + timedelta(seconds=70),
                        action_type="voice", tool_name="ezviz_voice", delivery_status="SUCCESS",
                        resident_response="stable", family_feedback=None, risk_after=0.18, resolved=True,
                        resolution_reason="stable posture", operator="system", source_mode="LIVE_DEVICE", simulated=False,
                    ),
                ])
                await db.commit()

                result = await list_live_field_runs(db, "resident-p01", limit=20)
                validated = [FieldRunSummary.model_validate(item) for item in result]
                assert [item.run_id for item in validated] == ["run-high", "run-low"]
                high, low = validated
                assert high.risk_level == "ORANGE"
                assert high.risk_score == 0.84
                assert high.current_risk_level == "GREEN"
                assert high.metrics["rapid_rise"].detected is True
                assert high.metrics["trunk_sway"].value == 18.6
                assert [item.phase for item in high.forewarning_snapshots] == [
                    "PRE_INTERVENTION", "PERIODIC", "POST_INTERVENTION",
                ]
                assert all(item.source_mode == "LIVE_DEVICE" for item in high.forewarning_snapshots)
                assert high.rule_traces[0]["trace_id"] == "trace-high"
                assert high.interventions[0].risk_after == 0.18
                assert low.event is None
                assert low.risk_level == "GREEN"
                assert low.metrics["rapid_rise"].detected is False
                assert low.metrics["rapid_rise"].value == 2.4
                assert all(item.source_mode == "LIVE_DEVICE" and item.simulated is False for item in validated)
        finally:
            await engine.dispose()

    asyncio.run(operation())
