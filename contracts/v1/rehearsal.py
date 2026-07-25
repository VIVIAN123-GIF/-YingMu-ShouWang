"""Reusable runner for the fixed GREEN -> RESOLVED Mock sequence."""

from __future__ import annotations

from datetime import datetime

from .engine import MockRiskEngine
from .mock_data import RESIDENT_ID, sequence


def run_fixed_sequence() -> tuple[MockRiskEngine, list[dict]]:
    data = sequence()
    engine = MockRiskEngine()
    steps: list[dict] = []

    normal_observation, rapid_observation, sway_observation, recovered_observation = data["observations"]
    normal_evidence, rapid_evidence, sway_evidence, recovered_evidence = data["evidence"]

    engine.ingest_observation(normal_observation)
    engine.ingest_evidence(normal_evidence)
    assert engine.evaluate(RESIDENT_ID) is None
    steps.append({"step": 1, "input": "normal_baseline_sample", "risk_level": "GREEN", "event": None})

    engine.ingest_observation(rapid_observation)
    engine.ingest_evidence(rapid_evidence)
    assert engine.evaluate(RESIDENT_ID) is None
    steps.append({"step": 2, "input": "rapid_rise", "risk_level": "GREEN", "event": None})

    engine.ingest_observation(sway_observation)
    engine.ingest_evidence(sway_evidence)
    event = engine.evaluate(RESIDENT_ID)
    assert event is not None and event.risk_level.value == "ORANGE" and event.status.value == "INTERVENING"
    steps.append({"step": 3, "input": "trunk_sway", "event_id": event.event_id, "risk_level": "ORANGE", "status": "INTERVENING"})

    result = engine.intervene(event.event_id)
    replayed_result = engine.intervene(event.event_id)
    assert result.result_id == replayed_result.result_id and engine.tool_call_count == 1
    steps.append({"step": 4, "action": "mock_voice", "delivery_status": result.delivery_status.value, "resolved": result.resolved, "tool_calls": engine.tool_call_count})

    engine.ingest_observation(recovered_observation)
    engine.ingest_evidence(recovered_evidence)
    event = engine.evaluate(RESIDENT_ID)
    assert event is not None and event.status.value == "OBSERVING"
    steps.append({"step": 5, "input": "posture_recovered", "status": "OBSERVING"})

    event = engine.tick(event.event_id, datetime.fromisoformat("2026-07-31T03:08:30+08:00"))
    result = engine.interventions["result-mock-voice-001"]
    assert event.status.value == "RESOLVED" and result.resolved and result.risk_after == 0.24
    steps.append({"step": 6, "virtual_time": "2026-07-31T03:08:30+08:00", "status": "RESOLVED", "risk_after": result.risk_after, "resolved": result.resolved})

    return engine, steps
