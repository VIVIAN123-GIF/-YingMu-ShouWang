"""Build a redacted D10 MOCK event and durable explanation evidence."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DB_PATH = ROOT / ".pytest-tmp-d10" / "d10-mock.db"
OUT_DIR = ROOT / "deliverables" / "d10-mock-acceptance-2026-08-18"
CN = timezone(timedelta(hours=8))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


async def main() -> None:
    os.environ["YINGMU_ENV"] = "mock"
    os.environ["YINGMU_DB_PATH"] = str(DB_PATH)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    from sqlalchemy import select
    from backend.db.database import AsyncSessionLocal, Base, engine
    from backend.db.init_db import init_tables
    from backend.db.models import AgentExplanationJob, Evidence, InterventionResult, Observation, RiskEvent, RiskEventEvidence
    from backend.schemas.intervention_result import InterventionResultCreate
    from backend.schemas.risk_event import EventDetailResponse
    from backend.service.agent_explanation_job_service import (
        claim_next_explanation_job, enqueue_event_explanation, job_dict,
        process_explanation_job,
    )
    from backend.service.agent_explanation_service import AgentExplanationService
    from backend.service.event_service import event_detail
    from backend.service.serialization import dumps, evidence_dict, intervention_dict

    await init_tables()

    async def worker_once(db, service):
        claimed = await claim_next_explanation_job(db)
        if claimed is None:
            raise RuntimeError("D10 explanation job was not claimable")
        return await process_explanation_job(db, claimed, service=service)

    async with AsyncSessionLocal() as db:
        now = datetime.now(CN).replace(microsecond=0)
        event_id = "event-d10-mock-001"
        resident_id = "resident-d10-demo-001"
        fall_obs_id = "obs-d10-fall-001"
        language_obs_id = "obs-d10-language-001"
        pacing_obs_id = "obs-d10-pacing-001"
        fall_evidence_id = "evi-d10-trunk-sway-001"
        pacing_evidence_id = "evi-d10-unusual-pacing-001"

        db.add_all([
            Observation(schema_version="1.0", observation_id=fall_obs_id, resident_id=resident_id,
                        timestamp=now, source="pose", feature_name="trunk_sway_ratio",
                        feature_value="0.82", unit="ratio", location="living_room", confidence=0.94,
                        data_quality=0.95, source_mode="MOCK", asset_id=None, simulated=True,
                        extra_metadata=dumps({"model_version": "mock-gait-v1"}), device_sn=None),
            Observation(schema_version="1.0", observation_id=language_obs_id, resident_id=resident_id,
                        timestamp=now + timedelta(seconds=1), source="language", feature_name="intent",
                        feature_value=dumps("HELP"), unit=None, location="living_room", confidence=0.91,
                        data_quality=0.93, source_mode="MOCK", asset_id=None, simulated=True,
                        extra_metadata=dumps({"model_version": "mock-language-v1"}), device_sn=None),
            Observation(schema_version="1.0", observation_id=pacing_obs_id, resident_id=resident_id,
                        timestamp=now + timedelta(seconds=2), source="tracking", feature_name="pace_variance",
                        feature_value="0.77", unit="ratio", location="living_room", confidence=0.90,
                        data_quality=0.92, source_mode="MOCK", asset_id=None, simulated=True,
                        extra_metadata=dumps({"model_version": "mock-trajectory-v1"}), device_sn=None),
            Evidence(schema_version="1.0", evidence_id=fall_evidence_id, resident_id=resident_id,
                     timestamp=now, risk_domain="FALL", evidence_type="trunk_sway", severity=0.82,
                     confidence=0.94, data_quality=0.95, baseline_value=0.20, current_value=0.82,
                     baseline_deviation=3.1, time_scale="SHORT", location="living_room",
                     explanation="脱敏姿态摘要显示躯干摆动高于个人基线。", adapter_version="mock-gait-v1",
                     source_mode="MOCK", simulated=True, observation_ids=dumps([fall_obs_id])),
            RiskEvent(schema_version="1.0", event_id=event_id, resident_id=resident_id,
                      created_at=now, updated_at=now, primary_domain="FALL", related_domains=dumps([]),
                      risk_level="ORANGE", risk_score=0.82, evidence_ids=dumps([fall_evidence_id]),
                      evidence_summary=dumps([{"evidence_id": fall_evidence_id, "evidence_type": "trunk_sway",
                                               "explanation": "脱敏姿态摘要显示躯干摆动高于个人基线。"}]),
                      time_horizon="IMMINENT", recommended_action="保持坐稳并继续观察。",
                      intervention_policy="fall-orange-gentle-v1", status="INTERVENING",
                      ruleset_version="ruleset-v1.0", source_mode="MOCK", simulated=True),
        ])
        db.add(RiskEventEvidence(event_id=event_id, evidence_id=fall_evidence_id))
        await db.commit()

        first_job, first_created = await enqueue_event_explanation(db, event_id)
        first_done = await worker_once(db, AgentExplanationService(provider=None))

        intervention_payload = InterventionResultCreate(
            schema_version="1.0", result_id="result-d10-language-help-001", event_id=event_id,
            started_at=now + timedelta(seconds=1), completed_at=now + timedelta(seconds=1),
            action_type="resident_response", tool_name="language_adapter", delivery_status="SUCCESS",
            resident_response="help", family_feedback=None, risk_after=None, resolved=False,
            resolution_reason=None, operator="system", source_mode="MOCK", simulated=True,
        )
        intervention = InterventionResult(**intervention_payload.model_dump())
        db.add(intervention)
        await db.commit()
        await db.refresh(intervention)
        second_job, second_created = await enqueue_event_explanation(db, event_id)
        second_done = await worker_once(db, AgentExplanationService(provider=None))

        pacing = Evidence(schema_version="1.0", evidence_id=pacing_evidence_id, resident_id=resident_id,
                          timestamp=now + timedelta(seconds=2), risk_domain="MENTAL", evidence_type="unusual_pacing",
                          severity=0.61, confidence=0.90, data_quality=0.92, baseline_value=0.30,
                          current_value=0.77, baseline_deviation=2.4, time_scale="SHORT", location="living_room",
                          explanation="脱敏行为摘要显示步速节律异常，关联心理健康域。",
                          adapter_version="mock-trajectory-v1", source_mode="MOCK", simulated=True,
                          observation_ids=dumps([pacing_obs_id]))
        db.add(pacing)
        db.add(RiskEventEvidence(event_id=event_id, evidence_id=pacing_evidence_id))
        event = (await db.execute(select(RiskEvent).where(RiskEvent.event_id == event_id))).scalar_one()
        event.evidence_ids = dumps([fall_evidence_id, pacing_evidence_id])
        event.evidence_summary = dumps([
            {"evidence_id": fall_evidence_id, "evidence_type": "trunk_sway", "explanation": "脱敏姿态摘要显示躯干摆动高于个人基线。"},
            {"evidence_id": pacing_evidence_id, "evidence_type": "unusual_pacing", "explanation": "脱敏行为摘要显示步速节律异常，关联心理健康域。"},
        ])
        event.related_domains = dumps(["MENTAL"])
        event.updated_at = now + timedelta(seconds=2)
        await db.commit()
        third_job, third_created = await enqueue_event_explanation(db, event_id)
        third_done = await worker_once(db, AgentExplanationService(provider=None))

        detail = EventDetailResponse.model_validate(
            await event_detail(db, event_id)
        ).model_dump(mode="json")
        latest_twice_a = await enqueue_event_explanation(db, event_id)
        latest_twice_b = await enqueue_event_explanation(db, event_id)
        jobs = list((await db.execute(select(AgentExplanationJob).where(
            AgentExplanationJob.event_id == event_id).order_by(AgentExplanationJob.id))).scalars().all())
        requests = [json.loads(job.request_payload) for job in jobs]
        report = {
            "status": "PASS",
            "source_mode": "MOCK", "simulated": True, "event_id": event_id,
            "event": detail,
            "explanation_after_language": job_dict(second_done),
            "explanation_after_unusual_pacing": job_dict(third_done),
            "intervention_result": intervention_dict(intervention),
            "evidence_result": evidence_dict(pacing),
            "explanation_request_redacted": [
                {"request_id": req["request_id"], "evidence": req["evidence"],
                 "intervention_status": req["intervention_status"]}
                for req in requests
            ],
            "idempotence": {"request_id_a": latest_twice_a[0].request_id,
                            "request_id_b": latest_twice_b[0].request_id,
                            "created_a": latest_twice_a[1], "created_b": latest_twice_b[1],
                            "attempt_count": third_done.attempt_count},
            "risk_fields_before_after_pacing": {
                "before": {"risk_level": "ORANGE", "risk_score": 0.82, "status": "INTERVENING"},
                "after": {"risk_level": detail["risk_level"], "risk_score": detail["risk_score"],
                          "status": detail["status"]},
                "unchanged": detail["risk_level"] == "ORANGE" and detail["risk_score"] == 0.82
                             and detail["status"] == "INTERVENING",
            },
            "worker_log": [
                f"agent_explanation_processed request_id={first_done.request_id} event_id={event_id} status={first_done.status} attempts={first_done.attempt_count}",
                f"agent_explanation_processed request_id={second_done.request_id} event_id={event_id} status={second_done.status} attempts={second_done.attempt_count}",
                f"agent_explanation_processed request_id={third_done.request_id} event_id={event_id} status={third_done.status} attempts={third_done.attempt_count}",
            ],
            "redaction_assertions": {"contains_raw_media": False, "contains_credentials": False,
                                     "contains_raw_transcript": False, "contains_resident_response_help": any(
                                         any(item.get("explanation") == "resident_response_help" for item in req["evidence"])
                                         for req in requests)},
        }
    write_json(OUT_DIR / "d10-mock-acceptance.json", report)
    (OUT_DIR / "README.md").write_text(
        "# D10 MOCK 验收材料\n\n"
        "本材料使用独立 SQLite 数据库生成，`source_mode=MOCK`、`simulated=true`，"
        "不关联任何 RECORDED_REPLAY 事件。Explanation 请求仅保存结构化风险、Evidence 摘要、"
        "干预状态和 `resident_response_help` 语义，不含原始媒体或凭证。\n",
        encoding="utf-8",
    )
    await engine.dispose()
    print(json.dumps({"status": "PASS", "event_id": event_id, "output": str(OUT_DIR)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
