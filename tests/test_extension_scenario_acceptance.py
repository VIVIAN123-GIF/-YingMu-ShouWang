import asyncio
import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.database import Base
from backend.db.models import RiskEvent
from backend.schemas.evidence import EvidenceCreate
from backend.schemas.observation import ObservationCreate
from backend.service.evidence_service import create_evidence
from backend.service.observation_service import create_observation
from experiments.structured_scenarios.scenarios import (
    GENERATOR_VERSION,
    SCENARIO_KIND,
    build_payloads,
    scenario_catalog,
)
from scripts.run_extension_scenario_acceptance import run_validation


def test_catalog_has_required_12_plus_12_matrix_and_provenance():
    scenarios = scenario_catalog()
    assert len(scenarios) == 24
    assert sum(item["risk_domain"] == "MENTAL" for item in scenarios) == 12
    assert sum(item["risk_domain"] == "FRAUD" for item in scenarios) == 12
    assert {item["category"] for item in scenarios if item["risk_domain"] == "MENTAL"} == {
        "normal_baseline", "activity_decline", "rhythm_shift", "trend_recovery",
    }
    assert {item["category"] for item in scenarios if item["risk_domain"] == "FRAUD"} == {
        "authorized_normal", "unknown_brief", "authorized_risk_words",
        "unknown_long_no_words", "risk_combination", "identity_recovery",
    }
    for index, scenario in enumerate(scenarios):
        assert scenario["source_mode"] == "MOCK"
        assert scenario["simulated"] is True
        assert scenario["scenario_kind"] == SCENARIO_KIND
        assert scenario["generator_version"] == GENERATOR_VERSION
        if scenario["risk_domain"] == "MENTAL":
            assert scenario["input_kind"] == "MULTI_DAY_TREND"
            assert len(scenario["structured_input"]["trend_days"]) == 12
            assert all(
                set(day) == {
                    "date", "activity_range", "room_transitions",
                    "daytime_activity_ratio", "data_quality",
                }
                for day in scenario["structured_input"]["trend_days"]
            )
        else:
            assert scenario["input_kind"] == "VISITOR_CONVERSATION_SCRIPT"
            assert scenario["structured_input"]["raw_transcript_stored"] is False
            assert scenario["structured_input"]["media_present"] is False
        for pair in build_payloads(scenario, index):
            assert pair["observation"]["metadata"]["scenario_kind"] == SCENARIO_KIND
            assert pair["observation"]["metadata"]["generator_version"] == GENERATOR_VERSION
            assert pair["observation"]["metadata"]["structured_input"] == scenario["structured_input"]
            if pair["evidence"]:
                assert pair["evidence"]["adapter_version"] == GENERATOR_VERSION
                assert pair["evidence"]["source_mode"] == "MOCK"
                assert pair["evidence"]["simulated"] is True


def test_isolated_acceptance_reports_expected_metrics(tmp_path):
    summary = asyncio.run(run_validation(tmp_path))
    assert summary["verdict"] == "PASS"
    assert summary["scenario_count"] == summary["passed_scenarios"] == 24

    mental = summary["domains"]["MENTAL"]
    assert mental["passed_scenarios"] == 12
    assert mental["expected_evidence_match"] == {
        "matched": 16, "expected": 16, "percent": 100.0,
    }
    assert mental["false_trigger_count"] == 0
    assert mental["false_escalation_count"] == 0
    assert mental["evidence_traceability"] == {
        "complete": 16, "total": 16, "percent": 100.0,
    }
    assert mental["closure_success"] == {
        "successful": 3, "required": 3, "percent": 100.0,
    }

    fraud = summary["domains"]["FRAUD"]
    assert fraud["passed_scenarios"] == 12
    assert fraud["expected_evidence_match"] == {
        "matched": 19, "expected": 19, "percent": 100.0,
    }
    assert fraud["false_trigger_count"] == 0
    assert fraud["false_escalation_count"] == 0
    assert fraud["evidence_traceability"] == {
        "complete": 19, "total": 19, "percent": 100.0,
    }
    assert fraud["closure_success"] == {
        "successful": 2, "required": 2, "percent": 100.0,
    }

    case_results = json.loads((tmp_path / "case-results.json").read_text(encoding="utf-8"))
    assert len(case_results) == 24
    assert all(item["checks"]["idempotent"] for item in case_results)
    assert "not clinical accuracy" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_same_resident_can_have_independent_mental_and_fraud_events():
    async def operation():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        try:
            async with factory() as db:
                selected = [
                    next(item for item in scenario_catalog() if item["scenario_id"] == "MENTAL-DECLINE-01"),
                    next(item for item in scenario_catalog() if item["scenario_id"] == "FRAUD-UNKNOWN-BRIEF-01"),
                ]
                for index, scenario in enumerate(selected):
                    pair = build_payloads(scenario, index)[0]
                    pair["observation"]["resident_id"] = "resident-cross-domain"
                    pair["evidence"]["resident_id"] = "resident-cross-domain"
                    await create_observation(
                        db, ObservationCreate.model_validate(pair["observation"])
                    )
                    await create_evidence(
                        db,
                        EvidenceCreate.model_validate(pair["evidence"]),
                        request_id=f"cross-domain-{index}",
                    )
                events = (await db.execute(
                    select(RiskEvent).where(RiskEvent.resident_id == "resident-cross-domain")
                )).scalars().all()
                return {(event.primary_domain, event.risk_level, event.status) for event in events}
        finally:
            await engine.dispose()

    assert asyncio.run(operation()) == {
        ("MENTAL", "YELLOW", "OPEN"),
        ("FRAUD", "YELLOW", "OPEN"),
    }


def test_fraud_indicators_outside_30_minute_window_do_not_escalate():
    async def operation():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        try:
            async with factory() as db:
                scenario = next(
                    item for item in scenario_catalog()
                    if item["scenario_id"] == "FRAUD-COMBINATION-01"
                )
                payloads = build_payloads(scenario, 0)
                late_timestamp = payloads[0]["observation"]["timestamp"] + timedelta(minutes=40)
                payloads[2]["observation"]["timestamp"] = late_timestamp
                payloads[2]["evidence"]["timestamp"] = late_timestamp
                for index, pair in enumerate(payloads):
                    await create_observation(
                        db, ObservationCreate.model_validate(pair["observation"])
                    )
                    await create_evidence(
                        db,
                        EvidenceCreate.model_validate(pair["evidence"]),
                        request_id=f"fraud-window-{index}",
                    )
                event = (await db.execute(
                    select(RiskEvent).where(RiskEvent.resident_id == scenario["resident_id"])
                )).scalar_one()
                return event.risk_level, event.status
        finally:
            await engine.dispose()

    assert asyncio.run(operation()) == ("YELLOW", "OPEN")
