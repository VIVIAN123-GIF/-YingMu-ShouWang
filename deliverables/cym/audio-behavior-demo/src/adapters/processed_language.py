"""Build LANGUAGE outputs from an already redacted ASR result."""

from __future__ import annotations

from typing import Any

from audio_evidence import ADAPTER_VERSION, FRAUD_PHRASE_GROUPS, LOW_QUALITY_THRESHOLD
from evidence import build_evidence, validate_evidence_collection
from observation import build_observation, validate_observation_collection


SCHEMA_VERSION = "language-analysis/1.0"
ALLOWED_FIELDS = {
    "schema_version",
    "keyword_groups",
    "resident_response",
    "audio_quality",
    "processing_source",
    "model_version",
    "language",
}
RESIDENT_RESPONSES = {
    "resident_response_help": "HELP",
    "resident_response_stable": "STABLE",
}
PROCESSING_SOURCES = {
    "ASR_REDACTED",
    "MANUAL_REDACTED",
    "MOCK_REDACTED",
    "WHISPER_REDACTED",
}


class ProcessedLanguageInputError(ValueError):
    """Raised when a LANGUAGE input could leak raw or unsupported data."""


def validate_processed_language_input(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProcessedLanguageInputError("language input must be a JSON object")
    unknown = sorted(set(payload) - ALLOWED_FIELDS)
    if unknown:
        raise ProcessedLanguageInputError("language input contains unsupported fields")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ProcessedLanguageInputError(f"schema_version must be {SCHEMA_VERSION}")

    keyword_groups = payload.get("keyword_groups", [])
    if not isinstance(keyword_groups, list) or not all(
        isinstance(item, str) and item for item in keyword_groups
    ):
        raise ProcessedLanguageInputError("keyword_groups must be an array of labels")
    if len(keyword_groups) != len(set(keyword_groups)):
        raise ProcessedLanguageInputError("keyword_groups cannot contain duplicates")
    invalid_groups = sorted(set(keyword_groups) - set(FRAUD_PHRASE_GROUPS))
    if invalid_groups:
        raise ProcessedLanguageInputError(
            "keyword_groups contains labels outside the frozen vocabulary"
        )

    resident_response = payload.get("resident_response")
    if resident_response is not None and resident_response not in RESIDENT_RESPONSES:
        raise ProcessedLanguageInputError(
            "resident_response must be resident_response_help, "
            "resident_response_stable or null"
        )

    quality = payload.get("audio_quality")
    if isinstance(quality, bool) or not isinstance(quality, (int, float)):
        raise ProcessedLanguageInputError("audio_quality must be a number between 0 and 1")
    quality = float(quality)
    if not 0 <= quality <= 1:
        raise ProcessedLanguageInputError("audio_quality must be a number between 0 and 1")

    processing_source = payload.get("processing_source")
    if processing_source not in PROCESSING_SOURCES:
        raise ProcessedLanguageInputError(
            "processing_source is outside the frozen redacted-source vocabulary"
        )
    model_version = payload.get("model_version")
    if not isinstance(model_version, str) or not model_version.strip():
        raise ProcessedLanguageInputError("model_version must be a non-empty string")
    language = payload.get("language", "Chinese")
    if not isinstance(language, str) or not language.strip():
        raise ProcessedLanguageInputError("language must be a non-empty string")

    return {
        "schema_version": SCHEMA_VERSION,
        "keyword_groups": keyword_groups,
        "resident_response": resident_response,
        "audio_quality": round(quality, 4),
        "processing_source": processing_source,
        "model_version": model_version.strip(),
        "language": language.strip(),
    }


def _redacted_summary(keyword_groups: list[str], resident_response: str | None) -> str:
    parts = []
    if keyword_groups:
        parts.append("keyword_groups=" + ",".join(keyword_groups))
    if resident_response:
        parts.append("resident_response=" + resident_response)
    return ";".join(parts) if parts else "speech_detected=true"


def build_processed_language_items(
    payload: dict[str, Any],
    *,
    job: dict[str, Any],
) -> tuple[list[dict], list[dict]]:
    checked = validate_processed_language_input(payload)
    quality = checked["audio_quality"]
    keyword_groups = checked["keyword_groups"]
    resident_response = (
        checked["resident_response"] if quality >= LOW_QUALITY_THRESHOLD else None
    )
    job_id = job["job_id"]
    timestamp = job["captured_at"]
    common = {
        "resident_id": job["resident_id"],
        "timestamp": timestamp,
        "source": checked["processing_source"].lower(),
        "location": job["location"],
        "confidence": round(min(0.85, quality), 4),
        "data_quality": quality,
        "source_mode": job["source_mode"],
        "asset_id": job["asset_id"],
        "simulated": job["simulated"],
        "metadata": {
            "adapter_version": ADAPTER_VERSION,
            "model_version": checked["model_version"],
            "language": checked["language"],
            "threshold_status": "DEMO_UNCALIBRATED",
            "interpretation": "REDACTED_INTERACTION_FEATURE_ONLY",
        },
    }
    observations = [
        build_observation(
            observation_id=f"obs-{job_id}-audio-asr-transcript-redacted",
            feature_name="asr_transcript_redacted",
            feature_value=_redacted_summary(keyword_groups, resident_response),
            unit=None,
            **common,
        ),
        build_observation(
            observation_id=f"obs-{job_id}-audio-intent",
            feature_name="audio_intent",
            feature_value="high_risk_interaction_feature" if keyword_groups else "neutral",
            unit=None,
            **common,
        ),
        build_observation(
            observation_id=f"obs-{job_id}-audio-keyword-count",
            feature_name="fraud_keyword_match_count",
            feature_value=len(keyword_groups),
            unit="count",
            **common,
        ),
        build_observation(
            observation_id=f"obs-{job_id}-audio-quality",
            feature_name="audio_quality_score",
            feature_value=quality,
            unit="ratio",
            **common,
        ),
    ]
    if resident_response:
        response_confidence = round(min(0.85, quality * 0.85), 4)
        observations.append(
            build_observation(
                observation_id=f"obs-{job_id}-{resident_response}",
                feature_name="resident_response",
                feature_value=resident_response,
                unit=None,
                **{
                    **common,
                    "confidence": response_confidence,
                    "metadata": {
                        **common["metadata"],
                        "interpretation": "INTERVENTION_RESPONSE_FEATURE_ONLY",
                    },
                },
            )
        )
    if keyword_groups:
        observations.append(
            build_observation(
                observation_id=f"obs-{job_id}-audio-keyword-labels",
                feature_name="fraud_keyword_labels",
                feature_value=",".join(keyword_groups),
                unit=None,
                **common,
            )
        )
    observations = validate_observation_collection(observations)
    by_name = {item["feature_name"]: item["observation_id"] for item in observations}

    evidences = []
    if quality < LOW_QUALITY_THRESHOLD:
        evidences.append(
            build_evidence(
                evidence_id=f"evi-{job_id}-audio-quality-low",
                observation_ids=[by_name["audio_quality_score"]],
                resident_id=job["resident_id"],
                timestamp=timestamp,
                risk_domain="SYSTEM",
                evidence_type="audio_quality_low",
                severity=round(1.0 - quality, 4),
                confidence=quality,
                data_quality=quality,
                baseline_value=None,
                current_value=quality,
                baseline_deviation=None,
                time_scale="SHORT",
                location=job["location"],
                explanation="音频处理质量偏低，本段语言特征不可用于居民回应判断。",
                adapter_version=ADAPTER_VERSION,
                source_mode=job["source_mode"],
                simulated=job["simulated"],
            )
        )
    elif keyword_groups:
        evidences.append(
            build_evidence(
                evidence_id=f"evi-{job_id}-audio-fraud-keyword",
                observation_ids=[
                    by_name["asr_transcript_redacted"],
                    by_name["fraud_keyword_match_count"],
                ],
                resident_id=job["resident_id"],
                timestamp=timestamp,
                risk_domain="FRAUD",
                evidence_type="fraud_keyword",
                severity=round(min(0.85, 0.25 + 0.18 * len(keyword_groups)), 4),
                confidence=round(
                    min(0.85, quality * (0.55 if len(keyword_groups) == 1 else 0.80)),
                    4,
                ),
                data_quality=quality,
                baseline_value=None,
                current_value=float(len(keyword_groups)),
                baseline_deviation=None,
                time_scale="SHORT",
                location=job["location"],
                explanation="脱敏结果包含高风险交互特征，仅建议人工核验，不直接判断诈骗。",
                adapter_version=ADAPTER_VERSION,
                source_mode=job["source_mode"],
                simulated=job["simulated"],
            )
        )
    return observations, validate_evidence_collection(evidences)


def response_candidate(
    payload: dict[str, Any], observations: list[dict]
) -> dict[str, Any] | None:
    checked = validate_processed_language_input(payload)
    response = checked["resident_response"]
    quality = checked["audio_quality"]
    if response is None or quality < LOW_QUALITY_THRESHOLD:
        return None
    transcript = next(
        item for item in observations if item["feature_name"] == "asr_transcript_redacted"
    )
    return {
        "intent": RESIDENT_RESPONSES[response],
        "confidence": round(min(0.85, quality * 0.85), 4),
        "transcript_observation_id": transcript["observation_id"],
    }
