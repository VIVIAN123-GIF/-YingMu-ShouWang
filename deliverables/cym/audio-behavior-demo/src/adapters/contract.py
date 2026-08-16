"""Small, dependency-free implementation of the Worker adapter contract.

The adapters return dictionaries so the Worker can JSON encode the result
without knowing about this package's Python types.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from evidence import validate_evidence_collection
from observation import validate_observation_collection


SCHEMA_VERSION = "1.0"
ADAPTER_SCHEMA_VERSION = "adapter-batch/1.0"
AdapterBatch = dict[str, Any]
MODULES = {"TRAJECTORY", "LANGUAGE"}
STATUSES = {"SUCCESS", "NO_EVIDENCE", "LOW_QUALITY", "FAILED"}
SOURCE_MODES = {"LIVE_DEVICE", "RECORDED_REPLAY", "PUBLIC_DATASET", "MOCK"}
INTENTS = {"STABLE", "HELP", "UNCERTAIN"}


class ContractValidationError(ValueError):
    """Raised when a Worker request or adapter response is invalid."""


class AdapterError(dict):
    """JSON-compatible standard error object."""

    def __init__(self, code: str, message: str, *, retryable: bool = False, details: dict | None = None):
        super().__init__(code=code, message=message, retryable=retryable, details=details or {})


@dataclass(frozen=True)
class AlgorithmJob:
    job_id: str
    correlation_id: str
    resident_id: str
    asset_id: str
    media_type: str
    media_locator: str
    captured_at: str
    source_mode: str
    simulated: bool
    location: str | None = None
    camera_position_id: str | None = None
    scene_config_id: str | None = None
    requested_modules: list[str] = field(default_factory=list)
    deadline_ms: int = 0

    @classmethod
    def from_payload(cls, payload: "AlgorithmJob | dict[str, Any]") -> "AlgorithmJob":
        if isinstance(payload, cls):
            return payload
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()
        elif hasattr(payload, "dict") and callable(payload.dict):
            payload = payload.dict()
        elif all(hasattr(payload, name) for name in ("job_id", "resident_id", "asset_id", "media_locator")):
            payload = {name: getattr(payload, name) for name in (
                "job_id", "correlation_id", "resident_id", "asset_id", "media_type",
                "media_locator", "captured_at", "source_mode", "simulated", "location",
                "camera_position_id", "scene_config_id", "requested_modules", "deadline_ms",
            ) if hasattr(payload, name)}
        if not isinstance(payload, dict):
            raise ContractValidationError("AlgorithmJob must be an object")
        required = (
            "job_id", "correlation_id", "resident_id", "asset_id", "media_type",
            "media_locator", "captured_at", "source_mode", "simulated",
        )
        missing = [name for name in required if name not in payload]
        if missing:
            raise ContractValidationError("AlgorithmJob missing fields: " + ", ".join(missing))
        return cls(
            job_id=payload["job_id"], correlation_id=payload["correlation_id"],
            resident_id=payload["resident_id"], asset_id=payload["asset_id"],
            media_type=payload["media_type"], media_locator=payload["media_locator"],
            captured_at=payload["captured_at"], source_mode=payload["source_mode"],
            simulated=payload["simulated"], location=payload.get("location"),
            camera_position_id=payload.get("camera_position_id"),
            scene_config_id=payload.get("scene_config_id"),
            requested_modules=list(payload.get("requested_modules") or []),
            deadline_ms=payload.get("deadline_ms", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id, "correlation_id": self.correlation_id,
            "resident_id": self.resident_id, "asset_id": self.asset_id,
            "media_type": self.media_type, "media_locator": self.media_locator,
            "captured_at": self.captured_at, "source_mode": self.source_mode,
            "simulated": self.simulated, "location": self.location,
            "camera_position_id": self.camera_position_id,
            "scene_config_id": self.scene_config_id,
            "requested_modules": self.requested_modules, "deadline_ms": self.deadline_ms,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


def _timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be an ISO 8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractValidationError(f"{field_name} is not a valid ISO 8601 timestamp") from error
    if parsed.utcoffset() is None:
        raise ContractValidationError(f"{field_name} must include a timezone")
    return parsed


def validate_job(job: AlgorithmJob | dict[str, Any]) -> AlgorithmJob:
    result = AlgorithmJob.from_payload(job)
    for name in ("job_id", "correlation_id", "resident_id", "asset_id", "media_type", "media_locator"):
        value = getattr(result, name)
        if not isinstance(value, str) or not value.strip():
            raise ContractValidationError(f"{name} must be a non-empty string")
    _timestamp(result.captured_at, "captured_at")
    if result.source_mode not in SOURCE_MODES:
        raise ContractValidationError(f"source_mode must be one of {sorted(SOURCE_MODES)}")
    if not isinstance(result.simulated, bool):
        raise ContractValidationError("simulated must be boolean")
    if not isinstance(result.requested_modules, list) or not all(isinstance(item, str) for item in result.requested_modules):
        raise ContractValidationError("requested_modules must be an array of strings")
    if not isinstance(result.deadline_ms, int) or isinstance(result.deadline_ms, bool) or result.deadline_ms < 0:
        raise ContractValidationError("deadline_ms must be a non-negative integer")
    return result


def now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def error(code: str, message: str, *, retryable: bool = False, details: dict | None = None) -> AdapterError:
    return AdapterError(code, message, retryable=retryable, details=details)


def build_batch(job: AlgorithmJob | dict[str, Any], *, module: str, status: str,
                adapter_version: str, started_at: str, completed_at: str,
                observations: list[dict], evidences: list[dict],
                diagnostics: dict | None = None, batch_error: dict | None = None) -> dict:
    checked_job = validate_job(job)
    if module not in MODULES:
        raise ContractValidationError(f"module must be one of {sorted(MODULES)}")
    if status not in STATUSES:
        raise ContractValidationError(f"status must be one of {sorted(STATUSES)}")
    start = _timestamp(started_at, "started_at")
    complete = _timestamp(completed_at, "completed_at")
    if complete < start:
        raise ContractValidationError("completed_at cannot be earlier than started_at")
    if not isinstance(adapter_version, str) or not adapter_version.strip():
        raise ContractValidationError("adapter_version must be a non-empty string")
    observations = validate_observation_collection(observations)
    evidences = validate_evidence_collection(evidences)
    observation_ids = {item["observation_id"] for item in observations}
    for observation in observations:
        for name in ("resident_id", "asset_id", "source_mode", "simulated"):
            if observation[name] != getattr(checked_job, name):
                raise ContractValidationError(f"Observation {name} must inherit AlgorithmJob")
    for evidence in evidences:
        if "asset_id" in evidence:
            raise ContractValidationError("Evidence must not contain asset_id")
        if evidence["resident_id"] != checked_job.resident_id or evidence["source_mode"] != checked_job.source_mode or evidence["simulated"] != checked_job.simulated:
            raise ContractValidationError("Evidence must inherit resident/source/simulated from AlgorithmJob")
        if not set(evidence["observation_ids"]).issubset(observation_ids):
            raise ContractValidationError("Evidence observation_ids must reference this batch")
    if status == "FAILED" and (observations or evidences):
        raise ContractValidationError("FAILED batches cannot contain observations or evidences")
    if status == "NO_EVIDENCE" and evidences:
        raise ContractValidationError("NO_EVIDENCE batches cannot contain evidences")
    if not isinstance(diagnostics, dict):
        raise ContractValidationError("diagnostics must be an object")
    if status == "FAILED" and not isinstance(batch_error, dict):
        raise ContractValidationError("FAILED batches require error")
    if isinstance(batch_error, dict):
        required_error_fields = {"code", "message", "retryable", "details"}
        if set(batch_error) != required_error_fields:
            raise ContractValidationError("AdapterError must contain code, message, retryable and details")
        if not isinstance(batch_error["code"], str) or not batch_error["code"].strip():
            raise ContractValidationError("AdapterError.code must be a non-empty string")
        if not isinstance(batch_error["message"], str) or not batch_error["message"].strip():
            raise ContractValidationError("AdapterError.message must be a non-empty string")
        if not isinstance(batch_error["retryable"], bool) or not isinstance(batch_error["details"], dict):
            raise ContractValidationError("AdapterError.retryable must be boolean and details must be an object")
    if status != "FAILED" and batch_error is not None:
        raise ContractValidationError("successful batches must have error=null")
    return {
        "schema_version": ADAPTER_SCHEMA_VERSION,
        "job_id": checked_job.job_id,
        "module": module,
        "adapter_version": adapter_version,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "observations": observations,
        "evidences": evidences,
        "diagnostics": diagnostics,
        "error": batch_error,
    }


def validate_adapter_batch(batch: dict, *, job: AlgorithmJob | dict | None = None,
                           expected_module: str | None = None) -> dict:
    """Validate a previously serialized AdapterBatch without rebuilding it."""
    if not isinstance(batch, dict):
        raise ContractValidationError("AdapterBatch must be an object")
    required = {
        "schema_version", "job_id", "module", "adapter_version", "status",
        "started_at", "completed_at", "observations", "evidences", "diagnostics", "error",
    }
    missing = sorted(required - batch.keys())
    if missing:
        raise ContractValidationError("AdapterBatch missing fields: " + ", ".join(missing))
    if batch["schema_version"] != ADAPTER_SCHEMA_VERSION:
        raise ContractValidationError("schema_version must be adapter-batch/1.0")
    if expected_module is not None and batch["module"] != expected_module:
        raise ContractValidationError("AdapterBatch module does not match adapter entry")
    if job is None:
        if not isinstance(batch["job_id"], str) or not batch["job_id"].strip():
            raise ContractValidationError("job_id must be a non-empty string")
        validate_observation_collection(batch["observations"])
        validate_evidence_collection(batch["evidences"])
        return batch
    checked_job = validate_job(job)
    if batch["job_id"] != checked_job.job_id:
        raise ContractValidationError("AdapterBatch job_id does not match AlgorithmJob")
    build_batch(
        checked_job, module=batch["module"], status=batch["status"],
        adapter_version=batch["adapter_version"], started_at=batch["started_at"],
        completed_at=batch["completed_at"], observations=batch["observations"],
        evidences=batch["evidences"], diagnostics=batch["diagnostics"],
        batch_error=batch["error"],
    )
    return batch
