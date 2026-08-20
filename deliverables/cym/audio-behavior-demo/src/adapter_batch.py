"""Validation and construction for the AlgorithmJob/AdapterBatch contract."""

from datetime import datetime

from evidence import validate_evidence_collection
from observation import validate_observation_collection


class AdapterBatchValidationError(ValueError):
    """Raised when a worker input or algorithm response is incomplete."""


def _require_string(payload, field_name):
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise AdapterBatchValidationError(f"{field_name} must be a non-empty string")
    return value


def _parse_timestamp(value, field_name):
    if not isinstance(value, str):
        raise AdapterBatchValidationError(f"{field_name} must be an ISO 8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AdapterBatchValidationError(f"{field_name} is not a valid ISO 8601 timestamp") from error
    if parsed.utcoffset() is None:
        raise AdapterBatchValidationError(f"{field_name} must include a timezone")
    return parsed


def validate_algorithm_job(job):
    if not isinstance(job, dict):
        raise AdapterBatchValidationError("AlgorithmJob must be an object")
    for field_name in ("job_id", "asset_id", "media_locator", "captured_at"):
        _require_string(job, field_name)
    _parse_timestamp(job["captured_at"], "captured_at")
    return job


def build_adapter_batch(job, *, observations, evidences, adapter_version, started_at, completed_at):
    """Build a public response without leaking the internal media_locator."""
    validate_algorithm_job(job)
    started = _parse_timestamp(started_at, "started_at")
    completed = _parse_timestamp(completed_at, "completed_at")
    if completed < started:
        raise AdapterBatchValidationError("completed_at cannot be earlier than started_at")
    if not isinstance(adapter_version, str) or not adapter_version.strip():
        raise AdapterBatchValidationError("adapter_version must be a non-empty string")
    observations = validate_observation_collection(observations)
    evidences = validate_evidence_collection(evidences)
    observation_ids = {item["observation_id"] for item in observations}
    for evidence in evidences:
        missing = set(evidence["observation_ids"]) - observation_ids
        if missing:
            raise AdapterBatchValidationError(
                f"Evidence references missing Observation IDs: {sorted(missing)}"
            )
    return {
        "schema_version": "1.0",
        "job_id": job["job_id"],
        "asset_id": job["asset_id"],
        "adapter_version": adapter_version,
        "started_at": started_at,
        "completed_at": completed_at,
        "observations": observations,
        "evidences": evidences,
    }
