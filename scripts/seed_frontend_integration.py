"""Seed a comprehensive, idempotent data set for frontend/API integration."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


RESIDENT_ID = "resident-mock-001"
CN_TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]


def _json(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def _upsert(session, model, key: str, payload: dict[str, Any]):
    from sqlalchemy import select

    async def apply():
        row = (await session.execute(
            select(model).where(getattr(model, key) == payload[key])
        )).scalar_one_or_none()
        if row is None:
            row = model(**payload)
            session.add(row)
        else:
            for field, value in payload.items():
                setattr(row, field, value)
        return row

    return apply()


def _event_times(now: datetime, index: int) -> tuple[datetime, datetime]:
    created = now - timedelta(hours=2 + index * 2)
    return _naive(created), _naive(created + timedelta(minutes=35))


async def seed(db_path: Path) -> dict[str, Any]:
    db_path = db_path.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["YINGMU_DB_PATH"] = str(db_path)
    os.environ.setdefault("YINGMU_ENV", "mock")
    os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")

    from backend.config import RULESET_VERSION
    from backend.db.database import AsyncSessionLocal, engine
    from backend.db.init_db import init_default_config, init_tables
    from backend.db.models import (
        AlarmProcessingTask,
        AgentExplanationJob,
        Asset,
        DeviceInfo,
        Evidence,
        ForewarningSnapshot,
        InterventionResult,
        Observation,
        RiskAlarm,
        RiskEvent,
        RuleTrace,
    )
    from backend.service.agent_explanation_job_service import enqueue_event_explanation
    from backend.service.serialization import dumps

    await init_tables()
    await init_default_config()
    now = datetime.now(CN_TZ)
    events = _json("frontend/src/mocks/events.json")
    observations = _json("frontend/src/mocks/observations.json")
    forewarnings = _json("frontend/src/mocks/forewarning.json")

    seeded_event_ids: list[str] = []
    evidence_payloads: dict[str, dict[str, Any]] = {}
    async with AsyncSessionLocal() as db:
        device = {
            "resident_id": RESIDENT_ID,
            "device_sn": "MOCK-FRONTEND-C6C",
            "channel_no": 1,
            "device_name": "Frontend integration camera",
            "is_online": True,
            "rtsp_url": None,
            "flv_url": None,
            "adapter_mode": "MOCK",
            "stream_max_channel": 2,
            "update_time": _naive(now),
        }
        await _upsert(db, DeviceInfo, "device_sn", device)

        asset = {
            "asset_id": "asset-frontend-integration",
            "title": "Authorized simulated living-room replay",
            "source_mode": "RECORDED_REPLAY",
            "simulated": True,
            "stream_url": None,
            "fallback_url": None,
            "fallback_kind": "unavailable",
            "available": False,
            "verification_status": "MOCK_ONLY",
            "captured_at": _naive(now - timedelta(days=6)),
            "notice": "Simulated metadata only; no private media is stored.",
            "device_ref": "device-frontend-integration",
            "device_model": "EZVIZ_C6C",
            "camera_position_id": "living-room-main",
            "authorization_status": "AUTHORIZED",
            "authorization_record_id": "authorization-frontend-integration",
            "retention_until": _naive(now + timedelta(days=30)),
        }
        for asset_id in (
            "asset-frontend-integration",
            "asset-fall-authorized",
            "asset-mock-fall-001",
        ):
            await _upsert(db, Asset, "asset_id", {
                **asset,
                "asset_id": asset_id,
                "title": f"Simulated unavailable media ({asset_id})",
            })

        # Keep frontend mock evidence wording while placing all events inside
        # the current weekly-report window.
        for index, item in enumerate(events):
            created_at, updated_at = _event_times(now, index)
            evidence_ids = []
            summaries = []
            for ev_index, evidence in enumerate(item.get("evidences", [])):
                evidence_id = evidence["evidence_id"]
                evidence_ids.append(evidence_id)
                summaries.append({
                    "evidence_id": evidence_id,
                    "evidence_type": evidence["evidence_type"],
                    "explanation": evidence["explanation"],
                })
                payload = {
                    "schema_version": "1.0",
                    "evidence_id": evidence_id,
                    "resident_id": RESIDENT_ID,
                    "timestamp": created_at + timedelta(minutes=ev_index),
                    "risk_domain": evidence["risk_domain"],
                    "evidence_type": evidence["evidence_type"],
                    "severity": evidence["severity"],
                    "confidence": evidence["confidence"],
                    "data_quality": evidence["data_quality"],
                    "baseline_value": evidence.get("baseline_value"),
                    "current_value": evidence.get("current_value"),
                    "baseline_deviation": evidence.get("baseline_deviation"),
                    "time_scale": evidence["time_scale"],
                    "location": evidence.get("location") or "living_room",
                    "explanation": evidence["explanation"],
                    "adapter_version": evidence["adapter_version"],
                    "source_mode": evidence.get("source_mode", "MOCK"),
                    "simulated": True,
                    "observation_ids": dumps(evidence.get("observation_ids", [])),
                }
                evidence_payloads[evidence_id] = payload
                await _upsert(db, Evidence, "evidence_id", payload)

            event_payload = {
                "schema_version": "1.0",
                "event_id": item["event_id"],
                "resident_id": RESIDENT_ID,
                "created_at": created_at,
                "updated_at": updated_at,
                "primary_domain": item["primary_domain"],
                "related_domains": dumps(item.get("related_domains", [])),
                "risk_level": item["risk_level"],
                "risk_score": item["risk_score"],
                "evidence_ids": dumps(evidence_ids),
                "evidence_summary": dumps(summaries),
                "time_horizon": item["time_horizon"],
                "recommended_action": item["recommended_action"],
                "intervention_policy": item["intervention_policy"],
                "status": item["status"],
                "ruleset_version": RULESET_VERSION,
                "source_mode": item.get("source_mode", "MOCK"),
                "simulated": True,
            }
            await _upsert(db, RiskEvent, "event_id", event_payload)
            seeded_event_ids.append(item["event_id"])

            for intervention in item.get("interventions", []):
                result_payload = {
                    "schema_version": "1.0",
                    "result_id": intervention["result_id"],
                    "event_id": item["event_id"],
                    "started_at": created_at + timedelta(minutes=5),
                    "completed_at": created_at + timedelta(minutes=6),
                    "action_type": intervention["action_type"],
                    "tool_name": intervention["tool_name"],
                    "delivery_status": intervention["delivery_status"],
                    "resident_response": intervention.get("resident_response"),
                    "family_feedback": intervention.get("family_feedback"),
                    "risk_after": intervention.get("risk_after"),
                    "resolved": intervention.get("resolved", False),
                    "resolution_reason": intervention.get("resolution_reason"),
                    "operator": intervention.get("operator", "system"),
                    "source_mode": intervention.get("source_mode", "MOCK"),
                    "simulated": True,
                }
                await _upsert(db, InterventionResult, "result_id", result_payload)

        for index, observation in enumerate(observations):
            payload = {
                "schema_version": "1.0",
                "observation_id": observation["observation_id"],
                "resident_id": RESIDENT_ID,
                "timestamp": _naive(now - timedelta(minutes=90 - index)),
                "source": observation["source"],
                "feature_name": observation["feature_name"],
                "feature_value": dumps(observation["feature_value"]),
                "unit": observation.get("unit"),
                "location": observation.get("location") or "living_room",
                "confidence": observation["confidence"],
                "data_quality": observation["data_quality"],
                "source_mode": observation.get("source_mode", "MOCK"),
                "asset_id": observation.get("asset_id"),
                "simulated": True,
                "extra_metadata": dumps(observation.get("metadata", {})),
                "device_sn": None,
            }
            await _upsert(db, Observation, "observation_id", payload)

        # Seven safe days for all three required personal-baseline metrics.
        metric_specs = (
            ("rise_duration", "sit_to_stand_duration", "rise_duration_baseline_sample", "s", 2.2),
            ("trunk_sway", "trunk_sway_angle", "trunk_sway_baseline_sample", "deg", 0.12),
            ("relative_gait_speed", "relative_gait_speed", "gait_stability_baseline_sample", "ratio", 1.0),
        )
        for day in range(7):
            timestamp = _naive(now - timedelta(days=day, hours=15))
            for metric, feature, evidence_type, unit, center in metric_specs:
                suffix = f"{day}-{metric}"
                observation_id = f"obs-fi-baseline-{suffix}"
                value = round(center + (day - 3) * center * 0.015, 4)
                await _upsert(db, Observation, "observation_id", {
                    "schema_version": "1.0", "observation_id": observation_id,
                    "resident_id": RESIDENT_ID, "timestamp": timestamp,
                    "source": "pose", "feature_name": feature,
                    "feature_value": dumps(value), "unit": unit,
                    "location": "living_room", "confidence": 0.96,
                    "data_quality": 0.95, "source_mode": "RECORDED_REPLAY",
                    "asset_id": asset["asset_id"], "simulated": True,
                    "extra_metadata": dumps({"seed": "frontend-integration"}),
                    "device_sn": None,
                })
                evidence_id = f"evi-fi-baseline-{suffix}"
                await _upsert(db, Evidence, "evidence_id", {
                    "schema_version": "1.0", "evidence_id": evidence_id,
                    "resident_id": RESIDENT_ID, "timestamp": timestamp,
                    "risk_domain": "FALL", "evidence_type": evidence_type,
                    "severity": 0.08, "confidence": 0.96, "data_quality": 0.95,
                    "baseline_value": center, "current_value": value,
                    "baseline_deviation": (value - center) / center,
                    "time_scale": "LONG", "location": "living_room",
                    "explanation": f"Safe baseline sample for {metric}",
                    "adapter_version": "frontend-integration-seed-v1",
                    "source_mode": "RECORDED_REPLAY", "simulated": True,
                    "observation_ids": dumps([observation_id]),
                })

        # PRE and POST snapshots make the event-detail warning timeline testable.
        fall_id = "event-fall-100"
        fall_evidence_ids = [
            evidence["evidence_id"] for evidence in events[0].get("evidences", [])
        ]
        for index, phase in enumerate(("PRE_INTERVENTION", "POST_INTERVENTION")):
            template = forewarnings[index]
            snapshot_id = f"snapshot-fi-{phase.lower()}"
            await _upsert(db, ForewarningSnapshot, "snapshot_id", {
                "snapshot_id": snapshot_id, "resident_id": RESIDENT_ID,
                "evaluated_at": _naive(now - timedelta(minutes=50 - index * 15)),
                "phase": phase, "assessment_status": template["assessment_status"],
                "confidence_level": template["confidence_level"],
                "baseline_status": template["baseline_status"],
                "instant_index": template["instant"]["engineering_index"],
                "short_30s_index": template["short_30s"]["engineering_index"],
                "trend_3min_index": template["trend_3min"]["engineering_index"],
                "components_payload": dumps(template["components"]),
                "factors_payload": dumps(template["dominant_factors"]),
                "degradation_payload": dumps(template["degradation_reasons"]),
                "evidence_ids": dumps(fall_evidence_ids),
                "observation_ids": dumps([]), "scene_config_id": "scene-living-room-v1",
                "event_id": fall_id, "intervention_result_id": "result-fall-001" if index else None,
                "recommended_action": template["recommended_action"],
                "ruleset_version": RULESET_VERSION, "source_mode": "MOCK", "simulated": True,
            })

        review_evidence_id = next(iter(evidence_payloads))
        await _upsert(db, RuleTrace, "trace_id", {
            "trace_id": "trace-fi-review", "event_id": None,
            "resident_id": RESIDENT_ID, "evidence_id": review_evidence_id,
            "evaluated_at": _naive(now - timedelta(minutes=20)),
            "ruleset_version": RULESET_VERSION, "matched_rule": "R-FALL-08",
            "previous_state": "GREEN", "next_state": "YELLOW",
            "previous_status": None, "next_status": None,
            "event_created": False, "error": None,
            "trace_payload": dumps({"seed": "frontend-integration", "review_required": True}),
        })

        alarm_id = "alarm-fi-processing"
        await _upsert(db, RiskAlarm, "alarm_msg_id", {
            "alarm_msg_id": alarm_id, "resident_id": RESIDENT_ID,
            "device_sn": device["device_sn"], "alarm_source": "mock_seed",
            "alarm_type": "motion_detected", "capture_img_path": None,
            "alarm_time": _naive(now - timedelta(minutes=12)),
            "raw_callback_json": dumps({"simulated": True, "seed": "frontend-integration"}),
        })
        task_time = _naive(now - timedelta(minutes=11))
        await _upsert(db, AlarmProcessingTask, "task_id", {
            "task_id": "alarm-task-fi-processing", "alarm_msg_id": alarm_id,
            "resident_id": RESIDENT_ID, "device_sn": device["device_sn"],
            "status": "SUCCESS", "attempt_count": 1, "max_attempts": 3,
            "capture_asset_id": asset["asset_id"], "capture_completed_at": task_time,
            "algorithm_attempt_count": 1, "algorithm_started_at": task_time,
            "algorithm_completed_at": task_time + timedelta(seconds=2),
            "algorithm_summary": dumps({"modules": [{"module": "mock_pose", "status": "SUCCESS", "elapsed_ms": 120, "error_code": None}], "observation_count": 3, "evidence_count": 2}),
            "error_stage": None, "error_code": None, "error_message": None,
            "available_at": task_time, "started_at": task_time,
            "finished_at": task_time + timedelta(seconds=2),
            "create_time": task_time, "update_time": task_time + timedelta(seconds=2),
        })
        await db.commit()

        from sqlalchemy import delete

        await db.execute(delete(AgentExplanationJob).where(
            AgentExplanationJob.event_id.in_(seeded_event_ids)
        ))
        await db.commit()
        explanation_jobs = 0
        for event_id in seeded_event_ids:
            try:
                _, created = await enqueue_event_explanation(db, event_id)
                explanation_jobs += int(created)
            except Exception:
                await db.rollback()

    await engine.dispose()
    return {
        "database": str(db_path.resolve()), "resident_id": RESIDENT_ID,
        "events": len(seeded_event_ids), "baseline_samples": 21,
        "forewarning_snapshots": 2, "alarm_tasks": 1,
        "explanation_jobs_created": explanation_jobs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=os.getenv("YINGMU_DB_PATH", "ezviz_system.db"),
        help="SQLite database used by the API and workers",
    )
    args = parser.parse_args()
    summary = asyncio.run(seed(Path(args.db_path)))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
