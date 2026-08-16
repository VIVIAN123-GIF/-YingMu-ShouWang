from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


FRONTEND = Path(__file__).resolve().parents[1]
ROOT = FRONTEND.parent
API_BASE = "http://127.0.0.1:8021/api/v1"
HEALTH_URL = "http://127.0.0.1:8021/health"


def request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc


def wait_for_health(timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("temporary FastAPI server did not become ready")


def stop_process(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def observation(identifier: str, resident_id: str, timestamp: datetime, feature_name: str, value: float, unit: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "observation_id": identifier,
        "resident_id": resident_id,
        "timestamp": timestamp.isoformat(),
        "source": "pose",
        "feature_name": feature_name,
        "feature_value": value,
        "unit": unit,
        "location": "living_room",
        "confidence": 0.92,
        "data_quality": 0.88,
        "source_mode": "MOCK",
        "asset_id": None,
        "simulated": True,
        "metadata": {"verification": "frontend-agent-api"},
    }


def evidence(
    identifier: str,
    observation_id: str,
    resident_id: str,
    timestamp: datetime,
    evidence_type: str,
    severity: float,
    baseline: float,
    current: float,
    deviation: float,
    explanation: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "evidence_id": identifier,
        "observation_ids": [observation_id],
        "resident_id": resident_id,
        "timestamp": timestamp.isoformat(),
        "risk_domain": "FALL",
        "evidence_type": evidence_type,
        "severity": severity,
        "confidence": 0.92,
        "data_quality": 0.88,
        "baseline_value": baseline,
        "current_value": current,
        "baseline_deviation": deviation,
        "time_scale": "SHORT",
        "location": "living_room",
        "explanation": explanation,
        "adapter_version": "frontend-agent-api-verification-v1",
        "source_mode": "MOCK",
        "simulated": True,
    }


def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    resident_id = f"resident-agent-{suffix}"
    python = os.environ.get("PYTHON", "python")
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    backend: subprocess.Popen[Any] | None = None
    worker: subprocess.Popen[Any] | None = None

    with tempfile.TemporaryDirectory(prefix="yingmu-agent-frontend-") as temp_dir:
        env = os.environ.copy()
        env.update({
            "YINGMU_DB_PATH": str(Path(temp_dir) / "verification.db"),
            "YINGMU_ENV": "mock",
            "AGENT_LLM_BASE_URL": "",
            "AGENT_LLM_MODEL": "",
        })
        try:
            backend = subprocess.Popen(
                [python, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8021"],
                cwd=ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            wait_for_health()
            worker = subprocess.Popen(
                [python, "-m", "backend.worker.agent_worker", "--poll-seconds", "0.2"],
                cwd=ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )

            first_time = datetime.now().astimezone()
            second_time = first_time + timedelta(seconds=4)
            rise_observation = observation(f"obs-{suffix}-rise", resident_id, first_time, "sit_to_stand_duration", 1.2, "second")
            sway_observation = observation(f"obs-{suffix}-sway", resident_id, second_time, "trunk_sway_angle", 18, "degree")
            rise_evidence = evidence(
                f"evi-{suffix}-rise", rise_observation["observation_id"], resident_id, first_time,
                "rapid_rise", 0.78, 3.5, 1.2, -2.3, "起身速度明显快于个人基线",
            )
            sway_evidence = evidence(
                f"evi-{suffix}-sway", sway_observation["observation_id"], resident_id, second_time,
                "trunk_sway", 0.82, 6.2, 18, 2.8, "快速起身后出现明显躯干摇晃",
            )

            request_json("POST", "/observations", rise_observation)
            request_json("POST", "/evidence", rise_evidence)
            request_json("POST", "/observations", sway_observation)
            risk_response = request_json("POST", "/evidence", sway_evidence)
            event_id = risk_response.get("evaluation", {}).get("event_id")
            if not event_id:
                raise RuntimeError("risk event was not created")

            explanation_response: dict[str, Any] = {}
            for _ in range(40):
                explanation_response = request_json("GET", f"/events/{event_id}/explanation")
                if explanation_response.get("status") in {"SUCCESS", "FALLBACK", "FAILED"}:
                    break
                time.sleep(0.25)
            if explanation_response.get("status") != "FALLBACK":
                raise RuntimeError(f"unexpected explanation terminal status: {explanation_response.get('status')}")
            if explanation_response.get("generated_by") != "template-fallback-v1" or explanation_response.get("fallback_used") is not True:
                raise RuntimeError("fallback metadata does not match the API contract")

            intervention = request_json("POST", f"/events/{event_id}/intervene", {})
            completed_at = datetime.now().astimezone().isoformat()
            resident_result = request_json("POST", f"/events/{event_id}/results", {
                "schema_version": "1.0",
                "result_id": f"result-{suffix}-stable",
                "event_id": event_id,
                "started_at": completed_at,
                "completed_at": completed_at,
                "action_type": "resident_response",
                "tool_name": "family_console",
                "delivery_status": "SUCCESS",
                "resident_response": "stable",
                "family_feedback": None,
                "risk_after": None,
                "resolved": False,
                "resolution_reason": None,
                "operator": "family",
                "source_mode": "MOCK",
                "simulated": True,
            })
            result = {
                "event_id": event_id,
                "explanation_status": explanation_response["status"],
                "generated_by": explanation_response["generated_by"],
                "fallback_used": explanation_response["fallback_used"],
                "intervention_status": intervention["delivery_status"],
                "resident_result_action": resident_result["action_type"],
                "resident_response": resident_result["resident_response"],
            }
            print(json.dumps(result, ensure_ascii=False))
            return 0
        finally:
            stop_process(worker)
            stop_process(backend)


if __name__ == "__main__":
    raise SystemExit(main())
