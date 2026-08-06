"""Submit local authorized C6c packages through the real FastAPI routes.

The detailed packages stay outside Git. The optional report contains only
asset/take identifiers, HTTP status codes, rule results, and redacted traces.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


class RuleLogCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.items.append(json.loads(record.getMessage()))
        except json.JSONDecodeError:
            self.items.append({"unparsed": record.getMessage()})


def post(client, route: str, payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    response = client.post(route, json=payload, headers={"X-Request-ID": request_id})
    body = response.json()
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"{route} failed: {response.status_code} {body}")
    return {"status_code": response.status_code, "body": body}


async def database_traces(session_factory, resident_id: str) -> list[dict[str, Any]]:
    from sqlalchemy import select
    from backend.db.models import RuleTrace

    async with session_factory() as db:
        rows = list((await db.execute(
            select(RuleTrace).where(RuleTrace.resident_id == resident_id).order_by(RuleTrace.id)
        )).scalars().all())
    return [
        {
            "trace_id": row.trace_id,
            "event_id": row.event_id,
            "evidence_id": row.evidence_id,
            "matched_rule": row.matched_rule,
            "previous_state": row.previous_state,
            "next_state": row.next_state,
            "ruleset_version": row.ruleset_version,
            "event_created": row.event_created,
            "trace": json.loads(row.trace_payload) if row.trace_payload else None,
        }
        for row in rows
    ]


async def reset_database(engine, base) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(base.metadata.drop_all)
        await connection.run_sync(base.metadata.create_all)


def scenario_result(client, package: dict[str, Any], collector: RuleLogCollector, session_factory) -> dict[str, Any]:
    take_id = package["scenario_id"]
    asset_result = post(client, "/api/v1/assets", package["asset"], f"recorded-{take_id}-asset")
    observation_results = [
        post(client, "/api/v1/observations", item, f"recorded-{take_id}-obs-{index}")
        for index, item in enumerate(package["observations"], start=1)
    ]
    evidence_results = [
        post(client, "/api/v1/evidence", item, f"recorded-{take_id}-evi-{index}")
        for index, item in enumerate(package["evidence"], start=1)
    ]
    duplicate = None
    if package["evidence"]:
        duplicate = post(client, "/api/v1/evidence", package["evidence"][0], f"recorded-{take_id}-duplicate")
    traces = asyncio.run(database_traces(session_factory, package["resident_id"]))
    evaluations = [item["body"]["evaluation"] for item in evidence_results]
    by_type = {
        evidence["evidence_type"]: result["body"]["evaluation"]
        for evidence, result in zip(package["evidence"], evidence_results)
    }

    expected_pass = True
    checks: dict[str, bool] = {
        "asset_created": asset_result["status_code"] == 201,
        "observations_created": all(item["status_code"] == 201 for item in observation_results),
        "evidence_created": all(item["status_code"] == 201 for item in evidence_results),
        "duplicate_idempotent": duplicate is None or duplicate["body"]["evaluation"]["matched_rule"] == "R-SYSTEM-01",
    }
    if "rapid-only" in take_id:
        checks["rapid_only_green"] = by_type.get("rapid_rise", {}).get("risk_level") == "GREEN"
        checks["rapid_only_no_event"] = not by_type.get("rapid_rise", {}).get("event_created", True)
    elif "under15" in take_id:
        recovery = next((item for item in package["evidence"] if item["evidence_type"] == "posture_recovered"), None)
        checks["recovery_below_15"] = bool(recovery and recovery["current_value"] < 15.0)
        checks["recovery_does_not_observe"] = by_type.get("posture_recovered", {}).get("matched_rule") != "R-FALL-04"
    elif "golden" in take_id:
        checks["golden_not_resolved"] = not package["eligible_for_real_resolved_claim"]
        if package["partial_acceptance_stage"] == "CONFIDENCE_BLOCKED":
            checks["confidence_gate_no_orange"] = all(not item["event_created"] for item in evaluations)
    expected_pass = all(checks.values())
    relevant_logs = [
        item for item in collector.items
        if item.get("resident_id") == package["resident_id"]
        and item.get("evidence_id") in {evidence["evidence_id"] for evidence in package["evidence"]}
    ]
    logged_by_id = {item.get("trace_id"): item for item in relevant_logs}
    checks["database_log_trace_exact_match"] = all(
        logged_by_id.get(item["trace_id"]) == item["trace"] for item in traces
    )
    expected_pass = all(checks.values())
    return {
        "take_id": take_id,
        "asset_id": package["asset"]["asset_id"],
        "source_mode": package["source_mode"],
        "simulated": package["simulated"],
        "acceptance_status": package["acceptance_status"],
        "partial_acceptance_stage": package["partial_acceptance_stage"],
        "observation_count": len(package["observations"]),
        "evidence_types": [item["evidence_type"] for item in package["evidence"]],
        "http": {
            "asset": asset_result["status_code"],
            "observations": [item["status_code"] for item in observation_results],
            "evidence": [item["status_code"] for item in evidence_results],
            "duplicate": duplicate["status_code"] if duplicate else None,
        },
        "evaluations": evaluations,
        "database_rule_traces": traces,
        "log_trace_ids": [item.get("trace_id") for item in relevant_logs],
        "checks": checks,
        "passed": expected_pass,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run redacted HTTP acceptance for locally generated C6c packages.")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    package_root = Path(args.package_root).resolve()
    package_paths = sorted(package_root.glob("*/package.json"))
    if not package_paths:
        raise SystemExit(f"no package.json files found below {package_root}")

    os.environ["YINGMU_ENV"] = "mock"
    os.environ["MIN_EVIDENCE_QUALITY"] = "0.70"
    os.environ["MIN_EVIDENCE_CONFIDENCE"] = "0.70"
    with tempfile.TemporaryDirectory(prefix="yingmu-recorded-replay-") as temp_dir:
        os.environ["YINGMU_DB_PATH"] = str(Path(temp_dir) / "recorded_replay.db")
        from fastapi.testclient import TestClient
        from backend.db.database import AsyncSessionLocal, Base, engine
        from backend.main import app

        collector = RuleLogCollector()
        logger = logging.getLogger("risk_rule")
        logger.addHandler(collector)
        logger.setLevel(logging.INFO)
        try:
            with TestClient(app) as client:
                results = []
                for path in package_paths:
                    asyncio.run(reset_database(engine, Base))
                    results.append(scenario_result(
                        client,
                        json.loads(path.read_text(encoding="utf-8")),
                        collector,
                        AsyncSessionLocal,
                    ))
        finally:
            logger.removeHandler(collector)
            asyncio.run(engine.dispose())

    report = {
        "schema_version": "1.0",
        "source_mode": "RECORDED_REPLAY",
        "real_media_processed": True,
        "real_resolved_claimed": False,
        "baseline_status": "INSUFFICIENT",
        "contains_local_paths": False,
        "results": results,
        "passed": all(item["passed"] for item in results),
    }
    write_json(Path(args.output).resolve(), report)
    if not report["passed"]:
        raise SystemExit("recorded replay HTTP acceptance failed")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
