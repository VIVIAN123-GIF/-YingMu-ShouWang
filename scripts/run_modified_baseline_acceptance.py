"""Submit the modified-video three-day baseline package through the FastAPI routes
and read back /residents/{id}/baseline to verify PROVISIONAL admission.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def post(client, route: str, payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    response = client.post(route, json=payload, headers={"X-Request-ID": request_id})
    body = response.json()
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"{route} failed: {response.status_code} {body}")
    return {"status_code": response.status_code, "body": body}


async def reset_database(engine, base) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(base.metadata.drop_all)
        await connection.run_sync(base.metadata.create_all)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backend acceptance on modified-video baseline package.")
    parser.add_argument("--package", type=Path, default=Path("artifacts/modified_video_gait_acceptance/modified_video_gait_baseline_package.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/modified_video_gait_acceptance/baseline_http_acceptance.json"))
    args = parser.parse_args()

    package = json.loads(args.package.read_text(encoding="utf-8"))
    resident_id = package["resident_id"]

    os.environ["YINGMU_ENV"] = "mock"
    os.environ["MIN_EVIDENCE_QUALITY"] = "0.70"
    os.environ["MIN_EVIDENCE_CONFIDENCE"] = "0.70"

    with tempfile.TemporaryDirectory(prefix="yingmu-modified-baseline-") as temp_dir:
        os.environ["YINGMU_DB_PATH"] = str(Path(temp_dir) / "modified_baseline.db")
        from fastapi.testclient import TestClient
        from backend.db.database import AsyncSessionLocal, Base, engine  # noqa: F401
        from backend.main import app

        try:
            with TestClient(app) as client:
                asyncio.run(reset_database(engine, Base))

                asset_results = []
                for index, asset in enumerate(package["asset_manifest"], start=1):
                    asset_results.append(post(client, "/api/v1/assets", asset, f"modified-baseline-asset-{index}"))

                observation_results = []
                for index, obs in enumerate(package["observations"], start=1):
                    observation_results.append(post(client, "/api/v1/observations", obs, f"modified-baseline-obs-{index}"))

                evidence_results = []
                for index, evi in enumerate(package["evidences"], start=1):
                    evidence_results.append(post(client, "/api/v1/evidence", evi, f"modified-baseline-evi-{index}"))

                # Query baseline as of the day after the newest sample.
                latest = max(e["timestamp"] for e in package["evidences"])
                latest_dt = datetime.fromisoformat(latest)
                as_of = (latest_dt + timedelta(hours=6)).isoformat()
                response = client.get(f"/api/v1/residents/{resident_id}/baseline", params={"as_of": as_of})
                if response.status_code != 200:
                    raise RuntimeError(f"baseline read failed: {response.status_code} {response.text}")
                baseline = response.json()
        finally:
            asyncio.run(engine.dispose())

    baselines = baseline.get("baselines") or {}
    report = {
        "schema_version": "1.0",
        "resident_id": resident_id,
        "as_of": baseline.get("as_of"),
        "overall_status": baseline.get("overall_status"),
        "observed_days": baseline.get("baseline_progress", {}).get("observed_days"),
        "provisional_target_days": baseline.get("baseline_progress", {}).get("provisional_target_days"),
        "http": {
            "assets": [item["status_code"] for item in asset_results],
            "observations": [item["status_code"] for item in observation_results],
            "evidence": [item["status_code"] for item in evidence_results],
        },
        "baselines": baselines,
        "provenance": baseline.get("provenance"),
        "passed": (
            all(item["status_code"] == 201 for item in asset_results)
            and all(item["status_code"] == 201 for item in observation_results)
            and all(item["status_code"] == 201 for item in evidence_results)
            and baseline.get("overall_status") in {"PROVISIONAL", "STABLE"}
        ),
    }
    write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit("modified-video baseline acceptance did not reach PROVISIONAL")


if __name__ == "__main__":
    main()
