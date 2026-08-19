"""Worker adapter for already-redacted language analysis results."""

import asyncio
import json
from pathlib import Path

from audio_evidence import ADAPTER_VERSION

from .processed_language import (
    ProcessedLanguageInputError,
    build_processed_language_items,
    response_candidate,
    validate_processed_language_input,
)

from .contract import (
    AdapterBatch,
    AlgorithmModule,
    AlgorithmJob,
    ContractValidationError,
    build_batch,
    error,
    job_payload,
    now_timestamp,
    validate_job,
)


LOW_QUALITY_THRESHOLD = 0.45


def _input_path(locator: str) -> Path:
    if locator.startswith("file://"):
        locator = locator[7:]
    if "://" in locator:
        raise ValueError("only local file or file:// media_locator is supported")
    path = Path(locator).expanduser()
    if not path.is_absolute():
        package_root = Path(__file__).resolve().parents[2]
        candidate = package_root / path
        if candidate.exists():
            return candidate
    return path


def _load_processed_result(job: AlgorithmJob) -> dict:
    path = _input_path(job.media_locator)
    if not path.is_file():
        raise FileNotFoundError("language input file does not exist")
    if path.suffix.lower() != ".json":
        raise ValueError(
            "LANGUAGE accepts only a redacted language-analysis JSON result; "
            "raw audio and transcript files are forbidden"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return validate_processed_language_input(payload)


async def run(job: AlgorithmJob) -> AdapterBatch:
    """Execute the language adapter using the repository's frozen contract."""
    started_at = now_timestamp()
    try:
        checked_job = validate_job(job)
        if checked_job.requested_modules and AlgorithmModule.LANGUAGE not in checked_job.requested_modules:
            raise ValueError("LANGUAGE is not listed in requested_modules")
        processed = await asyncio.to_thread(_load_processed_result, checked_job)
        completed_at = now_timestamp()
        observations, evidences = build_processed_language_items(
            processed,
            job=job_payload(checked_job),
        )
        quality = processed["audio_quality"]
        status = "LOW_QUALITY" if quality < LOW_QUALITY_THRESHOLD else ("SUCCESS" if evidences else "NO_EVIDENCE")
        candidate = response_candidate(processed, observations)
        diagnostics = {
            "input_format": "REDACTED_LANGUAGE_ANALYSIS",
            "audio_quality": round(quality, 4),
            "processing_source": processed["processing_source"],
            "model_version": processed["model_version"],
            "core_algorithm": "processed_language.py",
        }
        return build_batch(
            checked_job, module="LANGUAGE", status=status,
            adapter_version=ADAPTER_VERSION, started_at=started_at, completed_at=completed_at,
            observations=observations, evidences=evidences, diagnostics=diagnostics,
            resident_response_candidate=candidate,
        )
    except (
        ContractValidationError,
        ProcessedLanguageInputError,
        FileNotFoundError,
        ValueError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        return build_batch(
            job, module="LANGUAGE", status="FAILED", adapter_version=ADAPTER_VERSION,
            started_at=started_at, completed_at=now_timestamp(), observations=[], evidences=[],
            diagnostics={"input_format": "UNKNOWN"},
            batch_error=error("LANGUAGE_INPUT_ERROR", str(exc), retryable=False),
        )
