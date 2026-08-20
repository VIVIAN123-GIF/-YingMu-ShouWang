"""Compatibility helpers backed by the repository's frozen v1 contract.

The public types come from ``contracts.v1.algorithm``. This module only keeps
small construction helpers for the two adapters; it is not a second contract.
"""

from datetime import datetime, timezone
from typing import Any

from contracts.v1.algorithm import (
    AdapterBatch,
    AdapterError,
    AdapterStatus,
    AlgorithmJob,
    AlgorithmModule,
    ResidentResponseCandidate,
    validate_batch_for_job,
)


class ContractValidationError(ValueError):
    """Raised when adapter input or output cannot satisfy the frozen contract."""


def validate_job(job: AlgorithmJob | dict[str, Any]) -> AlgorithmJob:
    if isinstance(job, AlgorithmJob):
        return job
    try:
        return AlgorithmJob.model_validate(job)
    except Exception as exc:
        raise ContractValidationError(str(exc)) from exc


def job_payload(job: AlgorithmJob) -> dict[str, Any]:
    """Return JSON-shaped values for the legacy feature builders."""
    return job.model_dump(mode="json")


def now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def error(code: str, message: str, *, retryable: bool = False) -> AdapterError:
    return AdapterError(code=code, message=message[:256], retryable=retryable)


def build_batch(
    job: AlgorithmJob | dict[str, Any],
    *,
    module: str | AlgorithmModule,
    status: str | AdapterStatus,
    adapter_version: str,
    started_at: str,
    completed_at: str,
    observations: list[dict],
    evidences: list[dict],
    diagnostics: dict | None = None,
    batch_error: AdapterError | dict | None = None,
    resident_response_candidate: ResidentResponseCandidate | dict | None = None,
) -> AdapterBatch:
    checked_job = validate_job(job)
    module_value = module if isinstance(module, AlgorithmModule) else AlgorithmModule(module)
    status_value = status if isinstance(status, AdapterStatus) else AdapterStatus(status)
    payload = {
        "schema_version": "adapter-batch/1.0",
        "job_id": checked_job.job_id,
        "module": module_value,
        "adapter_version": adapter_version,
        "status": status_value,
        "started_at": started_at,
        "completed_at": completed_at,
        "observations": observations,
        "evidences": evidences,
        "resident_response_candidate": resident_response_candidate,
        "diagnostics": diagnostics or {},
        "error": batch_error,
    }
    try:
        batch = AdapterBatch.model_validate(payload)
        return validate_batch_for_job(batch, checked_job)
    except Exception as exc:
        raise ContractValidationError(str(exc)) from exc


def validate_adapter_batch(
    batch: AdapterBatch | dict,
    *,
    job: AlgorithmJob | dict | None = None,
    expected_module: str | AlgorithmModule | None = None,
) -> AdapterBatch:
    try:
        result = batch if isinstance(batch, AdapterBatch) else AdapterBatch.model_validate(batch)
        if expected_module is not None:
            expected = expected_module if isinstance(expected_module, AlgorithmModule) else AlgorithmModule(expected_module)
            if result.module != expected:
                raise ValueError("AdapterBatch module does not match adapter entry")
        if job is not None:
            validate_batch_for_job(result, validate_job(job))
        return result
    except Exception as exc:
        raise ContractValidationError(str(exc)) from exc


__all__ = [
    "AdapterBatch", "AdapterError", "AdapterStatus", "AlgorithmJob",
    "AlgorithmModule", "ContractValidationError", "ResidentResponseCandidate",
    "build_batch", "error", "job_payload", "now_timestamp", "validate_adapter_batch",
    "validate_job",
]
