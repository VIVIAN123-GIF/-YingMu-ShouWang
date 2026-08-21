"""Run a redacted C6c recorded-replay acceptance against the local API.

The input archives stay outside the repository.  Only a compact, redacted JSON
summary is written to the requested output path.  This runner deliberately
reports a package whose quality/time gates are not met as INCOMPLETE; it never
rewrites timestamps or upgrades a risk state for demonstration purposes.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EXPECTED_VIDEO_SHA256 = "26838EA4C2D2EC84BCAEB4A1C3AB79C1DAD135172D70513D10FCDCD6B8F71D76"
EXPECTED_RESULT_SHA256 = "CA6067483C7F7E568C4290C41EC76659C7EAD26EDD5958EA252696E733397F85"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _json_entries(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return [name for name in archive.namelist() if name.lower().endswith(".json")]


def _read_json_entry(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    payload = json.loads(archive.read(name).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return payload


def load_packages(video_zip: Path, scenario_id: str | None = None) -> list[dict[str, Any]]:
    with zipfile.ZipFile(video_zip) as archive:
        names = sorted(
            name for name in archive.namelist()
            if name.lower().endswith("/package.json")
        )
        packages = [_read_json_entry(archive, name) for name in names]
    if scenario_id:
        packages = [item for item in packages if item.get("scenario_id") == scenario_id]
    if not packages:
        wanted = scenario_id or "any package.json"
        raise ValueError(f"C6c replay package not found: {wanted}")
    return packages


def validate_package(package: dict[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "scenario_id", "resident_id", "source_mode", "simulated", "asset", "observations", "evidence"}
    missing = sorted(required - package.keys())
    if missing:
        raise ValueError(f"{package.get('scenario_id', '<unknown>')} missing fields: {missing}")
    if package["schema_version"] != "1.0":
        raise ValueError("only schema_version=1.0 is supported")
    if package["source_mode"] != "RECORDED_REPLAY" or package["simulated"] is not True:
        raise ValueError("C6c replay must use source_mode=RECORDED_REPLAY and simulated=true")

    from backend.schemas.asset import AssetCreate
    from backend.schemas.evidence import EvidenceCreate
    from backend.schemas.observation import ObservationCreate

    asset = AssetCreate.model_validate(package["asset"])
    observations = [ObservationCreate.model_validate(item) for item in package["observations"]]
    evidences = [EvidenceCreate.model_validate(item) for item in package["evidence"]]
    observation_ids = {item.observation_id for item in observations}
    if len(observation_ids) != len(observations):
        raise ValueError("duplicate observation_id")
    evidence_ids = {item.evidence_id for item in evidences}
    if len(evidence_ids) != len(evidences):
        raise ValueError("duplicate evidence_id")
    if any(item.resident_id != package["resident_id"] for item in observations + evidences):
        raise ValueError("resident_id is inconsistent across package")
    for evidence in evidences:
        if not set(evidence.observation_ids) <= observation_ids:
            raise ValueError(f"{evidence.evidence_id} references an unknown Observation")
        linked = [item for item in observations if item.observation_id in evidence.observation_ids]
        if any(item.asset_id != asset.asset_id for item in linked):
            raise ValueError(f"{evidence.evidence_id} cannot be traced to Asset")
        if any(item.source_mode != evidence.source_mode or item.simulated != evidence.simulated for item in linked):
            raise ValueError(f"{evidence.evidence_id} disagrees with linked Observation metadata")
    return {"asset": asset.model_dump(mode="json"), "observations": [item.model_dump(mode="json") for item in observations],
            "evidence": [item.model_dump(mode="json") for item in evidences]}


def redact(value: Any, key: str = "") -> Any:
    forbidden = {"stream_url", "fallback_url", "local_path", "source_path", "video_zip", "result_zip", "device_ref", "device_serial",
                 "authorization_record_id", "access_token", "app_secret", "password"}
    if key.lower() in forbidden and value:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {name: redact(child, name) for name, child in value.items()}
    if isinstance(value, list):
        return [redact(child) for child in value]
    return value


async def reset_database(base) -> None:
    from backend.db.database import engine
    async with engine.begin() as connection:
        await connection.run_sync(base.metadata.drop_all)


def submit_package(client, package: dict[str, Any]) -> dict[str, Any]:
    exchanges: list[dict[str, Any]] = []

    def post(path: str, payload: dict[str, Any], request_id: str) -> dict[str, Any]:
        response = client.post(path, json=payload, headers={"X-Request-ID": request_id})
        body = response.json()
        exchanges.append({"path": path, "id": payload.get("asset_id") or payload.get("observation_id") or payload.get("evidence_id"),
                          "status_code": response.status_code, "saved": body.get("saved"),
                          "idempotent": body.get("idempotent"), "evaluation": body.get("evaluation")})
        if response.status_code not in {200, 201}:
            raise RuntimeError(f"{path} returned HTTP {response.status_code}")
        return body

    asset = package["asset"]
    observations = sorted(package["observations"], key=lambda item: item["timestamp"])
    evidences = sorted(package["evidence"], key=lambda item: item["timestamp"])
    post("/api/v1/assets", asset, "c6c-asset-001")
    for index, item in enumerate(observations, 1):
        post("/api/v1/observations", item, f"c6c-observation-{index:03d}")
    evaluations = []
    for index, item in enumerate(evidences, 1):
        body = post("/api/v1/evidence", item, f"c6c-evidence-{index:03d}")
        evaluations.append(body.get("evaluation", {}))
    duplicate = post("/api/v1/evidence", evidences[-1], "c6c-evidence-duplicate")
    event_ids = sorted({item.get("event_id") for item in evaluations if item.get("event_id")})
    details = []
    for event_id in event_ids:
        response = client.get(f"/api/v1/events/{event_id}")
        response.raise_for_status()
        details.append(response.json())
    return {"exchanges": exchanges, "evaluations": evaluations, "duplicate": duplicate,
            "events": details, "event_ids": event_ids}


def run(video_zip: Path, result_zip: Path | None, output: Path, scenario_id: str | None,
        expected_video_sha256: str | None, expected_result_sha256: str | None) -> int:
    checks: dict[str, Any] = {"video_sha256": sha256_file(video_zip)}
    if expected_video_sha256 and checks["video_sha256"] != expected_video_sha256.upper():
        raise ValueError("视频.zip SHA-256 mismatch")
    if result_zip:
        checks["result_sha256"] = sha256_file(result_zip)
        if expected_result_sha256 and checks["result_sha256"] != expected_result_sha256.upper():
            raise ValueError("C6c result ZIP SHA-256 mismatch")
        if not _json_entries(result_zip):
            raise ValueError("result ZIP contains no JSON report")

    packages = load_packages(video_zip, scenario_id)
    os.environ["YINGMU_ENV"] = "mock"
    with tempfile.TemporaryDirectory(prefix="yingmu-c6c-replay-") as temp_dir:
        os.environ["YINGMU_DB_PATH"] = str(Path(temp_dir) / "acceptance.db")
        from fastapi.testclient import TestClient
        from backend.db.database import Base, engine
        from backend.main import app

        reports = []
        for package in packages:
            asyncio.run(reset_database(Base))
            with TestClient(app) as client:
                validated = validate_package(package)
                result = submit_package(client, validated)
            successful = all(item["status_code"] in {200, 201} for item in result["exchanges"])
            duplicate_ok = result["duplicate"].get("idempotent") is True and result["duplicate"].get("saved") is False
            readiness = package.get("readiness_checks", {})
            decision_eligible = bool(readiness.get("rapid_rise_and_trunk_sway") and readiness.get("at_least_one_combo_confidence_gte_0_80"))
            if not decision_eligible:
                state_machine_result = "NOT_ELIGIBLE"
            elif result["event_ids"]:
                state_machine_result = "EVENT_CREATED"
            else:
                state_machine_result = "EXPECTED_EVENT_NOT_CREATED"
            reports.append({"scenario_id": package["scenario_id"], "source_mode": package["source_mode"],
                            "simulated": package["simulated"], "baseline_status": package.get("baseline_status", "INSUFFICIENT"),
                            "http_submission_passed": successful, "duplicate_idempotent": duplicate_ok,
                            "decision_eligible": decision_eligible, "state_machine_result": state_machine_result,
                            "event_ids": result["event_ids"],
                            "evaluations": redact(result["evaluations"]), "events": redact(result["events"]),
                            "passed": successful and duplicate_ok})
        asyncio.run(engine.dispose())
    submission_passed = all(item["passed"] for item in reports)
    state_machine_closed = bool(reports) and all(item["state_machine_result"] == "RESOLVED" for item in reports)
    summary = {"schema_version": "1.0", "test_kind": "C6C_RECORDED_REPLAY_ACCEPTANCE", "checks": checks,
               "contains_credentials": False, "contains_raw_media": False, "reports": reports,
               "recorded_replay_submission_verified": submission_passed,
               "risk_state_machine_closed": state_machine_closed,
               "automatic_live_device_chain_verified": False,
               "overall_result": "PARTIAL" if submission_passed and not state_machine_closed else (
                   "PASS" if submission_passed else "FAILED")}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(redact(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{summary['overall_result']}: scenarios={len(reports)}; summary={output}")
    # PARTIAL is a successful, truthful replay execution with insufficient
    # material for an event closure, not an execution failure.
    return 0 if submission_passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the C6c recorded-replay acceptance without storing media.")
    parser.add_argument("--video-zip", type=Path, required=True)
    parser.add_argument("--result-zip", type=Path)
    parser.add_argument("--scenario-id")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--video-sha256", default=EXPECTED_VIDEO_SHA256)
    parser.add_argument("--result-sha256", default=EXPECTED_RESULT_SHA256)
    args = parser.parse_args()
    return run(args.video_zip, args.result_zip, args.output, args.scenario_id, args.video_sha256, args.result_sha256)


if __name__ == "__main__":
    raise SystemExit(main())
