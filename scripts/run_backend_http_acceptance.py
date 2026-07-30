"""Generate the fixed 7/27 backend HTTP acceptance evidence package."""

from __future__ import annotations

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
RESULT_DIR = ROOT / "deliverables" / "backend-2026-07-31" / "results"


def load_request(name: str) -> dict:
    return json.loads((REQUEST_DIR / name).read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


class RuleLogCollector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.items: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.items.append(json.loads(record.getMessage()))
        except json.JSONDecodeError:
            self.items.append({"unparsed": record.getMessage()})


def checked_post(client, path: str, payload: dict, request_id: str):
    response = client.post(
        path,
        json=payload,
        headers={"X-Request-ID": request_id},
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"{path} failed: {response.status_code} {response.text}")
    return {"status_code": response.status_code, "body": response.json()}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="yingmu-backend-acceptance-") as temp_dir:
        os.environ["YINGMU_ENV"] = "mock"
        os.environ["YINGMU_DB_PATH"] = str(Path(temp_dir) / "acceptance.db")

        from fastapi.testclient import TestClient
        from sqlalchemy import select

        from backend.db.database import AsyncSessionLocal, engine
        from backend.db.models import Evidence, InterventionResult, RiskEvent, RuleTrace
        from backend.main import app

        collector = RuleLogCollector()
        risk_logger = logging.getLogger("risk_rule")
        risk_logger.addHandler(collector)
        risk_logger.setLevel(logging.INFO)

        rapid_observation = load_request("01-observation-rapid-rise.json")
        rapid_evidence = load_request("02-evidence-rapid-rise.json")
        sway_observation = load_request("03-observation-trunk-sway.json")
        sway_evidence = load_request("04-evidence-trunk-sway.json")
        low_observation = load_request("05-observation-low-quality-trunk-sway.json")
        low_evidence = load_request("06-evidence-low-quality-trunk-sway.json")
        duplicate_evidence = load_request("07-evidence-duplicate.json")

        low_rapid_observation = dict(rapid_observation)
        low_rapid_observation.update({
            "observation_id": "obs-low-quality-rapid-rise-001",
            "resident_id": "resident-low-quality-001",
            "asset_id": "asset-mock-low-quality-001",
        })
        low_rapid_evidence = dict(rapid_evidence)
        low_rapid_evidence.update({
            "evidence_id": "evi-low-quality-rapid-rise-001",
            "observation_ids": ["obs-low-quality-rapid-rise-001"],
            "resident_id": "resident-low-quality-001",
        })

        with TestClient(app) as client:
            checked_post(client, "/api/v1/observations", rapid_observation, "req-accept-01")
            rapid_result = checked_post(
                client, "/api/v1/evidence", rapid_evidence, "req-accept-02"
            )
            checked_post(client, "/api/v1/observations", sway_observation, "req-accept-03")
            orange_result = checked_post(
                client, "/api/v1/evidence", sway_evidence, "req-accept-04"
            )
            event_id = orange_result["body"]["evaluation"]["event_id"]
            event_detail_response = client.get(f"/api/v1/events/{event_id}")
            event_detail_response.raise_for_status()
            event_detail = {
                "status_code": event_detail_response.status_code,
                "body": event_detail_response.json(),
            }

            checked_post(
                client,
                "/api/v1/observations",
                low_rapid_observation,
                "req-accept-05",
            )
            checked_post(
                client,
                "/api/v1/evidence",
                low_rapid_evidence,
                "req-accept-06",
            )
            checked_post(client, "/api/v1/observations", low_observation, "req-accept-07")
            quality_result = checked_post(
                client, "/api/v1/evidence", low_evidence, "req-accept-08"
            )
            duplicate_result = checked_post(
                client, "/api/v1/evidence", duplicate_evidence, "req-accept-09"
            )

        async def database_evidence():
            async with AsyncSessionLocal() as db:
                events = list((await db.execute(
                    select(RiskEvent).order_by(RiskEvent.id)
                )).scalars().all())
                interventions = list((await db.execute(
                    select(InterventionResult).order_by(InterventionResult.id)
                )).scalars().all())
                quality = (await db.execute(select(Evidence).where(
                    Evidence.evidence_id == "sys-quality-evi-low-quality-trunk-sway-001"
                ))).scalar_one_or_none()
                traces = list((await db.execute(
                    select(RuleTrace).order_by(RuleTrace.id)
                )).scalars().all())
                return {
                    "event_count": len(events),
                    "intervention_count": len(interventions),
                    "quality_evidence": {
                        "evidence_id": quality.evidence_id,
                        "risk_domain": quality.risk_domain,
                        "evidence_type": quality.evidence_type,
                        "data_quality": quality.data_quality,
                    } if quality else None,
                    "traces": [{
                        "event_id": trace.event_id,
                        "resident_id": trace.resident_id,
                        "evidence_id": trace.evidence_id,
                        "evaluated_at": trace.evaluated_at.isoformat(),
                        "ruleset_version": trace.ruleset_version,
                        "matched_rule": trace.matched_rule,
                        "previous_state": trace.previous_state,
                        "next_state": trace.next_state,
                        "event_created": trace.event_created,
                        "error": trace.error,
                    } for trace in traces],
                }

        database_result = asyncio.run(database_evidence())
        asyncio.run(engine.dispose())
        risk_logger.removeHandler(collector)

    summary = {
        "schema_version": "1.0",
        "generated_at": "2026-07-28T20:00:00+08:00",
        "source_mode": "MOCK",
        "simulated": True,
        "tests": {
            "rapid_rise_only": rapid_result["body"]["evaluation"],
            "rapid_rise_plus_trunk_sway": orange_result["body"]["evaluation"],
            "low_quality_trunk_sway": quality_result["body"]["evaluation"],
            "duplicate_evidence": duplicate_result["body"]["evaluation"],
        },
        "database": {
            "event_count": database_result["event_count"],
            "intervention_count": database_result["intervention_count"],
            "quality_evidence": database_result["quality_evidence"],
        },
        "passed": (
            rapid_result["body"]["evaluation"]["risk_level"] == "GREEN"
            and orange_result["body"]["evaluation"]["risk_level"] == "ORANGE"
            and quality_result["body"]["evaluation"]["matched_rule"] == "R-FALL-03"
            and duplicate_result["body"]["evaluation"]["matched_rule"] == "R-SYSTEM-01"
            and database_result["event_count"] == 1
            and database_result["intervention_count"] == 0
        ),
    }
    write_json(RESULT_DIR / "01-rapid-rise-response.json", rapid_result)
    write_json(RESULT_DIR / "02-orange-response.json", orange_result)
    write_json(RESULT_DIR / "03-orange-event-detail.json", event_detail)
    write_json(RESULT_DIR / "04-low-quality-response.json", quality_result)
    write_json(RESULT_DIR / "05-duplicate-response.json", duplicate_result)
    write_json(RESULT_DIR / "06-rule-traces.json", database_result["traces"])
    write_json(RESULT_DIR / "07-acceptance-summary.json", summary)
    (RESULT_DIR / "08-rule-logs.jsonl").write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
            for item in collector.items
        ),
        encoding="utf-8",
    )
    if not summary["passed"]:
        raise SystemExit("FAIL: backend HTTP acceptance did not satisfy the frozen rules")
    print(f"PASS: backend HTTP acceptance; results={RESULT_DIR}")


if __name__ == "__main__":
    main()
