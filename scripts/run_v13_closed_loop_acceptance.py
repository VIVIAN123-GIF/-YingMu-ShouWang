"""Run authorized recordings through the v1.3-min backend acceptance chain.

Reports contain counts and state transitions only. They never include media
paths, names, hashes, device identifiers, credentials, or pose coordinates.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NO_EVENT = "NO_EVENT"
EVENT_RESOLVED = "EVENT_RESOLVED"


class AcceptanceError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an anonymous v1.3-min replay acceptance")
    parser.add_argument("--expected-outcome", choices=(NO_EVENT, EVENT_RESOLVED), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--retention-until", required=True)
    parser.add_argument("--recovery-input", type=Path)
    parser.add_argument("--recovery-captured-at")
    parser.add_argument("--resolve-at")
    parser.add_argument("--scene-config-id", default="scene-recorded-demo-v1")
    parser.add_argument("--camera-position-id", default="recorded-fixed-demo-v1")
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AcceptanceError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AcceptanceError(f"{field} must include a timezone offset")
    return parsed


def validate_inputs(args: argparse.Namespace) -> dict[str, datetime]:
    if not args.input.is_file():
        raise AcceptanceError("INPUT_MEDIA_NOT_FOUND")
    captured_at = parse_timestamp(args.captured_at, "captured-at")
    retention_until = parse_timestamp(args.retention_until, "retention-until")
    if retention_until <= captured_at:
        raise AcceptanceError("retention-until must be after captured-at")

    timeline = {"captured_at": captured_at, "retention_until": retention_until}
    recovery_values = (args.recovery_input, args.recovery_captured_at, args.resolve_at)
    if args.expected_outcome == NO_EVENT:
        if any(value is not None for value in recovery_values):
            raise AcceptanceError("NO_EVENT does not accept recovery inputs")
        return timeline

    if any(value is None for value in recovery_values):
        raise AcceptanceError(
            "EVENT_RESOLVED requires recovery-input, recovery-captured-at, and resolve-at"
        )
    if not args.recovery_input.is_file():
        raise AcceptanceError("RECOVERY_MEDIA_NOT_FOUND")
    recovery_at = parse_timestamp(args.recovery_captured_at, "recovery-captured-at")
    resolve_at = parse_timestamp(args.resolve_at, "resolve-at")
    if recovery_at <= captured_at:
        raise AcceptanceError("recovery-captured-at must be after captured-at")
    if retention_until <= recovery_at:
        raise AcceptanceError("retention-until must be after recovery-captured-at")
    timeline.update({"recovery_at": recovery_at, "resolve_at": resolve_at})
    return timeline


async def _process_recording(
    db: Any,
    *,
    input_path: Path,
    captured_at: datetime,
    resident_id: str,
    private_root: Path,
    camera_position_id: str,
    retention_until: str,
) -> Any:
    from backend.service.algorithm_task_service import (
        claim_next_algorithm_task,
        process_algorithm_task,
    )
    from backend.service.recorded_replay_ingest_service import enqueue_recorded_replay

    await enqueue_recorded_replay(
        db,
        input_path=input_path,
        resident_id=resident_id,
        captured_at=captured_at,
        private_media_root=str(private_root),
        camera_position_id=camera_position_id,
        authorization_record_id="authorization-local-acceptance",
        retention_until=retention_until,
    )
    task = await claim_next_algorithm_task(db)
    if task is None:
        raise AcceptanceError("ALGORITHM_TASK_NOT_CREATED")
    return await process_algorithm_task(db, task)


async def _drain_agent_jobs(db: Any) -> list[str]:
    from backend.service.agent_explanation_job_service import (
        claim_next_explanation_job,
        process_explanation_job,
    )

    statuses: list[str] = []
    while True:
        job = await claim_next_explanation_job(db)
        if job is None:
            return statuses
        result = await process_explanation_job(db, job)
        statuses.append(result.status)


def _module_results(task: Any) -> list[dict[str, Any]]:
    from backend.service.serialization import loads

    summary = loads(task.algorithm_summary, {})
    return [
        {
            "module": item.get("module"),
            "status": item.get("status"),
            "error_code": item.get("error_code"),
        }
        for item in summary.get("modules", [])
        if isinstance(item, dict)
    ]


def acceptance_errors(result: dict[str, Any]) -> list[str]:
    counts = result["counts"]
    errors: list[str] = []
    if result["task_statuses"][0] not in {"COMPLETED", "NO_EVIDENCE"}:
        errors.append("trigger algorithm task did not finish successfully")
    modules = {item.get("module"): item.get("status") for item in result["module_results"][0]}
    if not {"GAIT", "TRAJECTORY"}.issubset(modules):
        errors.append("GAIT and TRAJECTORY were not both executed")
    if not result["reference_integrity"]["passed"]:
        errors.append("cross-table reference integrity failed")
    if counts["assets"] < result["input_media_count"]:
        errors.append("not every input recording produced an Asset")
    if counts["forewarning_snapshots"] < result["input_media_count"]:
        errors.append("not every input recording produced a ForewarningSnapshot")

    if result["expected_outcome"] == NO_EVENT:
        if counts["risk_events"] != 0:
            errors.append("NO_EVENT unexpectedly created a RiskEvent")
        if counts["agent_jobs"] != 0 or counts["intervention_results"] != 0:
            errors.append("NO_EVENT unexpectedly entered agent or intervention stages")
        return errors

    if len(result["task_statuses"]) != 2 or result["task_statuses"][1] not in {
        "COMPLETED", "NO_EVIDENCE"
    }:
        errors.append("recovery algorithm task did not finish successfully")
    required_counts = {
        "risk_events": 1,
        "agent_jobs": 1,
        "intervention_results": 1,
    }
    for name, minimum in required_counts.items():
        if counts[name] < minimum:
            errors.append(f"{name} did not reach the required count")
    if not result["transitions"].get("orange_created"):
        errors.append("ORANGE event was not created")
    if not result["transitions"].get("observing_seen"):
        errors.append("recovery evidence did not enter OBSERVING")
    if result["transitions"].get("final_status") != "RESOLVED":
        errors.append("event did not resolve after the observation window")
    if not {"PRE_INTERVENTION", "POST_INTERVENTION"}.issubset(result["snapshot_phases"]):
        errors.append("PRE_INTERVENTION and POST_INTERVENTION snapshots are both required")
    if result["intervention"].get("tool_name") != "mock_voice":
        errors.append("acceptance intervention must use mock_voice")
    if result["intervention"].get("simulated") is not True:
        errors.append("acceptance intervention must remain simulated")
    if result["intervention"].get("resolved") is not True:
        errors.append("intervention result was not closed by the recovery state machine")
    if result["intervention"].get("risk_after") is None:
        errors.append("resolved intervention is missing risk_after")
    if not result["agent_statuses"] or any(
        status not in {"SUCCESS", "FALLBACK"} for status in result["agent_statuses"]
    ):
        errors.append("agent explanation jobs did not finish successfully or by fallback")
    return errors


async def run_backend(args: argparse.Namespace, timeline: dict[str, datetime]) -> dict[str, Any]:
    from sqlalchemy import func, select

    from backend.db.database import AsyncSessionLocal
    from backend.db.init_db import init_default_config, init_tables
    from backend.db.models import (
        AgentExplanationJob,
        Asset,
        Evidence,
        ForewarningSnapshot,
        InterventionResult,
        Observation,
        RiskEvent,
        RiskEventEvidence,
        RuleTrace,
    )
    from backend.service.event_service import intervene
    from backend.service.recovery_scheduler_service import advance_one_due_event
    from backend.service.serialization import aware, loads
    from contracts.v1.ruleset import load_ruleset

    await init_tables()
    await init_default_config()
    resident_id = "resident-v13-acceptance"
    task_results = []
    agent_statuses: list[str] = []
    transitions = {"orange_created": False, "observing_seen": False, "final_status": None}

    async with AsyncSessionLocal() as db:
        trigger_task = await _process_recording(
            db,
            input_path=args.input,
            captured_at=timeline["captured_at"],
            resident_id=resident_id,
            private_root=args.private_root,
            camera_position_id=args.camera_position_id,
            retention_until=args.retention_until,
        )
        task_results.append(trigger_task)
        events = (await db.execute(
            select(RiskEvent).where(RiskEvent.resident_id == resident_id)
        )).scalars().all()

        if args.expected_outcome == EVENT_RESOLVED:
            if len(events) != 1 or events[0].risk_level != "ORANGE":
                raise AcceptanceError("RISK_RECORDING_DID_NOT_CREATE_ONE_ORANGE_EVENT")
            event = events[0]
            transitions["orange_created"] = True
            agent_statuses.extend(await _drain_agent_jobs(db))
            intervention = await intervene(db, event.event_id)
            if intervention.get("tool_name") != "mock_voice" or intervention.get("simulated") is not True:
                raise AcceptanceError("INTERVENTION_CAPABILITY_BOUNDARY_VIOLATED")
            agent_statuses.extend(await _drain_agent_jobs(db))

            recovery_task = await _process_recording(
                db,
                input_path=args.recovery_input,
                captured_at=timeline["recovery_at"],
                resident_id=resident_id,
                private_root=args.private_root,
                camera_position_id=args.camera_position_id,
                retention_until=args.retention_until,
            )
            task_results.append(recovery_task)
            await db.refresh(event)
            transitions["observing_seen"] = event.status == "OBSERVING"
            observation_seconds = load_ruleset().thresholds["observation_seconds"]
            if timeline["resolve_at"] < timeline["recovery_at"] + timedelta(seconds=observation_seconds):
                raise AcceptanceError(
                    f"resolve-at must be at least {observation_seconds:g}s after recovery-captured-at"
                )
            transition = await advance_one_due_event(db, now=timeline["resolve_at"])
            if transition is None:
                raise AcceptanceError("RECOVERY_SCHEDULER_DID_NOT_ADVANCE_EVENT")
            await db.refresh(event)
            transitions["final_status"] = event.status
            agent_statuses.extend(await _drain_agent_jobs(db))

        models = (
            ("assets", Asset),
            ("observations", Observation),
            ("evidences", Evidence),
            ("forewarning_snapshots", ForewarningSnapshot),
            ("rule_traces", RuleTrace),
            ("risk_events", RiskEvent),
            ("event_evidence_links", RiskEventEvidence),
            ("agent_jobs", AgentExplanationJob),
            ("intervention_results", InterventionResult),
        )
        counts = {
            name: int((await db.execute(select(func.count()).select_from(model))).scalar_one())
            for name, model in models
        }
        rows = {
            name: (await db.execute(select(model))).scalars().all()
            for name, model in models
        }
        asset_ids = {item.asset_id for item in rows["assets"]}
        observation_ids = {item.observation_id for item in rows["observations"]}
        evidence_ids = {item.evidence_id for item in rows["evidences"]}
        event_ids = {item.event_id for item in rows["risk_events"]}
        intervention_ids = {item.result_id for item in rows["intervention_results"]}
        reference_checks = {
            "observation_to_asset": all(
                not item.asset_id or item.asset_id in asset_ids for item in rows["observations"]
            ),
            "evidence_to_observation": all(
                set(loads(item.observation_ids, [])) <= observation_ids for item in rows["evidences"]
            ),
            "snapshot_to_evidence_observation": all(
                set(loads(item.evidence_ids, [])) <= evidence_ids
                and set(loads(item.observation_ids, [])) <= observation_ids
                for item in rows["forewarning_snapshots"]
            ),
            "rule_trace_to_evidence_event": all(
                (not item.evidence_id or item.evidence_id in evidence_ids)
                and (not item.event_id or item.event_id in event_ids)
                for item in rows["rule_traces"]
            ),
            "event_evidence_link": all(
                item.event_id in event_ids and item.evidence_id in evidence_ids
                for item in rows["event_evidence_links"]
            ),
            "agent_intervention_to_event": all(
                item.event_id in event_ids for item in rows["agent_jobs"]
            ) and all(item.event_id in event_ids for item in rows["intervention_results"]),
            "snapshot_to_event_intervention": all(
                (not item.event_id or item.event_id in event_ids)
                and (not item.intervention_result_id or item.intervention_result_id in intervention_ids)
                for item in rows["forewarning_snapshots"]
            ),
        }
        intervention_row = rows["intervention_results"][-1] if rows["intervention_results"] else None
        result = {
            "expected_outcome": args.expected_outcome,
            "input_media_count": 2 if args.expected_outcome == EVENT_RESOLVED else 1,
            "task_statuses": [task.status for task in task_results],
            "module_results": [_module_results(task) for task in task_results],
            "counts": counts,
            "reference_integrity": {
                "passed": all(reference_checks.values()),
                "checks": reference_checks,
            },
            "transitions": transitions,
            "snapshot_phases": sorted({item.phase for item in rows["forewarning_snapshots"]}),
            "agent_statuses": [item.status for item in rows["agent_jobs"]] or agent_statuses,
            "intervention": {} if intervention_row is None else {
                "tool_name": intervention_row.tool_name,
                "simulated": intervention_row.simulated,
                "resolved": intervention_row.resolved,
                "risk_after": intervention_row.risk_after,
            },
            "latest_snapshot": None,
        }
        latest = max(
            rows["forewarning_snapshots"],
            key=lambda item: (aware(item.evaluated_at), item.id),
            default=None,
        )
        if latest is not None:
            result["latest_snapshot"] = {
                "assessment_status": latest.assessment_status,
                "confidence_level": latest.confidence_level,
                "baseline_status": latest.baseline_status,
                "source_mode": latest.source_mode,
                "simulated": latest.simulated,
                "degradation_reasons": loads(latest.degradation_payload, []),
            }
        result["errors"] = acceptance_errors(result)
        result["acceptance_status"] = "PASS" if not result["errors"] else "FAIL"
        return {"resident_id": resident_id, **result}


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        timeline = validate_inputs(args)
        os.environ.update({
            "YINGMU_ENV": "mock",
            "YINGMU_DB_PATH": str(args.database.resolve()),
            "YINGMU_PRIVATE_MEDIA_ROOT": str(args.private_root.resolve()),
            "YINGMU_GAIT_ADAPTER": "contracts.v1.gait_adapter:run",
            "YINGMU_TRAJECTORY_ADAPTER": "adapters.trajectory_adapter:run",
            "YINGMU_SCENE_CONFIG_ID": args.scene_config_id,
            "YINGMU_SCENE_CONFIG_DIR": str((ROOT / "scene-calibrations").resolve()),
            "YINGMU_CAMERA_POSITION_ID": args.camera_position_id,
            "YINGMU_LOCATION": "living_room",
            "YINGMU_ALGORITHM_TIMEOUT_SECONDS": "120",
            "EZVIZ_VOICE_VERIFIED": "false",
            "AGENT_LLM_API_KEY": "",
            "EZVIZ_API_KEY": "",
        })
        backend = asyncio.run(run_backend(args, timeline))

        from fastapi.testclient import TestClient
        from backend.main import app

        resident_id = backend.pop("resident_id")
        with TestClient(app) as client:
            latest_response = client.get(f"/api/v1/residents/{resident_id}/forewarning/latest")
            history_response = client.get(f"/api/v1/residents/{resident_id}/forewarning")
            baseline_response = client.get(f"/api/v1/residents/{resident_id}/baseline")
            event_response = client.get("/api/v1/events", params={"resident_id": resident_id})
            event_forewarning_status = None
            events = event_response.json() if event_response.status_code == 200 else []
            if events:
                event_forewarning_status = client.get(
                    f"/api/v1/events/{events[0]['event_id']}/forewarning"
                ).status_code
        http_statuses = {
            "latest": latest_response.status_code,
            "history": history_response.status_code,
            "baseline": baseline_response.status_code,
            "events": event_response.status_code,
            "event_forewarning": event_forewarning_status,
        }
        http_ok = all(status == 200 for status in http_statuses.values() if status is not None)
        if not http_ok:
            backend["errors"].append("one or more read APIs failed")
            backend["acceptance_status"] = "FAIL"
        report = {
            "schema_version": "v13-closed-loop-acceptance/2.0",
            "expected_outcome": args.expected_outcome,
            "input_media_count": backend["input_media_count"],
            "observation_clock": "RECORDED_TIMELINE",
            "provenance": {
                "source_mode": "RECORDED_REPLAY",
                "simulated": True,
                "pixel_source": "AUTHORIZED_REAL_RECORDING",
            },
            "backend": backend,
            "http_api": {"statuses": http_statuses, "passed": http_ok},
            "claim_boundary": "engineering forewarning index, not a fall probability or clinical validation",
            "privacy": "No media name, path, hash, participant, device identifier or pose coordinates are included.",
        }
        if args.report:
            write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if backend["acceptance_status"] == "PASS" else 1
    except (AcceptanceError, OSError, ValueError) as exc:
        report = {
            "schema_version": "v13-closed-loop-acceptance/2.0",
            "expected_outcome": getattr(args, "expected_outcome", None),
            "acceptance_status": "FAIL",
            "error_code": str(exc),
            "contains_private_media_details": False,
        }
        if getattr(args, "report", None):
            write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
