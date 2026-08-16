"""Build backend-safe speech Observations and Evidence.

The transcript is accepted in memory for keyword extraction. Only a redacted
summary is returned; the original text is never placed in metadata, Evidence,
logs, or output files.
"""

import hashlib
from datetime import datetime

from adapter_batch import build_adapter_batch, validate_algorithm_job
from evidence import build_evidence, validate_evidence_collection
from observation import build_observation, validate_observation_collection


FRAUD_PHRASE_GROUPS = {
    "guaranteed_return": ("保证收益", "保證收益"),
    "verification_code_like": (
        "验证码",
        "驗證碼",
        "验证马",
        "驗證馬",
        "验证吗",
    ),
    "immediate_transfer": ("马上转账", "馬上轉帳", "马上完成转账", "馬上完成轉帳"),
    "safe_account": ("安全账户", "安全賬戶", "安全账户"),
    "keep_secret_from_family": ("不要告诉家人", "不要告訴家人"),
}

RESIDENT_RESPONSE_PHRASE_GROUPS = {
    "stable": (
        "我没事",
        "我没关系",
        "我很好",
        "不用帮忙",
        "不用帮助",
        "已经坐稳",
        "我坐稳了",
    ),
    "help_requested": (
        "需要帮助",
        "帮帮我",
        "帮我一下",
        "帮我联系家人",
        "叫救护车",
        "我不舒服",
        "我起不来",
    ),
    "uncertain": (
        "等一下",
        "不知道",
        "说不清",
    ),
}

ADAPTER_VERSION = "speech-adapter-v3"
LOW_QUALITY_THRESHOLD = 0.45


def normalize_transcript(transcript):
    if not isinstance(transcript, str):
        raise TypeError("transcript must be a string")
    return " ".join(transcript.replace("\u3000", " ").split()).strip()


def find_fraud_phrase_labels(transcript):
    normalized = normalize_transcript(transcript)
    return [
        label
        for label, variants in FRAUD_PHRASE_GROUPS.items()
        if any(variant in normalized for variant in variants)
    ]


def find_resident_response_labels(transcript):
    """Return matched response groups without retaining the source text."""
    normalized = normalize_transcript(transcript)
    return [
        label
        for label, variants in RESIDENT_RESPONSE_PHRASE_GROUPS.items()
        if any(variant in normalized for variant in variants)
    ]


def classify_resident_response(transcript, quality=1.0):
    """Classify a short safety response with conservative conflict handling."""
    normalized = normalize_transcript(transcript)
    if quality < LOW_QUALITY_THRESHOLD:
        return "unavailable", [], round(max(0.0, min(1.0, quality)), 4)
    if not normalized:
        return "no_response", [], round(max(0.0, min(1.0, quality)), 4)
    labels = find_resident_response_labels(normalized)
    if len(labels) != 1:
        return "uncertain", labels, round(min(0.55, quality * 0.60), 4)
    confidence = round(min(0.85, quality * 0.85), 4)
    return labels[0], labels, confidence


def redact_transcript(transcript, labels=None, response_labels=None):
    """Return a non-verbatim transcript summary safe for persistence."""
    labels = labels if labels is not None else find_fraud_phrase_labels(transcript)
    if not normalize_transcript(transcript):
        return "UNAVAILABLE"
    redacted_groups = []
    if labels:
        redacted_groups.append("keyword_groups=" + ",".join(labels))
    if response_labels:
        redacted_groups.append("response_groups=" + ",".join(response_labels))
    if redacted_groups:
        return ";".join(redacted_groups)
    return "speech_detected=true"


def score_audio_quality(metrics=None, *, transcript=""):
    if metrics is None:
        return 0.60
    if not isinstance(metrics, dict):
        raise ValueError("quality_metrics must be an object")
    if "data_quality" in metrics:
        value = float(metrics["data_quality"])
    else:
        value = 0.60
        for field in ("non_silent_ratio", "transcript_completeness"):
            if field in metrics:
                value = min(value, float(metrics[field]))
        if "clipping_ratio" in metrics:
            value = min(value, 1.0 - float(metrics["clipping_ratio"]))
    if not 0 <= value <= 1:
        raise ValueError("audio quality must be between 0 and 1")
    return round(value, 4)


def _timestamp(value):
    if value is None:
        return datetime.now().astimezone().isoformat(timespec="seconds")
    return value


def _namespace(transcript, job_id=None, run_id=None):
    if job_id:
        return str(job_id)
    if run_id:
        return str(run_id)
    return "audio-" + hashlib.sha256(normalize_transcript(transcript).encode("utf-8")).hexdigest()[:16]


def _build_audio_items(
    transcript,
    *,
    resident_id,
    model="unknown",
    language="Chinese",
    source_mode="RECORDED_REPLAY",
    location=None,
    asset_id=None,
    simulated=True,
    quality_metrics=None,
    timestamp=None,
    job_id=None,
    run_id=None,
):
    normalized = normalize_transcript(transcript)
    quality = score_audio_quality(quality_metrics, transcript=normalized)
    labels = find_fraud_phrase_labels(normalized)
    response_intent, response_labels, response_confidence = classify_resident_response(
        normalized, quality
    )
    timestamp = _timestamp(timestamp)
    namespace = _namespace(normalized, job_id=job_id, run_id=run_id)
    common = {
        "resident_id": resident_id,
        "timestamp": timestamp,
        "source": "whisper",
        "location": location,
        "confidence": round(min(0.85, quality), 4),
        "data_quality": quality,
        "source_mode": source_mode,
        "asset_id": asset_id,
        "simulated": bool(simulated),
        "metadata": {
            "adapter_version": ADAPTER_VERSION,
            "model": model,
            "language": language,
            "threshold_status": "DEMO_UNCALIBRATED",
            "interpretation": "INTERACTION_FEATURE_ONLY",
        },
    }
    redacted = redact_transcript(normalized, labels, response_labels)
    observations = [
        build_observation(
            observation_id=f"obs-{namespace}-audio-asr-transcript-redacted",
            feature_name="asr_transcript_redacted",
            feature_value=redacted,
            unit=None,
            **common,
        ),
        build_observation(
            observation_id=f"obs-{namespace}-audio-keyword-count",
            feature_name="fraud_keyword_match_count",
            feature_value=len(labels),
            unit="count",
            **common,
        ),
        build_observation(
            observation_id=f"obs-{namespace}-audio-quality",
            feature_name="audio_quality_score",
            feature_value=quality,
            unit="ratio",
            **common,
        ),
    ]
    if job_id is not None:
        observations.insert(
            1,
            build_observation(
                observation_id=f"obs-{namespace}-audio-intent",
                feature_name="audio_intent",
                feature_value="high_risk_interaction_feature" if labels else ("neutral" if normalized else "unavailable"),
                unit=None,
                **common,
            ),
        )
        observations.insert(
            2,
            build_observation(
                observation_id=f"obs-{namespace}-resident-response-intent",
                feature_name="resident_response_intent",
                feature_value=response_intent,
                unit=None,
                **{
                    **common,
                    "confidence": response_confidence,
                    "metadata": {
                        **common["metadata"],
                        "interpretation": "INTERVENTION_RESPONSE_FEATURE_ONLY",
                    },
                },
            ),
        )
        observations.insert(
            3,
            build_observation(
                observation_id=f"obs-{namespace}-resident-response-match-count",
                feature_name="resident_response_match_count",
                feature_value=len(response_labels),
                unit="count",
                **{
                    **common,
                    "confidence": response_confidence,
                    "metadata": {
                        **common["metadata"],
                        "interpretation": "INTERVENTION_RESPONSE_FEATURE_ONLY",
                    },
                },
            ),
        )
    if labels:
        observations.append(
            build_observation(
                observation_id=f"obs-{namespace}-audio-keyword-labels",
                feature_name="fraud_keyword_labels",
                feature_value=",".join(labels),
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
                evidence_id=f"evi-{namespace}-audio-quality-low",
                observation_ids=[by_name["audio_quality_score"]],
                resident_id=resident_id,
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
                location=location,
                explanation="音频质量低，关键词结果不可单独用于风险判断，建议重新采集清晰完整的授权音频。",
                adapter_version=ADAPTER_VERSION,
                source_mode=source_mode,
                simulated=bool(simulated),
            )
        )
    if labels:
        evidences.append(
            build_evidence(
                evidence_id=f"evi-{namespace}-audio-fraud-keyword",
                observation_ids=[by_name["asr_transcript_redacted"], by_name["fraud_keyword_match_count"]],
                resident_id=resident_id,
                timestamp=timestamp,
                risk_domain="FRAUD",
                evidence_type="fraud_keyword",
                severity=round(min(0.85, 0.25 + 0.18 * len(labels)), 4),
                confidence=round(min(0.85, quality * (0.55 if len(labels) == 1 else 0.80)), 4),
                data_quality=quality,
                baseline_value=None,
                current_value=float(len(labels)),
                baseline_deviation=None,
                time_scale="SHORT",
                location=location,
                explanation="转写中出现高风险交互特征，仅建议人工核验；单个关键词或单段音频不能独立判断诈骗。",
                adapter_version=ADAPTER_VERSION,
                source_mode=source_mode,
                simulated=bool(simulated),
            )
        )
    return observations, validate_evidence_collection(evidences)


def build_audio_bundle(transcript, *, resident_id, model="unknown", language="Chinese", source_mode="RECORDED_REPLAY", location=None, asset_id=None, simulated=True, quality_metrics=None, timestamp=None, run_id=None, job_id=None):
    observations, evidences = _build_audio_items(
        transcript, resident_id=resident_id, model=model, language=language,
        source_mode=source_mode, location=location, asset_id=asset_id,
        simulated=simulated, quality_metrics=quality_metrics, timestamp=timestamp,
        run_id=run_id, job_id=job_id,
    )
    # Keep `evidence` for existing local consumers; new Worker payloads use
    # `evidences` through build_audio_batch.
    return {
        "schema_version": "1.0", "source_mode": source_mode,
        "simulated": bool(simulated), "threshold_status": "DEMO_UNCALIBRATED",
        "observations": observations, "evidence": evidences, "evidences": evidences,
    }


def build_audio_batch(job, transcript, *, resident_id, model="unknown", language="Chinese", source_mode="RECORDED_REPLAY", location=None, simulated=True, quality_metrics=None, started_at, completed_at):
    """Build the complete AlgorithmJob -> AdapterBatch response."""
    validate_algorithm_job(job)
    source_mode = job.get("source_mode", source_mode)
    simulated = bool(job.get("simulated", simulated))
    observations, evidences = _build_audio_items(
        transcript, resident_id=resident_id, model=model, language=language,
        source_mode=source_mode, location=location, asset_id=job["asset_id"],
        simulated=simulated, quality_metrics=quality_metrics,
        timestamp=job["captured_at"], job_id=job["job_id"],
    )
    return build_adapter_batch(
        job, observations=observations, evidences=evidences,
        adapter_version=ADAPTER_VERSION, started_at=started_at, completed_at=completed_at,
    )
