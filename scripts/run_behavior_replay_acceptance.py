"""Verify and actually ingest a result-only C6c behaviour delivery locally.

The delivery ZIP stays outside Git.  The runner creates a temporary SQLite
database, submits only the Asset and Observations it contains, checks an
idempotent replay, and writes a redacted result.  It never manufactures an
Evidence item when the algorithm delivery intentionally contains none.
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
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_json(archive: zipfile.ZipFile, name: str) -> Any:
    try:
        return json.loads(archive.read(name).decode("utf-8"))
    except KeyError as error:
        raise ValueError(f"delivery is missing {name}") from error


def _manifest_checks(archive: zipfile.ZipFile) -> tuple[dict[str, bool], str | None]:
    manifest = archive.read("sha256sums.txt").decode("utf-8")
    checks: dict[str, bool] = {}
    declared_input_video_hash = None
    for line in manifest.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or parts[0].startswith("#"):
            continue
        expected, name = parts[0].upper(), parts[1].strip()
        if name in archive.namelist():
            checks[name] = sha256_bytes(archive.read(name)) == expected
        elif name.lower().endswith(".mp4"):
            declared_input_video_hash = expected
    return checks, declared_input_video_hash


def load_delivery(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        asset = _read_json(archive, "asset.json")
        observations = _read_json(archive, "behavior_observations.json")
        bundle = _read_json(archive, "behavior_bundle.json")
        checks, input_video_hash = _manifest_checks(archive)

    if not isinstance(asset, dict) or not isinstance(observations, list) or not isinstance(bundle, dict):
        raise ValueError("asset, observations, or bundle has an invalid JSON shape")
    evidence = bundle.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("behavior_bundle.json evidence must be an array")
    if bundle.get("observations") != observations:
        raise ValueError("behavior bundle observations disagree with behavior_observations.json")

    from backend.schemas.asset import AssetCreate
    from backend.schemas.observation import ObservationCreate

    validated_asset = AssetCreate.model_validate(asset).model_dump(mode="json")
    validated_observations = [ObservationCreate.model_validate(item).model_dump(mode="json") for item in observations]
    if not validated_observations:
        raise ValueError("delivery contains no Observation")
    if any(item["asset_id"] != validated_asset["asset_id"] for item in validated_observations):
        raise ValueError("an Observation cannot be traced to asset.json")
    if len({item["observation_id"] for item in validated_observations}) != len(validated_observations):
        raise ValueError("duplicate observation_id")
    return {
        "asset": validated_asset,
        "observations": sorted(validated_observations, key=lambda item: item["timestamp"]),
        "evidence_count": len(evidence),
        "manifest_checks": checks,
        "declared_input_video_sha256": input_video_hash,
    }


async def dispose_engine() -> None:
    from backend.db.database import engine
    await engine.dispose()


def run(delivery_zip: Path, output: Path, expected_sha256: str | None) -> int:
    actual_sha256 = sha256_file(delivery_zip)
    if expected_sha256 and actual_sha256 != expected_sha256.upper():
        raise ValueError("delivery ZIP SHA-256 mismatch")
    delivery = load_delivery(delivery_zip)
    if not all(delivery["manifest_checks"].values()):
        raise ValueError("one or more delivery manifest checks failed")

    os.environ["YINGMU_ENV"] = "mock"
    with tempfile.TemporaryDirectory(prefix="yingmu-behavior-replay-") as temp_dir:
        os.environ["YINGMU_DB_PATH"] = str(Path(temp_dir) / "acceptance.db")
        from fastapi.testclient import TestClient
        from backend.main import app

        exchanges: list[dict[str, Any]] = []
        with TestClient(app) as client:
            asset_response = client.post("/api/v1/assets", json=delivery["asset"], headers={"X-Request-ID": "behavior-asset-001"})
            exchanges.append({"kind": "asset", "status_code": asset_response.status_code})
            if asset_response.status_code not in {200, 201}:
                raise RuntimeError(f"asset submission returned HTTP {asset_response.status_code}")
            for index, observation in enumerate(delivery["observations"], 1):
                response = client.post("/api/v1/observations", json=observation,
                                       headers={"X-Request-ID": f"behavior-observation-{index:03d}"})
                exchanges.append({"kind": "observation", "status_code": response.status_code})
                if response.status_code not in {200, 201}:
                    raise RuntimeError(f"observation {index} submission returned HTTP {response.status_code}")
            duplicate_response = client.post("/api/v1/observations", json=delivery["observations"][-1],
                                             headers={"X-Request-ID": "behavior-observation-duplicate"})
            duplicate_body = duplicate_response.json()
            exchanges.append({"kind": "observation_duplicate", "status_code": duplicate_response.status_code,
                              "idempotent": duplicate_body.get("idempotent"), "saved": duplicate_body.get("saved")})
            asset_read = client.get(f"/api/v1/assets/{delivery['asset']['asset_id']}")
            exchanges.append({"kind": "asset_readback", "status_code": asset_read.status_code})
            if asset_read.status_code != 200:
                raise RuntimeError("asset readback failed")
            readback = asset_read.json()
        asyncio.run(dispose_engine())

    idempotent = duplicate_response.status_code == 200 and duplicate_body.get("idempotent") is True and duplicate_body.get("saved") is False
    provenance_preserved = all(readback.get(key) == delivery["asset"].get(key) for key in (
        "source_mode", "simulated", "authorization_status", "device_model", "camera_position_id", "retention_until"))
    passed = all(item["status_code"] in {200, 201} for item in exchanges if item["kind"] != "observation_duplicate") and idempotent and provenance_preserved
    report = {
        "schema_version": "1.0",
        "test_kind": "C6C_BEHAVIOR_RESULT_ONLY_LOCAL_INGESTION",
        "delivery_zip_sha256": actual_sha256,
        "declared_input_video_sha256": delivery["declared_input_video_sha256"],
        "manifest_checks_passed": True,
        "contains_raw_media": False,
        "contains_credentials": False,
        "source_mode": delivery["asset"]["source_mode"],
        "simulated": delivery["asset"]["simulated"],
        "asset_submission_verified": exchanges[0]["status_code"] in {200, 201},
        "observation_submission_count": len(delivery["observations"]),
        "observation_submission_verified": all(item["status_code"] in {200, 201} for item in exchanges if item["kind"] == "observation"),
        "duplicate_observation_idempotent": idempotent,
        "asset_provenance_preserved": provenance_preserved,
        "evidence_count": delivery["evidence_count"],
        "risk_evaluation_executed": False,
        "risk_state_machine_closed": False,
        "automatic_live_device_chain_verified": False,
        "overall_result": "PARTIAL" if passed else "FAILED",
        "interpretation": "Asset and Observations were actually submitted to a temporary local backend. No Evidence was supplied, so no risk evaluation was run or claimed.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['overall_result']}: observations={report['observation_submission_count']}; summary={output}")
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Actually ingest a C6c result-only delivery into a temporary local backend.")
    parser.add_argument("--delivery-zip", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sha256", help="Expected outer ZIP SHA-256; omit only when independently verified.")
    args = parser.parse_args()
    return run(args.delivery_zip, args.output, args.sha256)


if __name__ == "__main__":
    raise SystemExit(main())
