from datetime import datetime


SCHEMA_VERSION = "1.0"
RISK_DOMAINS = {"FALL", "MENTAL", "FRAUD", "SYSTEM"}
TIME_SCALES = {"SHORT", "MEDIUM", "LONG"}
SOURCE_MODES = {"LIVE_DEVICE", "RECORDED_REPLAY", "PUBLIC_DATASET", "MOCK"}
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


class EvidenceValidationError(ValueError):
    pass


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_non_empty_string(evidence, field_name):
    value = evidence[field_name]
    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError(f"{field_name}必须是非空字符串")


def _validate_timestamp(value):
    if not isinstance(value, str):
        raise EvidenceValidationError("timestamp必须是ISO 8601字符串")

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceValidationError("timestamp不是有效的ISO 8601时间") from error

    if parsed.utcoffset() is None:
        raise EvidenceValidationError("timestamp必须包含时区")


def validate_evidence(evidence):
    if not isinstance(evidence, dict):
        raise EvidenceValidationError("Evidence必须是对象")

    missing_fields = sorted(REQUIRED_FIELDS - evidence.keys())
    if missing_fields:
        raise EvidenceValidationError(
            f"Evidence缺少必填字段：{', '.join(missing_fields)}"
        )

    if evidence["schema_version"] != SCHEMA_VERSION:
        raise EvidenceValidationError(
            f"schema_version必须是{SCHEMA_VERSION}"
        )

    for field_name in (
        "evidence_id",
        "resident_id",
        "evidence_type",
        "explanation",
        "adapter_version",
    ):
        _require_non_empty_string(evidence, field_name)

    observation_ids = evidence["observation_ids"]
    if (
        not isinstance(observation_ids, list)
        or not observation_ids
        or not all(isinstance(item, str) and item.strip() for item in observation_ids)
    ):
        raise EvidenceValidationError(
            "observation_ids必须是包含至少一个非空字符串的数组"
        )
    if len(observation_ids) != len(set(observation_ids)):
        raise EvidenceValidationError("observation_ids不能重复")

    _validate_timestamp(evidence["timestamp"])

    if evidence["risk_domain"] not in RISK_DOMAINS:
        raise EvidenceValidationError(
            f"risk_domain必须属于：{', '.join(sorted(RISK_DOMAINS))}"
        )
    if evidence["time_scale"] not in TIME_SCALES:
        raise EvidenceValidationError(
            f"time_scale必须属于：{', '.join(sorted(TIME_SCALES))}"
        )
    if evidence["source_mode"] not in SOURCE_MODES:
        raise EvidenceValidationError(
            f"source_mode必须属于：{', '.join(sorted(SOURCE_MODES))}"
        )

    for field_name in ("severity", "confidence", "data_quality"):
        value = evidence[field_name]
        if not _is_number(value) or not 0 <= value <= 1:
            raise EvidenceValidationError(f"{field_name}必须是0到1之间的数字")

    for field_name in (
        "baseline_value",
        "current_value",
        "baseline_deviation",
    ):
        value = evidence[field_name]
        if value is not None and not _is_number(value):
            raise EvidenceValidationError(f"{field_name}必须是数字或null")

    location = evidence["location"]
    if location is not None and not isinstance(location, str):
        raise EvidenceValidationError("location必须是字符串或null")

    if not isinstance(evidence["simulated"], bool):
        raise EvidenceValidationError("simulated必须是布尔值")

    return evidence


def validate_evidence_collection(evidence_items):
    if not isinstance(evidence_items, list):
        raise EvidenceValidationError("Evidence集合必须是数组")

    evidence_ids = []
    for evidence in evidence_items:
        validate_evidence(evidence)
        evidence_ids.append(evidence["evidence_id"])

    duplicate_ids = sorted(
        evidence_id
        for evidence_id in set(evidence_ids)
        if evidence_ids.count(evidence_id) > 1
    )
    if duplicate_ids:
        raise EvidenceValidationError(
            f"evidence_id重复：{', '.join(duplicate_ids)}"
        )

    return evidence_items


def build_evidence(
    *,
    evidence_id,
    observation_ids,
    resident_id,
    timestamp,
    risk_domain,
    evidence_type,
    severity,
    confidence,
    data_quality,
    baseline_value,
    current_value,
    baseline_deviation,
    time_scale,
    location,
    explanation,
    adapter_version,
    source_mode,
    simulated,
):
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "evidence_id": evidence_id,
        "observation_ids": observation_ids,
        "resident_id": resident_id,
        "timestamp": timestamp,
        "risk_domain": risk_domain,
        "evidence_type": evidence_type,
        "severity": severity,
        "confidence": confidence,
        "data_quality": data_quality,
        "baseline_value": baseline_value,
        "current_value": current_value,
        "baseline_deviation": baseline_deviation,
        "time_scale": time_scale,
        "location": location,
        "explanation": explanation,
        "adapter_version": adapter_version,
        "source_mode": source_mode,
        "simulated": simulated,
    }
    return validate_evidence(evidence)
