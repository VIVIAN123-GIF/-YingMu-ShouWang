from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts.v1.agent import AgentExplanationRequest, AgentExplanationResponse
from contracts.v1.platform import PlatformSnapshotResult


EXAMPLE_DIR = Path("contracts/v1/examples")
SCHEMA_DIR = Path("contracts/v1/schemas")


def load_example(name: str) -> dict:
    return json.loads((EXAMPLE_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("platform_snapshot_result", PlatformSnapshotResult),
        ("agent_explanation_request", AgentExplanationRequest),
        ("agent_explanation_response", AgentExplanationResponse),
    ],
)
def test_frozen_examples_match_models_and_exported_schemas(name, model):
    payload = load_example(name)
    assert model.model_validate(payload).model_dump(mode="json") == payload
    exported = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert exported == model.model_json_schema()


def test_platform_snapshot_requires_timezone_and_internal_live_url():
    payload = load_example("platform_snapshot_result")
    payload["captured_at"] = "2026-08-15T09:30:00"
    with pytest.raises(ValidationError):
        PlatformSnapshotResult.model_validate(payload)

    payload = load_example("platform_snapshot_result")
    payload["temporary_url"] = None
    with pytest.raises(ValidationError):
        PlatformSnapshotResult.model_validate(payload)


def test_platform_snapshot_rejects_source_and_simulation_mismatch():
    payload = load_example("platform_snapshot_result")
    payload["simulated"] = True
    with pytest.raises(ValidationError):
        PlatformSnapshotResult.model_validate(payload)

    payload = load_example("platform_snapshot_result")
    payload.update({"source_mode": "RECORDED_REPLAY", "temporary_url": None})
    with pytest.raises(ValidationError):
        PlatformSnapshotResult.model_validate(payload)


def test_platform_snapshot_rejects_expiry_before_capture():
    payload = load_example("platform_snapshot_result")
    payload["expires_at"] = "2026-08-15T09:29:59+08:00"
    with pytest.raises(ValidationError):
        PlatformSnapshotResult.model_validate(payload)


def test_agent_request_rejects_unstructured_media_and_loose_scores():
    payload = load_example("agent_explanation_request")
    payload["video_url"] = "https://snapshot.invalid/raw.mp4"
    with pytest.raises(ValidationError):
        AgentExplanationRequest.model_validate(payload)

    payload = load_example("agent_explanation_request")
    payload["risk_score"] = "0.82"
    with pytest.raises(ValidationError):
        AgentExplanationRequest.model_validate(payload)


def test_agent_request_rejects_duplicate_or_overlapping_capabilities():
    payload = load_example("agent_explanation_request")
    payload["verified_capabilities"] = ["EZVIZ_CAPTURE", "EZVIZ_CAPTURE"]
    with pytest.raises(ValidationError):
        AgentExplanationRequest.model_validate(payload)

    payload = load_example("agent_explanation_request")
    payload["verified_capabilities"].append("EZVIZ_SERVER_VOICE")
    with pytest.raises(ValidationError):
        AgentExplanationRequest.model_validate(payload)


@pytest.mark.parametrize("forbidden", ["risk_level", "risk_score", "resolved", "rule_id"])
def test_agent_response_rejects_safety_decision_fields(forbidden):
    payload = deepcopy(load_example("agent_explanation_response"))
    payload[forbidden] = False if forbidden == "resolved" else "forbidden"
    with pytest.raises(ValidationError):
        AgentExplanationResponse.model_validate(payload)
