from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timedelta, timezone

import pytest

from scripts.run_v13_closed_loop_acceptance import (
    EVENT_RESOLVED,
    NO_EVENT,
    AcceptanceError,
    acceptance_errors,
    validate_inputs,
)


def args(tmp_path, expected_outcome=NO_EVENT):
    media = tmp_path / "input.mp4"
    media.write_bytes(b"recorded pixels")
    return Namespace(
        expected_outcome=expected_outcome,
        input=media,
        database=tmp_path / "acceptance.db",
        private_root=tmp_path / "private",
        captured_at="2026-08-26T10:00:00+08:00",
        retention_until="2026-09-30T23:59:59+08:00",
        recovery_input=None,
        recovery_captured_at=None,
        resolve_at=None,
    )


def base_result(expected_outcome):
    positive = expected_outcome == EVENT_RESOLVED
    return {
        "expected_outcome": expected_outcome,
        "input_media_count": 2 if positive else 1,
        "task_statuses": ["COMPLETED"] * (2 if positive else 1),
        "module_results": [[
            {"module": "GAIT", "status": "SUCCESS"},
            {"module": "TRAJECTORY", "status": "SUCCESS"},
        ]] * (2 if positive else 1),
        "counts": {
            "assets": 2 if positive else 1,
            "forewarning_snapshots": 4 if positive else 1,
            "risk_events": 1 if positive else 0,
            "agent_jobs": 3 if positive else 0,
            "intervention_results": 1 if positive else 0,
        },
        "reference_integrity": {"passed": True},
        "transitions": {
            "orange_created": positive,
            "observing_seen": positive,
            "final_status": "RESOLVED" if positive else None,
        },
        "snapshot_phases": ["PERIODIC"] if not positive else [
            "PERIODIC", "PRE_INTERVENTION", "POST_INTERVENTION",
        ],
        "intervention": {} if not positive else {
            "tool_name": "mock_voice",
            "simulated": True,
            "resolved": True,
            "risk_after": 0.28,
        },
        "agent_statuses": ["FALLBACK"] if positive else [],
    }


def test_no_event_rejects_recovery_arguments(tmp_path):
    payload = args(tmp_path)
    payload.recovery_input = tmp_path / "recovery.mp4"

    with pytest.raises(AcceptanceError, match="does not accept recovery"):
        validate_inputs(payload)


def test_event_resolved_requires_complete_recorded_timeline(tmp_path):
    payload = args(tmp_path, EVENT_RESOLVED)
    recovery = tmp_path / "recovery.mp4"
    recovery.write_bytes(b"stable recorded pixels")
    payload.recovery_input = recovery
    payload.recovery_captured_at = "2026-08-26T10:01:00+08:00"
    payload.resolve_at = "2026-08-26T10:02:00+08:00"

    timeline = validate_inputs(payload)

    assert timeline["resolve_at"] - timeline["recovery_at"] == timedelta(seconds=60)


def test_timestamps_must_include_timezone(tmp_path):
    payload = args(tmp_path)
    payload.captured_at = datetime(2026, 8, 26, 10, 0).isoformat()

    with pytest.raises(AcceptanceError, match="timezone"):
        validate_inputs(payload)


def test_positive_acceptance_requires_every_closure_stage():
    complete = base_result(EVENT_RESOLVED)
    assert acceptance_errors(complete) == []

    complete["snapshot_phases"].remove("POST_INTERVENTION")
    complete["intervention"]["risk_after"] = None

    errors = acceptance_errors(complete)
    assert any("POST_INTERVENTION" in error for error in errors)
    assert any("risk_after" in error for error in errors)


def test_no_event_acceptance_rejects_downstream_side_effects():
    result = base_result(NO_EVENT)
    result["counts"]["risk_events"] = 1

    assert "NO_EVENT unexpectedly created a RiskEvent" in acceptance_errors(result)
