"""Backend-facing behavior adapter and AlgorithmJob batch builder."""

from datetime import datetime

from adapter_batch import build_adapter_batch, validate_algorithm_job
from behavior_observations import ADAPTER_VERSION, build_behavior_observations
from evidence import build_evidence, validate_evidence_collection
from observation import validate_observation_collection
from pacing import analyze_pacing
from trend_analysis import build_trend_bundle


TRACKING_QUALITY_THRESHOLD = 0.65


def _timestamp(value, summary):
    return value or summary.get("captured_at") or datetime.now().astimezone().isoformat(timespec="seconds")


def _tracking_lost_evidence(summary, observations, *, resident_id, location, timestamp):
    frames = int(summary.get("frames_processed", 0))
    detected = int(summary.get("detected_frames", 0))
    ratio = detected / frames if frames else 0.0
    if ratio >= TRACKING_QUALITY_THRESHOLD:
        return []
    by_name = {item["feature_name"]: item["observation_id"] for item in observations}
    links = [by_name["person_detected_frame_ratio"]]
    if "max_person_count" in by_name:
        links.append(by_name["max_person_count"])
    return [
        build_evidence(
            evidence_id=f"evi-{summary.get('job_id') or summary.get('asset_id') or 'legacy-behavior'}-tracking-lost",
            observation_ids=links,
            resident_id=resident_id,
            timestamp=timestamp,
            risk_domain="FALL",
            evidence_type="tracking_lost",
            severity=round(1.0 - ratio, 4),
            confidence=round(max(0.0, min(1.0, ratio)), 4),
            data_quality=round(max(0.0, min(1.0, ratio)), 4),
            baseline_value=None,
            current_value=round(ratio, 4),
            baseline_deviation=None,
            time_scale="SHORT",
            location=location,
            explanation="人体检出比例偏低，可能存在遮挡、出画或光照问题；本段行为结果不应视为完整跟踪。",
            adapter_version=ADAPTER_VERSION,
            source_mode=summary.get("source_mode", "MOCK"),
            simulated=bool(summary.get("simulated", False)),
        )
    ]


def _unusual_pacing_evidence(summary, observations, *, resident_id, location, timestamp):
    """Emit a conservative demo Evidence for repeated region alternation."""
    region_statistics = summary.get("region_statistics")
    if not region_statistics:
        return []
    frames = int(summary.get("frames_processed", 0))
    detected = int(summary.get("detected_frames", 0))
    quality = detected / frames if frames else 0.0
    pacing = analyze_pacing(region_statistics)
    if quality < TRACKING_QUALITY_THRESHOLD or not pacing["triggered"]:
        return []
    by_name = {item["feature_name"]: item["observation_id"] for item in observations}
    feature_names = (
        "region_transition_count",
        "region_revisit_count",
        "alternating_region_transition_count",
        "pacing_pattern_score",
    )
    observation_ids = [by_name[name] for name in feature_names]
    confidence = round(min(0.80, quality * 0.80), 4)
    return [
        build_evidence(
            evidence_id=f"evi-{summary.get('job_id') or summary.get('asset_id') or 'legacy-behavior'}-unusual-pacing",
            observation_ids=observation_ids,
            resident_id=resident_id,
            timestamp=timestamp,
            risk_domain="MENTAL",
            evidence_type="unusual_pacing",
            severity=round(min(0.85, 0.35 + 0.50 * pacing["pacing_pattern_score"]), 4),
            confidence=confidence,
            data_quality=round(quality, 4),
            baseline_value=None,
            current_value=float(pacing["alternating_transition_count"]),
            baseline_deviation=None,
            time_scale="SHORT",
            location=location,
            explanation="观察到多个区域间反复往返，仅表示需要关注的活动模式；该演示规则未经正式标定，不构成心理疾病诊断。",
            adapter_version=ADAPTER_VERSION,
            source_mode=summary.get("source_mode", "MOCK"),
            simulated=bool(summary.get("simulated", False)),
        )
    ]


def _build_items(summary, *, resident_id, location=None, asset_id=None, timestamp=None, job_id=None, trend_payload=None):
    timestamp = _timestamp(timestamp, summary)
    observations = build_behavior_observations(
        summary,
        resident_id=resident_id,
        location=location,
        asset_id=asset_id,
        timestamp=timestamp,
        job_id=job_id,
    )
    evidences = (
        _tracking_lost_evidence(
            {**summary, "job_id": job_id, "asset_id": asset_id},
            observations,
            resident_id=resident_id,
            location=location,
            timestamp=timestamp,
        )
        if job_id is not None
        else []
    )
    if job_id is not None:
        evidences.extend(
            _unusual_pacing_evidence(
                {**summary, "job_id": job_id, "asset_id": asset_id},
                observations,
                resident_id=resident_id,
                location=location,
                timestamp=timestamp,
            )
        )
    if trend_payload is not None:
        if (
            trend_payload.get("source_mode") != summary.get("source_mode")
            or bool(trend_payload.get("simulated")) != bool(summary.get("simulated"))
        ):
            raise ValueError("trend input must use the same source_mode and simulated flags")
        trend_bundle = build_trend_bundle(trend_payload)
        observations.extend(trend_bundle["observations"])
        evidences.extend(trend_bundle.get("evidences", trend_bundle.get("evidence", [])))
    return validate_observation_collection(observations), validate_evidence_collection(evidences)


def build_behavior_bundle(summary, *, resident_id, location=None, asset_id=None, timestamp=None, trend_payload=None, job_id=None):
    """Build a legacy bundle plus plural `evidences` for new consumers."""
    observations, evidences = _build_items(
        summary,
        resident_id=resident_id,
        location=location,
        asset_id=asset_id,
        timestamp=timestamp,
        job_id=job_id,
        trend_payload=trend_payload,
    )
    return {
        "schema_version": "1.0",
        "source_mode": summary.get("source_mode", "MOCK"),
        "simulated": bool(summary.get("simulated", False)),
        "threshold_status": "DEMO_UNCALIBRATED",
        "observations": observations,
        "evidence": evidences,
        "evidences": evidences,
    }


def build_behavior_batch(job, summary, *, resident_id, location=None, trend_payload=None, started_at, completed_at):
    """Build the complete AlgorithmJob -> AdapterBatch response."""
    validate_algorithm_job(job)
    summary = {**summary, "captured_at": job["captured_at"]}
    observations, evidences = _build_items(
        summary,
        resident_id=resident_id,
        location=location,
        asset_id=job["asset_id"],
        timestamp=job["captured_at"],
        job_id=job["job_id"],
        trend_payload=trend_payload,
    )
    return build_adapter_batch(
        job,
        observations=observations,
        evidences=evidences,
        adapter_version=ADAPTER_VERSION,
        started_at=started_at,
        completed_at=completed_at,
    )
