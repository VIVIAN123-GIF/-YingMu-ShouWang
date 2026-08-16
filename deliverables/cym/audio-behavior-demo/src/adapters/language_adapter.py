"""Worker adapter for the existing Whisper/audio evidence pipeline.

Text files are intended for deterministic, redacted integration tests. Audio
files are transcribed in memory with the existing Whisper dependency; only the
redacted Observation/Evidence objects leave this process.
"""

import asyncio
import importlib.util
import json
import shutil
from pathlib import Path

from audio_evidence import ADAPTER_VERSION, build_audio_batch

from .contract import (
    AlgorithmJob,
    ContractValidationError,
    build_batch,
    error,
    now_timestamp,
    validate_job,
)


AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".mp4", ".webm"}
TEXT_SUFFIXES = {".txt"}
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


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _transcribe(path: Path) -> tuple[str, dict]:
    if importlib.util.find_spec("whisper") is None:
        raise RuntimeError("openai-whisper is not installed")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg is required for audio transcription")
    try:
        import whisper
        model = whisper.load_model("tiny")
        result = model.transcribe(str(path), language="Chinese", fp16=False)
        transcript = result.get("text", "")
        transcript = transcript if isinstance(transcript, str) else ""
        segments = result.get("segments") or []
        no_speech = [float(item.get("no_speech_prob", 0.0)) for item in segments if isinstance(item, dict)]
        quality = 0.0 if not transcript.strip() and not no_speech else 1.0 - (sum(no_speech) / len(no_speech) if no_speech else 0.0)
        return transcript, {"data_quality": round(max(0.0, min(1.0, quality)), 4)}
    except Exception as exc:
        # Do not expose model paths, source audio or raw transcription in the
        # adapter error returned to the Worker.
        raise RuntimeError("Whisper transcription failed") from exc


def _load_transcript(job: AlgorithmJob) -> tuple[str, str, dict | None]:
    path = _input_path(job.media_locator)
    if not path.is_file():
        raise FileNotFoundError("language input file does not exist")
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return _read_text(path), "REDACTED_TEXT", None
    if suffix in AUDIO_SUFFIXES:
        transcript, quality_metrics = _transcribe(path)
        return transcript, "WHISPER_AUDIO", quality_metrics
    if suffix == ".json":
        raise ValueError("JSON language input is not accepted because raw transcript must not be persisted")
    raise ValueError("unsupported language input format")


def _response_diagnostic(observations: list[dict]) -> dict:
    intent_observation = next(
        (item for item in observations if item.get("feature_name") == "resident_response_intent"),
        None,
    )
    transcript_observation = next(
        (item for item in observations if item.get("feature_name") == "asr_transcript_redacted"),
        None,
    )
    internal = intent_observation.get("feature_value") if intent_observation else "uncertain"
    intent = {"stable": "STABLE", "help_requested": "HELP"}.get(internal, "UNCERTAIN")
    return {
        "intent": intent,
        "confidence": intent_observation.get("confidence", 0.0) if intent_observation else 0.0,
        "transcript_observation_id": transcript_observation.get("observation_id") if transcript_observation else None,
    }


async def run(job: AlgorithmJob | dict) -> dict:
    """Execute the language adapter and return an ``adapter-batch/1.0`` dict."""
    started_at = now_timestamp()
    try:
        checked_job = validate_job(job)
        if checked_job.requested_modules and "LANGUAGE" not in checked_job.requested_modules:
            raise ValueError("LANGUAGE is not listed in requested_modules")
        transcript, input_format, quality_metrics = await asyncio.to_thread(_load_transcript, checked_job)
        completed_at = now_timestamp()
        inner = build_audio_batch(
            checked_job.to_dict(), transcript,
            resident_id=checked_job.resident_id,
            source_mode=checked_job.source_mode,
            location=checked_job.location,
            simulated=checked_job.simulated,
            quality_metrics=quality_metrics,
            started_at=started_at,
            completed_at=completed_at,
        )
        observations = inner["observations"]
        evidences = inner["evidences"]
        quality_observation = next(
            (item for item in observations if item.get("feature_name") == "audio_quality_score"),
            None,
        )
        quality = float(quality_observation["feature_value"]) if quality_observation else 0.0
        status = "LOW_QUALITY" if quality < LOW_QUALITY_THRESHOLD else ("SUCCESS" if evidences else "NO_EVIDENCE")
        diagnostics = {
            "input_format": input_format,
            "audio_quality": round(quality, 4),
            "core_algorithm": "audio_evidence.py",
            "resident_response": _response_diagnostic(observations),
        }
        return build_batch(
            checked_job, module="LANGUAGE", status=status,
            adapter_version=ADAPTER_VERSION, started_at=started_at, completed_at=completed_at,
            observations=observations, evidences=evidences, diagnostics=diagnostics,
        )
    except (ContractValidationError, FileNotFoundError, ValueError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        code = "LANGUAGE_INPUT_ERROR"
        if "FFmpeg" in str(exc):
            code = "FFMPEG_UNAVAILABLE"
        elif "Whisper" in str(exc) or "whisper" in str(exc):
            code = "WHISPER_UNAVAILABLE"
        return build_batch(
            job, module="LANGUAGE", status="FAILED", adapter_version=ADAPTER_VERSION,
            started_at=started_at, completed_at=now_timestamp(), observations=[], evidences=[],
            diagnostics={"input_format": "UNKNOWN"},
            batch_error=error(code, str(exc), retryable=code in {"FFMPEG_UNAVAILABLE", "WHISPER_UNAVAILABLE"}),
        )
