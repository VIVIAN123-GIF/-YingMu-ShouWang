"""Validate and submit the Observation-complete golden package to FastAPI."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_PACKAGE = Path("deliverables/zy/pose-demo/integration/golden_30s_fall_evidence.json")


def load_package(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def package_parts(payload: dict[str, Any]) -> tuple[str, list[dict], list[dict], list[dict]]:
    status = payload.get("acceptance_status") or payload.get("package_status") or "PENDING_ASSET"
    assets = payload.get("asset_manifest") or ([payload["asset"]] if payload.get("asset") else [])
    observations = payload.get("observations") or []
    evidences = payload.get("evidences") or payload.get("evidence") or []
    return status, assets, observations, evidences


def validate_package(payload: dict[str, Any], require_ready: bool = True) -> None:
    status, assets, observations, evidences = package_parts(payload)
    if require_ready and status != "READY":
        raise ValueError("package is PENDING_ASSET; authorized C6c assets are required")
    asset_by_id = {item["asset_id"]: item for item in assets}
    if not asset_by_id or len(asset_by_id) != len(assets):
        raise ValueError("package must contain unique assets")
    if require_ready:
        for asset in assets:
            if asset.get("source_mode") != "RECORDED_REPLAY" or asset.get("device_model") != "EZVIZ_C6C":
                raise ValueError(f"{asset['asset_id']} is not a recorded EZVIZ_C6C asset")
            if asset.get("authorization_status") != "AUTHORIZED" or not asset.get("authorization_record_id"):
                raise ValueError(f"{asset['asset_id']} is not authorized")
            if not asset.get("device_ref") or not asset.get("camera_position_id") or not asset.get("retention_until"):
                raise ValueError(f"{asset['asset_id']} lacks device/position/retention provenance")
    observation_by_id = {item["observation_id"]: item for item in observations}
    if len(observation_by_id) != len(observations):
        raise ValueError("duplicate observation_id in golden package")
    for evidence in evidences:
        linked = []
        for observation_id in evidence.get("observation_ids", []):
            if observation_id not in observation_by_id:
                raise ValueError(f"{evidence['evidence_id']} references missing Observation {observation_id}")
            linked.append(observation_by_id[observation_id])
        if not linked:
            raise ValueError(f"{evidence['evidence_id']} has no Observation")
        for observation in linked:
            for field in ("resident_id", "source_mode", "simulated"):
                if observation[field] != evidence[field]:
                    raise ValueError(f"{evidence['evidence_id']} and {observation['observation_id']} disagree on {field}")
            if observation.get("asset_id") not in asset_by_id:
                raise ValueError(f"{observation['observation_id']} cannot be traced to package asset")
    recovered = next((item for item in evidences if item["evidence_type"] == "posture_recovered"), None)
    if recovered:
        features = {observation_by_id[item]["feature_name"] for item in recovered["observation_ids"]}
        if features != {"stable_posture_duration", "stable_trunk_angle_deg"}:
            raise ValueError("posture_recovered must reference duration and angle Observations")
        if recovered["baseline_value"] != 15.0:
            raise ValueError("posture_recovered.baseline_value must be 15 seconds")


def request_json(base_url: str, path: str, request_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json", "X-Request-ID": request_id},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return {"status_code": response.status, "body": json.loads(response.read().decode("utf-8"))}
    except urllib.error.HTTPError as error:
        response_body = json.loads(error.read().decode("utf-8"))
        return {"status_code": error.code, "body": response_body}


def redacted_request(body: Any, key: str = "") -> Any:
    forbidden = {"stream_url", "fallback_url", "local_path", "source_path", "access_token", "app_secret", "password"}
    if key.lower() in forbidden and body:
        return "[REDACTED]"
    if isinstance(body, dict):
        return {child_key: redacted_request(value, child_key) for child_key, value in body.items()}
    if isinstance(body, list):
        return [redacted_request(value) for value in body]
    return body


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and submit the C6c golden package.")
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--allow-pending", action="store_true", help="development validation only; never marks real acceptance ready")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.allow_pending and not args.validate_only:
        parser.error("--allow-pending is restricted to --validate-only; pending packages cannot be submitted")
    payload = load_package(args.package)
    validate_package(payload, require_ready=not args.allow_pending)
    status, assets, observations, evidences = package_parts(payload)
    if args.validate_only:
        print(f"PASS: {len(observations)} Observations cover {len(evidences)} Evidences; status={status}")
        return

    exchanges = []
    failed = False
    event_ids = set()
    for operation, items, path, id_field in (
        ("asset", assets, "/api/v1/assets", "asset_id"),
        ("observation", observations, "/api/v1/observations", "observation_id"),
        ("evidence", evidences, "/api/v1/evidence", "evidence_id"),
    ):
        if failed:
            break
        for index, item in enumerate(items, start=1):
            response = request_json(args.base_url, path, f"package-{operation}-{index}", item)
            exchange = {
                "operation": operation,
                "id": item[id_field],
                "request": redacted_request(item),
                **response,
            }
            exchanges.append(exchange)
            if response["status_code"] >= 400:
                failed = True
                break
            evaluation = response["body"].get("evaluation", {}) if isinstance(response["body"], dict) else {}
            if evaluation.get("event_id"):
                event_ids.add(evaluation["event_id"])

    event_details = []
    if not failed:
        for index, event_id in enumerate(sorted(event_ids), start=1):
            event_details.append({
                "event_id": event_id,
                **request_json(args.base_url, f"/api/v1/events/{event_id}", f"package-event-{index}"),
            })
    result = {
        "submission_status": "FAILED" if failed else "PASS",
        "package_status": status,
        "asset_ids": [item["asset_id"] for item in assets],
        "event_ids": sorted(event_ids),
        "exchanges": exchanges,
        "event_details": event_details,
        "rule_traces": [
            trace
            for detail in event_details
            for trace in detail.get("body", {}).get("rule_traces", [])
        ],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failed:
        failed_exchange = exchanges[-1]
        print(f"FAILED: {failed_exchange['operation']} {failed_exchange['id']} HTTP {failed_exchange['status_code']} {failed_exchange['body']}")
        raise SystemExit(1)
    print(f"PASS: submitted {len(assets)} assets + {len(observations)} Observations + {len(evidences)} Evidences; events={sorted(event_ids)}")


if __name__ == "__main__":
    main()
