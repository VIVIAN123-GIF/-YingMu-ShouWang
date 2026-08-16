"""Export canonical JSON Schema and validated examples from Pydantic models."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.v1.mock_data import sequence  # noqa: E402
from contracts.v1.mock_memory_data import safe_history  # noqa: E402
from contracts.v1.agent import AgentExplanationRequest, AgentExplanationResponse  # noqa: E402
from contracts.v1.algorithm import AdapterBatch, AlgorithmJob  # noqa: E402
from contracts.v1.models import Evidence, InterventionResult, Observation, RiskEvent  # noqa: E402
from contracts.v1.platform import PlatformSnapshotResult  # noqa: E402
from contracts.v1.rehearsal import run_fixed_sequence  # noqa: E402


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    schema_dir = ROOT / "contracts" / "v1" / "schemas"
    example_dir = ROOT / "contracts" / "v1" / "examples"
    models = {
        "observation": Observation,
        "evidence": Evidence,
        "risk_event": RiskEvent,
        "intervention_result": InterventionResult,
        "platform_snapshot_result": PlatformSnapshotResult,
        "agent_explanation_request": AgentExplanationRequest,
        "agent_explanation_response": AgentExplanationResponse,
        "algorithm_job": AlgorithmJob,
        "adapter_batch": AdapterBatch,
    }
    for name, model in models.items():
        write_json(schema_dir / f"{name}.schema.json", model.model_json_schema())

    data = sequence()
    engine, steps = run_fixed_sequence()
    snapshot = engine.snapshot()
    examples = {
        "observation": Observation.model_validate(data["observations"][1]).model_dump(mode="json"),
        "evidence": Evidence.model_validate(data["evidence"][1]).model_dump(mode="json"),
        "risk_event": snapshot["events"][0],
        "intervention_result": snapshot["interventions"][0],
    }
    for name, payload in examples.items():
        write_json(example_dir / f"{name}.json", payload)
    d1_examples = {
        "platform_snapshot_result": {
            "schema_version": "platform-snapshot/1.0",
            "request_id": "ezviz-capture-20260815-001",
            "device_ref": "device-redacted-a13f",
            "channel_no": 1,
            "captured_at": "2026-08-15T09:30:00+08:00",
            "source_mode": "LIVE_DEVICE",
            "simulated": False,
            "temporary_url": "https://snapshot.invalid/internal/capture-001",
            "expires_at": None,
            "provider_latency_ms": 3650,
        },
        "agent_explanation_request": {
            "schema_version": "agent-explanation/1.0",
            "request_id": "agent-event-001-v1",
            "event_id": "event-001",
            "resident_id": "resident-001",
            "risk_level": "ORANGE",
            "risk_score": 0.82,
            "time_horizon": "IMMINENT",
            "evidence": [
                {
                    "evidence_type": "rapid_rise",
                    "explanation": "起身时长1.1秒，明显短于个人基线2.4秒",
                },
                {
                    "evidence_type": "trunk_sway",
                    "explanation": "躯干摆幅18.4度，高于个人基线5.2度",
                },
            ],
            "baseline_status": "STABLE",
            "intervention_status": "NOT_STARTED",
            "verified_capabilities": ["EZVIZ_CAPTURE"],
            "unverified_capabilities": ["EZVIZ_SERVER_VOICE"],
        },
        "agent_explanation_response": {
            "schema_version": "agent-explanation/1.0",
            "request_id": "agent-event-001-v1",
            "event_id": "event-001",
            "summary": "老人快速起身后出现持续躯干摇摆",
            "reasoning_points": [
                "起身速度明显偏离个人基线",
                "摇摆证据与快速起身位于同一短时窗口",
            ],
            "recommended_action_text": "建议提醒老人坐稳并继续观察",
            "capability_notice": "设备服务端语音尚未验证，将使用明确标记的降级工具",
            "generated_by": "llm-agent-v1",
            "fallback_used": False,
        },
        "algorithm_job": {
            "schema_version": "algorithm-job/1.0",
            "job_id": "job-alarm-task-001",
            "correlation_id": "alarm-task-001",
            "resident_id": "resident-001",
            "asset_id": "asset-authorized-001",
            "media_type": "VIDEO",
            "media_locator": "C:/private-media/authorized/event-001.mp4",
            "captured_at": "2026-08-15T09:30:00+08:00",
            "source_mode": "RECORDED_REPLAY",
            "simulated": True,
            "location": "living_room",
            "camera_position_id": "living-room-c6c-v1",
            "scene_config_id": "scene-living-room-v1",
            "requested_modules": ["GAIT", "TRAJECTORY"],
            "deadline_ms": 8000,
        },
        "adapter_batch": {
            "schema_version": "adapter-batch/1.0",
            "job_id": "job-alarm-task-001",
            "module": "GAIT",
            "adapter_version": "gait-adapter-v1.0.0",
            "status": "NO_EVIDENCE",
            "started_at": "2026-08-15T09:30:01+08:00",
            "completed_at": "2026-08-15T09:30:03+08:00",
            "observations": [{
                "schema_version": "1.0",
                "observation_id": "obs-gait-asset001-quality-0",
                "resident_id": "resident-001",
                "timestamp": "2026-08-15T09:30:02+08:00",
                "source": "pose",
                "feature_name": "valid_frame_ratio",
                "feature_value": 0.91,
                "unit": "ratio",
                "location": "living_room",
                "confidence": 0.92,
                "data_quality": 0.91,
                "source_mode": "RECORDED_REPLAY",
                "asset_id": "asset-authorized-001",
                "simulated": True,
                "metadata": {"model_version": "mediapipe-pose-heavy"},
            }],
            "evidences": [],
            "resident_response_candidate": None,
            "diagnostics": {"elapsed_ms": 1860, "valid_frame_ratio": 0.91},
            "error": None,
        },
    }
    for name, payload in d1_examples.items():
        model = models[name]
        validated = model.model_validate(payload).model_dump(mode="json")
        write_json(example_dir / f"{name}.json", validated)
    write_json(example_dir / "four_objects.json", examples)
    write_json(example_dir / "mock_fall_sequence.json", {**data, "expected_steps": steps})
    write_json(example_dir / "mock_memory_history.json", safe_history())
    print(
        f"Exported {len(models)} schemas and "
        f"{len(examples) + len(d1_examples) + 3} example files"
    )


if __name__ == "__main__":
    main()
