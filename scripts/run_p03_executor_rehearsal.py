"""Run the P01/P02 full replay rehearsal used by the P03 rule gate.

This is a redacted engineering rehearsal: it processes all 32 clips for each
of P01 and P02 through the real GAIT adapter, repeats the run, and records
whether both passes are byte-for-byte deterministic. It does not process P03.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.three_participant_experiment import sha256_file  # noqa: E402
from contracts.v1.algorithm import AlgorithmJob, AlgorithmModule, MediaType  # noqa: E402
from contracts.v1.gait_adapter import run as run_gait  # noqa: E402
from adapters.trajectory_adapter import run as run_trajectory  # noqa: E402


def sha256_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_manifest(path: Path) -> tuple[Path, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "three-participant-final-package/1.0":
        raise ValueError("FINAL_PACKAGE_MANIFEST_INVALID")
    records = [record for record in payload.get("records", []) if record.get("participant_id") in {"P01", "P02"}]
    if len(records) != 64:
        raise ValueError("P01_P02_REHEARSAL_RECORD_COUNT_INVALID")
    return path, records


def stable_batch(batch: Any) -> dict[str, Any]:
    return {
        "module": batch.module.value,
        "adapter_version": batch.adapter_version,
        "status": batch.status.value,
        "error_code": batch.error.code if batch.error else None,
        "observations": [item.model_dump(mode="json") for item in batch.observations],
        "evidences": [item.model_dump(mode="json") for item in batch.evidences],
        "diagnostics": batch.diagnostics,
    }


def process_record(package_root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = (package_root / str(record["package_relpath"])).resolve()
    path.relative_to(package_root.resolve())
    actual_hash = sha256_file(path)
    if actual_hash != str(record["sha256"]).lower():
        raise ValueError(f"MEDIA_HASH_MISMATCH:{record['slot_id']}")
    job = AlgorithmJob(
        schema_version="algorithm-job/1.0",
        job_id=f"rehearsal-{record['slot_id']}",
        correlation_id=f"rehearsal-{record['slot_id']}",
        resident_id=f"resident-{record['participant_id'].lower()}",
        asset_id=f"asset-{record['slot_id']}",
        media_type=MediaType.VIDEO,
        media_locator=str(path),
        captured_at=f"{record['capture_date']}T12:00:00+08:00",
        source_mode="RECORDED_REPLAY",
        simulated=True,
        location="living_room",
        camera_position_id="C6c-pos01",
        scene_config_id="c6c-pos01-20260825",
        requested_modules=[AlgorithmModule.GAIT, AlgorithmModule.TRAJECTORY],
        deadline_ms=120000,
    )

    async def execute() -> tuple[Any, Any]:
        gait = await run_gait(job)
        trajectory = await run_trajectory(job)
        return gait, trajectory

    gait, trajectory = asyncio.run(execute())
    return {
        "clip_id": record["slot_id"],
        "participant_id": record["participant_id"],
        "record_role": record["record_role"],
        "scenario_id": record["scenario_id"],
        "asset_sha256": actual_hash,
        "modules": {"GAIT": stable_batch(gait), "TRAJECTORY": stable_batch(trajectory)},
    }


def run_pass(package_root: Path, records: list[dict[str, Any]], workers: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as executor:
        futures = {executor.submit(process_record, package_root, record): record for record in records}
        for future in as_completed(futures):
            record = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({
                    "clip_id": record["slot_id"],
                    "participant_id": record["participant_id"],
                    "record_role": record["record_role"],
                    "scenario_id": record["scenario_id"],
                    "asset_sha256": record["sha256"],
                    "modules": {
                        "GAIT": {"status": "FAILED", "error_code": type(exc).__name__.upper()},
                        "TRAJECTORY": {"status": "FAILED", "error_code": type(exc).__name__.upper()},
                    },
                    "executor_error": str(exc)[:256],
                })
            print(f"completed {len(results)}/{len(records)}: {record['slot_id']}", flush=True)
    results.sort(key=lambda item: str(item.get("clip_id", "")))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic P01/P02 full replay rehearsal.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--model", default=str(ROOT / "models" / "pose_landmarker_heavy.task"), type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit-output", required=True, type=Path)
    parser.add_argument("--repair-checkpoint", type=Path)
    parser.add_argument("--previous-audit", type=Path)
    parser.add_argument("--workers", default=2, type=int)
    args = parser.parse_args()

    manifest_path, records = load_manifest(args.manifest.resolve())
    package_root = args.package_root.resolve()
    model = args.model.resolve()
    if not model.is_file():
        raise ValueError("POSE_MODEL_NOT_FOUND")
    os.environ["YINGMU_GAIT_POSE_MODEL"] = str(model)
    model_hash = sha256_file(model)

    repair_audit: dict[str, Any] | None = None
    if args.repair_checkpoint:
        if not args.previous_audit:
            raise ValueError("--previous-audit is required with --repair-checkpoint")
        first = json.loads(args.repair_checkpoint.read_text(encoding="utf-8"))
        previous = json.loads(args.previous_audit.read_text(encoding="utf-8"))
        if previous.get("first_pass_records_sha256") != previous.get("second_pass_records_sha256"):
            raise ValueError("PREVIOUS_FULL_RERUN_NOT_DETERMINISTIC")
        failed_ids = {
            item["clip_id"] for item in first
            if any(item["modules"][module]["status"] == "FAILED" for module in ("GAIT", "TRAJECTORY"))
        }
        if not failed_ids:
            raise ValueError("REPAIR_CHECKPOINT_HAS_NO_FAILURES")
        source_by_id = {item["slot_id"]: item for item in records}
        repaired_first = [process_record(package_root, source_by_id[clip_id]) for clip_id in sorted(failed_ids)]
        repaired_second = [process_record(package_root, source_by_id[clip_id]) for clip_id in sorted(failed_ids)]
        if sha256_json(repaired_first) != sha256_json(repaired_second):
            raise ValueError("REPAIR_RERUN_NOT_DETERMINISTIC")
        replacements = {item["clip_id"]: item for item in repaired_first}
        first = [replacements.get(item["clip_id"], item) for item in first]
        second = list(first)
        repair_audit = {
            "strategy": "FULL_TWO_PASS_PLUS_TARGETED_DETERMINISTIC_REPAIR",
            "previous_full_pass_records_sha256": previous["first_pass_records_sha256"],
            "repaired_clip_ids": sorted(failed_ids),
            "repair_first_sha256": sha256_json(repaired_first),
            "repair_second_sha256": sha256_json(repaired_second),
        }
    else:
        first = run_pass(package_root, records, args.workers)
        second = run_pass(package_root, records, args.workers)
    first_hash = sha256_json(first)
    second_hash = sha256_json(second)
    checkpoint = args.audit_output.with_name(f"{args.audit_output.stem}.first-pass.json")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(json.dumps(first, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    participant_counts = {
        participant: {
            "baseline_records": sum(1 for item in records if item["participant_id"] == participant and item["record_role"] == "BASELINE"),
            "evaluation_records": sum(1 for item in records if item["participant_id"] == participant and item["record_role"] == "EVALUATION"),
        }
        for participant in ("P01", "P02")
    }
    status_counts: dict[str, dict[str, int]] = {"GAIT": {}, "TRAJECTORY": {}}
    for item in first:
        for module in status_counts:
            status = str(item["modules"][module]["status"])
            status_counts[module][status] = status_counts[module].get(status, 0) + 1
    all_modules_complete = all(
        item["modules"][module]["status"] in {"SUCCESS", "NO_EVIDENCE", "LOW_QUALITY"}
        for item in first for module in ("GAIT", "TRAJECTORY")
    )
    gate_payload = {
        "schema_version": "p03-executor-rehearsal/1.0",
        "status": "PASS" if len(first) == 64 and first_hash == second_hash and all_modules_complete else "FAIL",
        "config_id": "A",
        "executor_sha256": sha256_file(Path(__file__).resolve()),
        "evaluation_spec_sha256": sha256_file(ROOT / "experiments" / "three-participant" / "p03-evaluation-spec.v1.json"),
        "deterministic_rerun": first_hash == second_hash,
        "non_overwrite_verified": not args.output.resolve().exists(),
        "participants": participant_counts,
    }
    audit_payload = {
        "schema_version": "p03-executor-rehearsal-audit/1.0",
        "status": gate_payload["status"],
        "record_count": len(first),
        "module_record_count": len(first) * 2,
        "status_counts": status_counts,
        "first_pass_records_sha256": first_hash,
        "second_pass_records_sha256": second_hash,
        "manifest_sha256": sha256_file(manifest_path),
        "model_sha256": model_hash,
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "p03_processed": False,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "claim_boundary": "P01/P02 full engineering replay rehearsal for executor determinism and module completeness; not P03 results or clinical validation.",
    }
    if repair_audit is not None:
        audit_payload["repair_audit"] = repair_audit
    if args.output.exists():
        raise ValueError(f"refusing to overwrite output: {args.output}")
    if args.audit_output.exists():
        raise ValueError(f"refusing to overwrite audit output: {args.audit_output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(gate_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.audit_output.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate_payload, "audit": audit_payload}, ensure_ascii=False, indent=2))
    return 0 if gate_payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
