from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_FIELDS = {
    "schema_version",
    "evidence_id",
    "observation_ids",
    "resident_id",
    "timestamp",
    "risk_domain",
    "evidence_type",
    "severity",
    "confidence",
    "data_quality",
    "baseline_value",
    "current_value",
    "baseline_deviation",
    "time_scale",
    "location",
    "explanation",
    "adapter_version",
    "source_mode",
    "simulated",
}

REQUIRED_FALL_TYPES = {
    "rapid_rise",
    "slow_rise",
    "trunk_sway",
    "gait_instability",
    "relative_speed_change",
    "posture_recovered",
    "tracking_lost",
}

SOURCE_MODES = {"LIVE_DEVICE", "RECORDED_REPLAY", "PUBLIC_DATASET", "MOCK"}


def load_payload(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "evidence" in payload:
        evidence = payload["evidence"]
        if isinstance(evidence, list):
            return evidence
    if isinstance(payload, dict) and "evidence_type" in payload:
        return [payload]
    raise SystemExit(f"Unsupported evidence payload shape: {path}")


def validate_score(field: str, value: object, evidence_id: str) -> list[str]:
    if not isinstance(value, (int, float)):
        return [f"{evidence_id}: {field} must be numeric"]
    if not 0 <= float(value) <= 1:
        return [f"{evidence_id}: {field} must be between 0 and 1"]
    return []


def validate_evidence(evidence: dict[str, object]) -> list[str]:
    evidence_id = str(evidence.get("evidence_id", "<missing evidence_id>"))
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - set(evidence.keys()))
    if missing:
        errors.append(f"{evidence_id}: missing fields: {', '.join(missing)}")

    if evidence.get("schema_version") != "1.0":
        errors.append(f"{evidence_id}: schema_version must be 1.0")
    if evidence.get("risk_domain") != "FALL":
        errors.append(f"{evidence_id}: risk_domain must be FALL")
    if evidence.get("time_scale") not in {"SHORT", "MEDIUM", "LONG"}:
        errors.append(f"{evidence_id}: invalid time_scale")
    if evidence.get("source_mode") not in SOURCE_MODES:
        errors.append(f"{evidence_id}: invalid source_mode")
    if not isinstance(evidence.get("observation_ids"), list) or not evidence.get("observation_ids"):
        errors.append(f"{evidence_id}: observation_ids must be a non-empty list")
    if not isinstance(evidence.get("simulated"), bool):
        errors.append(f"{evidence_id}: simulated must be boolean")

    for score_field in ("severity", "confidence", "data_quality"):
        if score_field in evidence:
            errors.extend(validate_score(score_field, evidence[score_field], evidence_id))
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Fall Evidence JSON against Freeze v1.0 field rules.")
    parser.add_argument("payload", nargs="?", default="deliverables/zy/pose-demo/evidence/fall_evidence_batch.json")
    parser.add_argument("--require-all-fall-types", action="store_true")
    args = parser.parse_args()

    evidence_items = load_payload(Path(args.payload))
    errors: list[str] = []
    for item in evidence_items:
        errors.extend(validate_evidence(item))

    if args.require_all_fall_types:
        found = {str(item.get("evidence_type")) for item in evidence_items}
        missing = sorted(REQUIRED_FALL_TYPES - found)
        if missing:
            errors.append(f"missing required fall evidence types: {', '.join(missing)}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)

    print(f"Evidence schema OK: {len(evidence_items)} item(s)")


if __name__ == "__main__":
    main()
