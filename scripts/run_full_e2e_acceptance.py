"""Run the frozen Mock API recovery loop three times with virtual timestamps.

This is backend-only acceptance evidence.  It deliberately uses `source_mode=MOCK`
and does not claim a real-device elapsed 60-second wait.
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


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUEST_DIR = ROOT / "deliverables" / "backend-2026-07-31" / "requests"
OUTPUT_DIR = ROOT / "deliverables" / "e2e-2026-07-31"


def load_request(name: str) -> dict:
    return json.loads((REQUEST_DIR / name).read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) + "\n" for item in entries),
        encoding="utf-8",
    )


class RuleLogCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.items.append(json.loads(record.getMessage()))
        except json.JSONDecodeError:
            self.items.append({"unparsed": record.getMessage()})


def checked_post(client, path: str, payload: dict, request_id: str) -> dict:
    response = client.post(path, json=payload, headers={"X-Request-ID": request_id})
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"{path} failed: {response.status_code} {response.text}")
    return {"status_code": response.status_code, "body": response.json()}


async def reset_database(engine, base) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(base.metadata.drop_all)


def run_once(run_number: int, app, engine, base) -> dict:
    from fastapi.testclient import TestClient

    asyncio.run(reset_database(engine, base))
    collector = RuleLogCollector()
    risk_logger = logging.getLogger("risk_rule")
    risk_logger.addHandler(collector)
    risk_logger.setLevel(logging.INFO)
    try:
        rapid_observation = load_request("01-observation-rapid-rise.json")
        rapid_evidence = load_request("02-evidence-rapid-rise.json")
        sway_observation = load_request("03-observation-trunk-sway.json")
        sway_evidence = load_request("04-evidence-trunk-sway.json")
        recovered_observation = load_request("08-observation-posture-recovered.json")
        recovered_evidence = load_request("09-evidence-posture-recovered.json")
        completed_evaluation = load_request("10-evaluate-observation-complete.json")

        with TestClient(app) as client:
            checked_post(client, "/api/v1/observations", rapid_observation, f"e2e-{run_number}-01")
            rapid = checked_post(client, "/api/v1/evidence", rapid_evidence, f"e2e-{run_number}-02")
            checked_post(client, "/api/v1/observations", sway_observation, f"e2e-{run_number}-03")
            orange = checked_post(client, "/api/v1/evidence", sway_evidence, f"e2e-{run_number}-04")
            event_id = orange["body"]["evaluation"]["event_id"]
            intervention_response = client.post(f"/api/v1/events/{event_id}/intervene")
            intervention_response.raise_for_status()
            intervention = {"status_code": intervention_response.status_code, "body": intervention_response.json()}
            intervening_response = client.get(f"/api/v1/events/{event_id}")
            intervening_response.raise_for_status()
            intervening = {"status_code": intervening_response.status_code, "body": intervening_response.json()}

            checked_post(client, "/api/v1/observations", recovered_observation, f"e2e-{run_number}-05")
            observing = checked_post(client, "/api/v1/evidence", recovered_evidence, f"e2e-{run_number}-06")
            observing_detail_response = client.get(f"/api/v1/events/{event_id}")
            observing_detail_response.raise_for_status()
            observing_detail = {"status_code": observing_detail_response.status_code,
                                "body": observing_detail_response.json()}

            resolved = checked_post(client, "/api/v1/risk/evaluate", completed_evaluation, f"e2e-{run_number}-07")
            final_detail_response = client.get(f"/api/v1/events/{event_id}")
            final_detail_response.raise_for_status()
            final_detail = {"status_code": final_detail_response.status_code,
                            "body": final_detail_response.json()}
            event_list = client.get("/api/v1/events", params={"resident_id": "resident-mock-001"})
            event_list.raise_for_status()

        semantic = {
            "risk_levels": [
                rapid["body"]["evaluation"]["risk_level"],
                orange["body"]["evaluation"]["risk_level"],
                observing["body"]["evaluation"]["risk_level"],
                resolved["body"]["risk_level"],
            ],
            "statuses": [
                intervening["body"]["status"],
                intervening["body"]["status"],
                observing_detail["body"]["status"],
                final_detail["body"]["status"],
            ],
            "rules": [
                rapid["body"]["evaluation"]["matched_rule"],
                orange["body"]["evaluation"]["matched_rule"],
                observing["body"]["evaluation"]["matched_rule"],
                resolved["body"]["matched_rule"],
            ],
            "tool_name": intervention["body"]["tool_name"],
            "delivery_status": intervention["body"]["delivery_status"],
            "resolved": final_detail["body"]["interventions"][0]["resolved"],
            "risk_after": final_detail["body"]["interventions"][0]["risk_after"],
        }
        expected = {
            "risk_levels": ["GREEN", "ORANGE", "ORANGE", "GREEN"],
            "statuses": ["INTERVENING", "INTERVENING", "OBSERVING", "RESOLVED"],
            "rules": ["R-FALL-01", "R-FALL-02", "R-FALL-04", "R-FALL-05"],
            "tool_name": "mock_voice",
            "delivery_status": "SUCCESS",
            "resolved": True,
            "risk_after": 0.24,
        }
        if semantic != expected:
            raise RuntimeError(f"run {run_number} semantic mismatch: {semantic}")
        if len(event_list.json()) != 1 or len(final_detail["body"]["interventions"]) != 1:
            raise RuntimeError(f"run {run_number} created an unexpected number of events or interventions")

        run_dir = OUTPUT_DIR / f"run-{run_number}"
        write_json(run_dir / "01-rapid-rise-response.json", rapid)
        write_json(run_dir / "02-orange-response.json", orange)
        write_json(run_dir / "03-intervention-response.json", intervention)
        write_json(run_dir / "04-observing-response.json", observing_detail)
        write_json(run_dir / "05-resolved-response.json", resolved)
        write_json(run_dir / "06-final-event-detail.json", final_detail)
        write_json(run_dir / "07-rule-traces.json", final_detail["body"]["rule_traces"])
        write_json(run_dir / "08-state-transitions.json", semantic)
        write_jsonl(run_dir / "09-rule-logs.jsonl", collector.items)
        summary = {
            "schema_version": "1.0",
            "run": run_number,
            "source_mode": "MOCK",
            "simulated": True,
            "virtual_time": True,
            "event_id": event_id,
            "semantic_signature": semantic,
            "passed": True,
        }
        write_json(run_dir / "summary.json", summary)
        return summary
    finally:
        risk_logger.removeHandler(collector)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the backend Mock recovery-loop acceptance suite.")
    parser.add_argument("--runs", type=int, default=3, help="number of isolated semantic runs")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    os.environ["YINGMU_ENV"] = "mock"
    os.environ["MIN_EVIDENCE_QUALITY"] = "0.70"
    os.environ["MIN_EVIDENCE_CONFIDENCE"] = "0.70"
    os.environ["YINGMU_CONTROL_TOKEN"] = "test-control-token"
    with tempfile.TemporaryDirectory(prefix="yingmu-e2e-") as temp_dir:
        os.environ["YINGMU_DB_PATH"] = str(Path(temp_dir) / "e2e_acceptance.db")
        from backend.db.database import Base, engine
        from backend.main import app

        summaries = [run_once(number, app, engine, Base) for number in range(1, args.runs + 1)]
        asyncio.run(engine.dispose())

    signature = summaries[0]["semantic_signature"]
    consistent = all(item["semantic_signature"] == signature for item in summaries)
    final_summary = {
        "schema_version": "1.0",
        "source_mode": "MOCK",
        "simulated": True,
        "virtual_time": True,
        "runs": args.runs,
        "semantic_signature": signature,
        "consistent": consistent,
        "passed": consistent and all(item["passed"] for item in summaries),
    }
    write_json(OUTPUT_DIR / "final-summary.json", final_summary)
    if not final_summary["passed"]:
        raise SystemExit("FAIL: full backend e2e acceptance is inconsistent")
    print(f"PASS: full backend e2e acceptance; runs={args.runs}; results={OUTPUT_DIR}")


if __name__ == "__main__":
    main()
