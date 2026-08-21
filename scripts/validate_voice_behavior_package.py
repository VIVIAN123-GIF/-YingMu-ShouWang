"""Validate 常易铭's supplied voice/behavior package against the backend.

The validation reads the checksum-pinned source package, validates every
payload with the backend schemas, and submits the six requests twice to an
isolated temporary SQLite database.  It never writes to the delivery package,
the normal development database, or the algorithm implementation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = (
    ROOT
    / "deliverables"
    / "algorithm-integration"
    / "voice-behavior-2026-08-03"
)
SOURCE_DIR = PACKAGE_DIR / "source" / "常易铭-语音行为接口样例-20260803"
ARCHIVE_PATH = PACKAGE_DIR / "常易铭-语音行为接口样例-20260803.zip"
EXPECTED_SHA256 = "0DF660E40329C614EC5235B7CA7AADE5D009183E8633A4E34CE8E21D72BD73D9"


def load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return payload


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> None:
    if sha256(ARCHIVE_PATH) != EXPECTED_SHA256:
        raise SystemExit("VALIDATION_FAILED: supplied archive SHA-256 does not match")

    manifest = load_json(SOURCE_DIR / "manifest.json")
    request_order = manifest.get("request_order")
    if not isinstance(request_order, list) or len(request_order) != 6:
        raise SystemExit("VALIDATION_FAILED: source manifest must contain six ordered requests")

    payloads: list[tuple[str, str, dict]] = []
    for relative_path in request_order:
        if not isinstance(relative_path, str):
            raise SystemExit("VALIDATION_FAILED: request_order contains a non-string path")
        payload = load_json(SOURCE_DIR / relative_path)
        endpoint = "/api/v1/observations" if "observation_id" in payload else "/api/v1/evidence"
        payloads.append((relative_path, endpoint, payload))

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from backend.schemas.evidence import EvidenceCreate
    from backend.schemas.observation import ObservationCreate

    for relative_path, endpoint, payload in payloads:
        if endpoint.endswith("observations"):
            ObservationCreate.model_validate(payload)
        else:
            EvidenceCreate.model_validate(payload)
        print(f"SCHEMA_PASS {relative_path}")

    os.environ["YINGMU_ENV"] = "mock"
    os.environ["MIN_EVIDENCE_QUALITY"] = "0.70"
    os.environ["MIN_EVIDENCE_CONFIDENCE"] = "0.70"
    with tempfile.TemporaryDirectory(prefix="yingmu-cym-integration-") as temp_dir:
        os.environ["YINGMU_DB_PATH"] = str(Path(temp_dir) / "cym-integration.db")
        from fastapi.testclient import TestClient
        from backend.db.database import engine
        from backend.main import app

        try:
            with TestClient(app) as client:
                for attempt, expected_status in ((1, 201), (2, 200)):
                    for relative_path, endpoint, payload in payloads:
                        response = client.post(endpoint, json=payload)
                        if response.status_code != expected_status:
                            raise SystemExit(
                                f"VALIDATION_FAILED: attempt={attempt} {relative_path} "
                                f"returned {response.status_code}: {response.text}"
                            )
                        body = response.json()
                        if bool(body.get("saved")) != (attempt == 1):
                            raise SystemExit(f"VALIDATION_FAILED: unexpected saved flag for {relative_path}")
                        if bool(body.get("idempotent")) != (attempt == 2):
                            raise SystemExit(f"VALIDATION_FAILED: unexpected idempotent flag for {relative_path}")
                        print(f"HTTP_PASS attempt={attempt} status={expected_status} {relative_path}")
        finally:
            asyncio.run(engine.dispose())

    print("PASS: 常易铭语音/行为样例通过 Schema、首次写入和幂等重放校验")


if __name__ == "__main__":
    main()
