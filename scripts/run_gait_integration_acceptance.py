"""Generate auditable gait adapter and backend integration evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.schemas.asset import AssetCreate
from contracts.v1.algorithm import (
    AdapterBatch,
    AdapterStatus,
    AlgorithmJob,
    AlgorithmModule,
    MediaType,
    validate_batch_for_job,
)
from contracts.v1.gait_adapter import run as run_gait_adapter
from contracts.v1.gait_video import VIDEO_SUFFIXES, _resolve_model_path


REPORT_VERSION = "gait-integration-acceptance/1.0"
JsonRequester = Callable[[str, str, dict[str, Any] | None, float], dict[str, Any]]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _file_manifest(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {
        "sha256": digest.hexdigest(),
        "byte_size": size,
        "suffix": path.suffix.lower(),
        "path_retained_in_report": False,
    }


def _request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return {
                "method": method,
                "url": url,
                "status_code": response.status,
                "body": json.loads(raw) if raw else None,
            }
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body: Any = json.loads(raw)
        except json.JSONDecodeError:
            body = raw
        return {"method": method, "url": url, "status_code": exc.code, "body": body}
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Unable to reach {url}: {exc}") from exc


def _check(name: str, passed: bool, detail: Any) -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}


def _adapter_checks(
    job: AlgorithmJob,
    batch: AdapterBatch,
    manifest: dict[str, Any],
    model_manifest: dict[str, Any] | None,
    expected_status: AdapterStatus,
) -> list[dict[str, Any]]:
    try:
        validate_batch_for_job(batch, job)
        pair_error = None
    except ValueError as exc:
        pair_error = str(exc)
    is_video = manifest["suffix"] in VIDEO_SUFFIXES
    elapsed_ms = round((batch.completed_at - batch.started_at).total_seconds() * 1000)
    return [
        _check("media_hash_recorded", len(manifest["sha256"]) == 64, manifest["sha256"]),
        _check("real_video_input", is_video, manifest["suffix"]),
        _check(
            "pose_model_hash_recorded",
            bool(model_manifest and len(model_manifest["sha256"]) == 64),
            model_manifest["sha256"] if model_manifest else None,
        ),
        _check("job_batch_consistent", pair_error is None, pair_error or batch.job_id),
        _check(
            "completed_within_deadline",
            elapsed_ms <= job.deadline_ms,
            {"elapsed_ms": elapsed_ms, "deadline_ms": job.deadline_ms},
        ),
        _check(
            "expected_adapter_status",
            batch.status == expected_status,
            {"expected": expected_status.value, "actual": batch.status.value},
        ),
        _check(
            "success_has_outputs",
            batch.status != AdapterStatus.SUCCESS or bool(batch.observations and batch.evidences),
            {"observations": len(batch.observations), "evidences": len(batch.evidences)},
        ),
    ]


def _asset_payload(
    job: AlgorithmJob,
    manifest: dict[str, Any],
    authorization_record_id: str,
    retention_until: str,
    device_ref: str,
) -> dict[str, Any]:
    if manifest["suffix"] != ".mp4":
        raise ValueError("backend E2E acceptance currently requires an MP4 asset")
    payload = {
        "asset_id": job.asset_id,
        "title": "Redacted authorized C6c gait acceptance clip",
        "source_mode": job.source_mode.value,
        "simulated": job.simulated,
        "stream_url": None,
        "fallback_url": None,
        "fallback_kind": "LOCAL_AUTHORIZED_CLIP",
        "available": False,
        "verification_status": "VERIFIED",
        "captured_at": job.captured_at.isoformat(),
        "notice": "Private media path omitted; verify with content_sha256.",
        "device_ref": device_ref,
        "device_model": "EZVIZ_C6C",
        "camera_position_id": job.camera_position_id,
        "authorization_status": "AUTHORIZED",
        "authorization_record_id": authorization_record_id,
        "retention_until": retention_until,
        "content_sha256": manifest["sha256"],
        "content_type": "video/mp4",
        "byte_size": manifest["byte_size"],
    }
    return AssetCreate.model_validate(payload).model_dump(mode="json")


def _submit_backend(
    backend_url: str,
    asset: dict[str, Any],
    batch: AdapterBatch,
    timeout: float,
    requester: JsonRequester,
) -> dict[str, Any]:
    base = backend_url.rstrip("/") + "/api/v1"
    observations = [item.model_dump(mode="json") for item in batch.observations]
    evidences = [item.model_dump(mode="json") for item in batch.evidences]

    def call(method: str, url: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        try:
            return requester(method, url, payload, timeout)
        except (OSError, RuntimeError) as exc:
            return {
                "method": method,
                "url": url,
                "status_code": 0,
                "body": {"error": str(exc)},
            }

    first = [call("POST", f"{base}/assets", asset)]
    first.extend(call("POST", f"{base}/observations", item) for item in observations)
    first.extend(call("POST", f"{base}/evidence", item) for item in evidences)

    duplicate = [call("POST", f"{base}/assets", asset)]
    duplicate.extend(call("POST", f"{base}/observations", item) for item in observations)
    duplicate.extend(call("POST", f"{base}/evidence", item) for item in evidences)

    event_ids = sorted({
        result.get("body", {}).get("evaluation", {}).get("event_id")
        for result in first
        if isinstance(result.get("body"), dict)
    } - {None})
    event_details = [
        call("GET", f"{base}/events/{event_id}", None)
        for event_id in event_ids
    ]
    return {"first_write": first, "idempotent_retry": duplicate, "event_details": event_details}


def _backend_checks(receipts: dict[str, Any], batch: AdapterBatch) -> list[dict[str, Any]]:
    first_codes = [item["status_code"] for item in receipts["first_write"]]
    duplicate_codes = [item["status_code"] for item in receipts["idempotent_retry"]]
    details = [
        item["body"] for item in receipts["event_details"]
        if item["status_code"] == 200 and isinstance(item.get("body"), dict)
    ]
    archived_evidence = {
        evidence_id
        for detail in details
        for evidence_id in detail.get("evidence_ids", [])
    }
    submitted_evidence = {item.evidence_id for item in batch.evidences}
    return [
        _check("backend_first_write_201", bool(first_codes) and all(code == 201 for code in first_codes), first_codes),
        _check("backend_idempotent_retry_200", bool(duplicate_codes) and all(code == 200 for code in duplicate_codes), duplicate_codes),
        _check("risk_event_returned", bool(details), [item.get("event_id") for item in details]),
        _check(
            "event_contains_submitted_evidence",
            bool(archived_evidence & submitted_evidence),
            sorted(archived_evidence & submitted_evidence),
        ),
        _check(
            "rule_trace_archived",
            any(detail.get("rule_traces") for detail in details),
            sum(len(detail.get("rule_traces", [])) for detail in details),
        ),
    ]


def _redacted_job(job: AlgorithmJob, manifest: dict[str, Any]) -> dict[str, Any]:
    payload = job.model_dump(mode="json")
    payload["media_locator"] = f"<redacted:sha256:{manifest['sha256']}>"
    return payload


async def run_acceptance(
    *,
    media_path: Path,
    output_dir: Path,
    job: AlgorithmJob,
    expected_status: AdapterStatus = AdapterStatus.SUCCESS,
    backend_url: str | None = None,
    authorization_record_id: str | None = None,
    retention_until: str | None = None,
    device_ref: str = "redacted-c6c-device",
    timeout: float = 15.0,
    requester: JsonRequester = _request_json,
) -> dict[str, Any]:
    if not media_path.is_file():
        raise ValueError(f"media input does not exist: {media_path}")
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    if backend_url and (not authorization_record_id or not retention_until):
        raise ValueError("backend E2E requires authorization_record_id and retention_until")
    manifest = _file_manifest(media_path)
    model_manifest = _file_manifest(_resolve_model_path()) if manifest["suffix"] in VIDEO_SUFFIXES else None
    asset = None
    if backend_url:
        asset = _asset_payload(job, manifest, authorization_record_id, retention_until, device_ref)
    batch = AdapterBatch.model_validate(await run_gait_adapter(job))
    checks = _adapter_checks(job, batch, manifest, model_manifest, expected_status)

    output_dir.mkdir(parents=True)
    _write_json(output_dir / "media_manifest.json", manifest)
    if model_manifest:
        _write_json(output_dir / "pose_model_manifest.json", model_manifest)
    _write_json(output_dir / "algorithm_job.redacted.json", _redacted_job(job, manifest))
    _write_json(output_dir / "adapter_batch.json", batch.model_dump(mode="json"))

    receipts = None
    if backend_url:
        _write_json(output_dir / "asset.json", asset)
        receipts = _submit_backend(backend_url, asset, batch, timeout, requester)
        _write_json(output_dir / "backend_receipts.json", receipts)
        checks.extend(_backend_checks(receipts, batch))

    check_by_name = {item["name"]: item["passed"] for item in checks}
    contract_pass = all(check_by_name[name] for name in (
        "media_hash_recorded",
        "job_batch_consistent",
        "completed_within_deadline",
        "expected_adapter_status",
        "success_has_outputs",
    ))
    adapter_pass = contract_pass and all(check_by_name[name] for name in (
        "real_video_input",
        "pose_model_hash_recorded",
    ))
    if backend_url:
        backend_pass = all(
            item["passed"] for item in checks
            if item["name"].startswith("backend_") or item["name"] in {
                "risk_event_returned", "event_contains_submitted_evidence", "rule_trace_archived",
            }
        )
        verdict = "BACKEND_E2E_PASS" if adapter_pass and backend_pass else "FAIL"
    elif adapter_pass:
        verdict = "ADAPTER_PASS"
    elif contract_pass:
        verdict = "CONTRACT_PASS"
    else:
        verdict = "FAIL"

    report = {
        "schema_version": REPORT_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "verdict": verdict,
        "job_id": job.job_id,
        "media": manifest,
        "checks": checks,
        "artifacts": {
            "job": "algorithm_job.redacted.json",
            "batch": "adapter_batch.json",
            "media_manifest": "media_manifest.json",
            "pose_model_manifest": "pose_model_manifest.json" if model_manifest else None,
            "backend_receipts": "backend_receipts.json" if receipts else None,
        },
    }
    _write_json(output_dir / "verification_report.json", report)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run auditable gait integration acceptance.")
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id", default=uuid.uuid4().hex[:12])
    parser.add_argument("--captured-at", required=True, help="ISO 8601 timestamp with timezone")
    parser.add_argument("--resident-id", required=True)
    parser.add_argument("--location", default="living_room")
    parser.add_argument("--camera-position-id", required=True)
    parser.add_argument("--scene-config-id", required=True)
    parser.add_argument("--expected-status", choices=[item.value for item in AdapterStatus], default="SUCCESS")
    parser.add_argument("--backend-url")
    parser.add_argument("--authorization-record-id")
    parser.add_argument("--retention-until")
    parser.add_argument("--device-ref", default="redacted-c6c-device")
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    media = args.media.resolve()
    output_dir = args.output_dir or Path("artifacts") / f"gait-integration-{args.run_id}"
    job = AlgorithmJob(
        schema_version="algorithm-job/1.0",
        job_id=f"job-gait-{args.run_id}",
        correlation_id=f"corr-gait-{args.run_id}",
        resident_id=args.resident_id,
        asset_id=f"asset-gait-{args.run_id}",
        media_type=MediaType.VIDEO,
        media_locator=str(media),
        captured_at=args.captured_at,
        source_mode="RECORDED_REPLAY",
        simulated=True,
        location=args.location,
        camera_position_id=args.camera_position_id,
        scene_config_id=args.scene_config_id,
        requested_modules=[AlgorithmModule.GAIT],
        deadline_ms=120000,
    )
    try:
        report = asyncio.run(run_acceptance(
            media_path=media,
            output_dir=output_dir,
            job=job,
            expected_status=AdapterStatus(args.expected_status),
            backend_url=args.backend_url,
            authorization_record_id=args.authorization_record_id,
            retention_until=args.retention_until,
            device_ref=args.device_ref,
            timeout=args.timeout,
        ))
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"GAIT_ACCEPTANCE_FAILED: {exc}") from exc
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["verdict"] == "FAIL":
        sys.exit(1)


if __name__ == "__main__":
    main()
