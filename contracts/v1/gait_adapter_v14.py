"""Version-isolated v1.4 gait adapter for supplemental validation and runtime."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.v1.algorithm import (
    AdapterBatch, AdapterError, AdapterStatus, AlgorithmJob, AlgorithmModule,
    MediaType, validate_batch_for_job,
)
from contracts.v1.gait_video import GaitVideoError, VIDEO_SUFFIXES, extract_gait_features_v14
from contracts.v1.models import Evidence, Observation, RiskDomain, TimeScale
from contracts.v1.ruleset import load_ruleset_version


ADAPTER_VERSION = "gait-adapter-v1.4"
MODULE = AlgorithmModule.GAIT
RULESET = load_ruleset_version("ruleset-v1.4")
THRESHOLDS = RULESET.thresholds
QUALITY_REASONS = {
    "HUMAN_TRACKING_OR_OCCLUSION", "FEET_OUT_OF_FRAME", "LOW_ILLUMINATION",
    "MULTIPLE_PEOPLE", "POST_RISE_TRACKING_LOW", "POST_RISE_WINDOW_INSUFFICIENT",
    "CAMERA_ORIENTATION_UNSUITABLE", "TURNING_DURING_ASSESSMENT",
}

FEATURES: tuple[str, ...] = (
    "rise_duration_s", "hip_vertical_speed_norm_s", "trunk_sway_angle_deg",
    "com_offset_norm", "step_speed_norm_s", "step_asymmetry_ratio",
    "turn_angular_velocity_deg_s", "support_distance_norm",
    "stable_posture_duration", "stable_trunk_angle_deg", "valid_frame_ratio",
    "assessment_status", "assessment_reason_code", "sit_to_stand_transition_confirmed",
    "post_rise_sway_reversal_count", "post_rise_pelvis_lateral_excursion_norm",
    "post_rise_support_width_change_norm", "post_rise_compensatory_step_count",
    "post_rise_left_ankle_motion_norm", "post_rise_right_ankle_motion_norm",
    "post_rise_pelvis_path_norm", "post_rise_locomotion_detected",
    "post_rise_orientation_quality", "post_rise_feet_visibility",
    "post_rise_tracking_ratio", "locomotion_frame_ratio", "locomotion_duration_s",
    "illumination_norm", "multi_person_frame_ratio", "multi_person_max_consecutive_s",
    "feet_visibility_mean", "feet_low_visibility_ratio", "core_low_visibility_ratio",
    "core_low_visibility_max_consecutive_s",
    "gait_cycle_count", "left_stride_excursion_norm",
    "right_stride_excursion_norm", "stride_length_asymmetry_ratio",
    "gait_cycle_assessment_valid",
    "person_roi_illumination_median", "person_roi_illumination_p10",
    "person_roi_contrast", "pose_freeze_visual_change_max_consecutive_s",
    "pre_quality_assessment_status", "pre_quality_assessment_reason_code",
)
ALIASES = {
    "sit_to_stand_duration": "rise_duration_s", "rise_duration": "rise_duration_s",
    "trunk_sway_angle": "trunk_sway_angle_deg", "step_speed": "step_speed_norm_s",
    "step_length_asymmetry_ratio": "step_asymmetry_ratio", "tracking_ratio": "valid_frame_ratio",
}
UNITS = {
    "rise_duration_s": "second", "hip_vertical_speed_norm_s": "norm_per_second",
    "trunk_sway_angle_deg": "degree", "com_offset_norm": "norm",
    "step_speed_norm_s": "norm_per_second", "step_asymmetry_ratio": "ratio",
    "turn_angular_velocity_deg_s": "degree_per_second", "support_distance_norm": "norm",
    "stable_posture_duration": "second", "stable_trunk_angle_deg": "degree",
    "valid_frame_ratio": "ratio", "post_rise_sway_reversal_count": "count",
    "post_rise_pelvis_lateral_excursion_norm": "body_scale",
    "post_rise_support_width_change_norm": "body_scale",
    "post_rise_compensatory_step_count": "count",
    "post_rise_left_ankle_motion_norm": "body_scale",
    "post_rise_right_ankle_motion_norm": "body_scale",
    "post_rise_pelvis_path_norm": "body_scale",
    "post_rise_orientation_quality": "ratio", "post_rise_feet_visibility": "ratio",
    "post_rise_tracking_ratio": "ratio", "locomotion_frame_ratio": "ratio",
    "locomotion_duration_s": "second", "illumination_norm": "ratio",
    "multi_person_frame_ratio": "ratio", "multi_person_max_consecutive_s": "second",
    "feet_visibility_mean": "ratio", "feet_low_visibility_ratio": "ratio",
    "core_low_visibility_ratio": "ratio",
    "core_low_visibility_max_consecutive_s": "second",
    "gait_cycle_count": "count",
    "left_stride_excursion_norm": "body_scale",
    "right_stride_excursion_norm": "body_scale",
    "stride_length_asymmetry_ratio": "ratio",
    "gait_cycle_assessment_valid": "boolean",
    "person_roi_illumination_median": "ratio",
    "person_roi_illumination_p10": "ratio",
    "person_roi_contrast": "ratio",
    "pose_freeze_visual_change_max_consecutive_s": "second",
}


class FeatureInputError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _stable_id(prefix: str, *parts: object) -> str:
    value = "|".join("" if part is None else str(part) for part in parts)
    return f"{prefix}-{hashlib.sha1(value.encode('utf-8')).hexdigest()[:16]}"


def _score(value: float) -> float:
    return round(min(max(float(value), 0.0), 1.0), 3)


def _coerce(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 3)
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return value


def _mapping(payload: dict[Any, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_name, value in payload.items():
        name = ALIASES.get(str(raw_name), str(raw_name))
        if name in FEATURES and value not in (None, ""):
            result[name] = _coerce(value)
    return result


def _read(job: AlgorithmJob) -> tuple[dict[str, Any], dict[str, Any]]:
    locator = job.media_locator[7:] if job.media_locator.startswith("file://") else job.media_locator
    if "://" in locator:
        raise FeatureInputError("only_local_media_supported")
    path = Path(locator).expanduser()
    if not path.is_file():
        raise FeatureInputError("media_locator_not_readable")
    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return {"valid_frame_ratio": 1.0}, {"feature_source_type": "image"}
    if path.suffix.lower() in VIDEO_SUFFIXES:
        try:
            return extract_gait_features_v14(path)
        except GaitVideoError as exc:
            raise FeatureInputError(str(exc)) from exc
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise FeatureInputError("feature_payload_invalid")
        for key in ("features", "gait_features", "metrics"):
            if isinstance(payload.get(key), dict):
                payload = payload[key]
                break
        features = _mapping(payload)
        if not features:
            raise FeatureInputError("feature_payload_empty")
        return features, {"feature_source_type": "json"}
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        features = _mapping(rows[0]) if rows else {}
        if not features:
            raise FeatureInputError("feature_payload_empty")
        return features, {"feature_source_type": "csv", "feature_rows": len(rows)}
    raise FeatureInputError("unsupported_media_locator")


def _quality(features: dict[str, Any]) -> float:
    values = [
        float(features[name]) for name in ("valid_frame_ratio", "post_rise_tracking_ratio")
        if isinstance(features.get(name), (int, float))
    ]
    quality = min(values) if values else 0.85
    reason = str(features.get("assessment_reason_code", ""))
    if reason in QUALITY_REASONS:
        quality = min(quality, 0.69)
    return _score(quality)


def _observation(job: AlgorithmJob, name: str, value: Any, quality: float) -> Observation:
    return Observation(
        schema_version="1.0",
        observation_id=_stable_id("obs-gait-v14", job.job_id, job.resident_id, job.asset_id, name),
        resident_id=job.resident_id, timestamp=job.captured_at, source="gait_adapter_v14",
        feature_name=name, feature_value=value, unit=UNITS.get(name), location=job.location,
        confidence=_score(0.72 + 0.25 * quality), data_quality=quality,
        source_mode=job.source_mode, asset_id=job.asset_id, simulated=job.simulated,
        metadata={
            "adapter_module": MODULE.value, "adapter_version": ADAPTER_VERSION,
            "camera_position_id": job.camera_position_id, "scene_config_id": job.scene_config_id,
        },
    )


def _evidence(
    job: AlgorithmJob, evidence_type: str, observation: Observation, severity: float,
    current: float | None, baseline: float | None, explanation: str, *,
    related: tuple[Observation, ...] = (), time_scale: TimeScale = TimeScale.SHORT,
) -> Evidence:
    deviation = None
    if current is not None and baseline not in (None, 0):
        deviation = (current - baseline) / baseline
    return Evidence(
        schema_version="1.0",
        evidence_id=_stable_id("evi-gait-v14", job.job_id, job.asset_id, evidence_type, observation.observation_id),
        observation_ids=[observation.observation_id, *(item.observation_id for item in related)],
        resident_id=job.resident_id, timestamp=job.captured_at, risk_domain=RiskDomain.FALL,
        evidence_type=evidence_type, severity=_score(severity), confidence=observation.confidence,
        data_quality=observation.data_quality, baseline_value=baseline, current_value=current,
        baseline_deviation=None if deviation is None else round(deviation, 3), time_scale=time_scale,
        location=job.location, explanation=explanation, adapter_version=ADAPTER_VERSION,
        source_mode=job.source_mode, simulated=job.simulated,
    )


def _severity(value: float, threshold: float, saturation: float) -> float:
    return _score((value - threshold) / max(saturation - threshold, 1e-6))


def _build(
    job: AlgorithmJob, observations: list[Observation], *, quality_gate: bool = True,
    ruleset: Any = RULESET,
) -> list[Evidence]:
    thresholds = ruleset.thresholds
    by_name = {item.feature_name: item for item in observations}
    status = str(by_name.get("assessment_status").feature_value) if by_name.get("assessment_status") else None
    reason_observation = by_name.get("assessment_reason_code")
    reason = str(reason_observation.feature_value) if reason_observation else "ASSESSMENT_INDETERMINATE"
    if status == "INDETERMINATE" and quality_gate:
        anchor = by_name.get("assessment_status") or next(iter(observations))
        return [_evidence(
            job, "assessment_indeterminate", anchor, 0.0, None, None,
            f"Assessment is indeterminate because {reason}.",
            related=(reason_observation,) if reason_observation else (),
        )]

    evidences: list[Evidence] = []
    transition = by_name.get("sit_to_stand_transition_confirmed")
    confirmed = bool(transition and transition.feature_value is True)
    if confirmed and transition:
        evidences.append(_evidence(
            job, "sit_to_stand_transition", transition, 0.05, 1.0, 1.0,
            "An assessable sit-to-stand transition was confirmed.",
        ))
    transition_related = (transition,) if confirmed and transition else ()

    rise = by_name.get("rise_duration_s")
    if confirmed and rise and isinstance(rise.feature_value, (int, float)):
        value = float(rise.feature_value)
        rapid = float(thresholds["rapid_rise_duration_s"])
        slow = float(thresholds["slow_rise_duration_s"])
        if value <= rapid:
            evidences.append(_evidence(job, "rapid_rise", rise, (rapid - value) / rapid, value, rapid, "Rise speed is faster than the engineering reference and is retained as a trend observation.", related=transition_related, time_scale=TimeScale.MEDIUM))
        elif value >= slow:
            evidences.append(_evidence(job, "slow_rise", rise, (value - slow) / slow, value, slow, "Rise speed is slower than the engineering reference and is retained as a trend observation.", related=transition_related, time_scale=TimeScale.MEDIUM))

    sway = by_name.get("trunk_sway_angle_deg")
    reversals = by_name.get("post_rise_sway_reversal_count")
    if confirmed and sway and isinstance(sway.feature_value, (int, float)):
        value = float(sway.feature_value)
        threshold = float(thresholds["trunk_sway_amplitude_deg"])
        enough_reversals = bool(reversals and isinstance(reversals.feature_value, (int, float)) and float(reversals.feature_value) >= thresholds["trunk_sway_min_reversals"])
        if value >= threshold and enough_reversals:
            evidences.append(_evidence(job, "trunk_sway", sway, _severity(value, threshold, ruleset.severity_saturation["trunk_sway"]), value, threshold, f"Post-rise trunk sway exceeded the {ruleset.version} engineering threshold.", related=tuple(item for item in (*transition_related, reversals) if item)))

    for feature, evidence_type, threshold_name, saturation_name in (
        ("post_rise_pelvis_lateral_excursion_norm", "post_rise_lateral_drift", "post_rise_lateral_excursion_norm", "post_rise_lateral_drift"),
        ("post_rise_support_width_change_norm", "support_base_change", "post_rise_support_width_change_norm", "support_base_change"),
    ):
        item = by_name.get(feature)
        if confirmed and item and isinstance(item.feature_value, (int, float)):
            value = float(item.feature_value)
            threshold = float(thresholds[threshold_name])
            if value >= threshold:
                evidences.append(_evidence(job, evidence_type, item, _severity(value, threshold, ruleset.severity_saturation[saturation_name]), value, threshold, f"{evidence_type} exceeded the {ruleset.version} engineering threshold.", related=transition_related))

    steps = by_name.get("post_rise_compensatory_step_count")
    feet = by_name.get("post_rise_feet_visibility")
    feet_usable = bool(feet and isinstance(feet.feature_value, (int, float)) and float(feet.feature_value) >= thresholds["post_rise_feet_visibility"])
    if confirmed and feet_usable and steps and isinstance(steps.feature_value, (int, float)):
        value = float(steps.feature_value)
        threshold = float(thresholds["post_rise_compensatory_step_count"])
        if value >= threshold:
            evidences.append(_evidence(job, "compensatory_step", steps, _severity(value, threshold, ruleset.severity_saturation["compensatory_step"]), value, threshold, "A post-rise compensatory step proxy was detected.", related=tuple(item for item in (*transition_related, feet) if item)))

    asymmetry = by_name.get("step_asymmetry_ratio")
    locomotion = by_name.get("locomotion_duration_s")
    locomotion_usable = locomotion is None or (isinstance(locomotion.feature_value, (int, float)) and float(locomotion.feature_value) >= 0.5)
    if locomotion_usable and asymmetry and isinstance(asymmetry.feature_value, (int, float)):
        value = float(asymmetry.feature_value)
        threshold = float(thresholds["gait_asymmetry_ratio"])
        if value >= threshold:
            evidences.append(_evidence(job, "gait_instability", asymmetry, _severity(value, threshold, ruleset.severity_saturation["gait_instability"]), value, threshold, f"Active-window gait asymmetry exceeded the {ruleset.version} trend threshold.", time_scale=TimeScale.MEDIUM))

    stable = by_name.get("stable_posture_duration")
    angle = by_name.get("stable_trunk_angle_deg")
    if stable and angle and isinstance(stable.feature_value, (int, float)) and isinstance(angle.feature_value, (int, float)) and float(stable.feature_value) >= thresholds["stable_posture_seconds"] and float(angle.feature_value) <= 8.0:
        evidences.append(_evidence(job, "posture_recovered", stable, min(float(stable.feature_value) / 30.0, 1.0), float(stable.feature_value), float(thresholds["stable_posture_seconds"]), "Stable posture met the recovery threshold.", related=(angle,)))
    return evidences


def _failed(job: AlgorithmJob, started_at: datetime, code: str) -> AdapterBatch:
    return validate_batch_for_job(AdapterBatch(
        schema_version="adapter-batch/1.0", job_id=job.job_id, module=MODULE,
        adapter_version=ADAPTER_VERSION, status=AdapterStatus.FAILED,
        started_at=started_at, completed_at=_now(), observations=[], evidences=[],
        error=AdapterError(code=code, message="v1.4 gait input could not be analyzed.", retryable=False),
    ), job)


async def run_with_config(
    job: AlgorithmJob, *, quality_gate: bool = True, offline_ablation: bool = False,
) -> AdapterBatch:
    if not quality_gate and not offline_ablation:
        raise ValueError("QUALITY_GATE_BYPASS_IS_OFFLINE_ONLY")
    started_at = _now()
    try:
        features, diagnostics = await asyncio.to_thread(_read, job)
        quality = _quality(features)
        if not quality_gate and features.get("pre_quality_assessment_status"):
            features["assessment_status"] = features["pre_quality_assessment_status"]
            features["assessment_reason_code"] = features.get(
                "pre_quality_assessment_reason_code", "NO_SIT_TO_STAND_TRANSITION"
            )
            quality = max(quality, 0.7)
        observations = [_observation(job, name, features[name], quality) for name in FEATURES if name in features]
        evidences = _build(job, observations, quality_gate=quality_gate)
        indeterminate = quality_gate and any(item.evidence_type == "assessment_indeterminate" for item in evidences)
        if job.media_type == MediaType.IMAGE:
            evidences, status = [], AdapterStatus.NO_EVIDENCE
        elif indeterminate:
            status = AdapterStatus.LOW_QUALITY
        elif evidences:
            status = AdapterStatus.SUCCESS
        else:
            status = AdapterStatus.NO_EVIDENCE
        diagnostics.update({
            "ruleset_version": RULESET.version,
            "quality_gate_status": "FAILED" if indeterminate else diagnostics.get("quality_gate_status", "PASS"),
            "relative_speed_evidence_deferred_to_backend": True,
            "quality_gate_enabled": quality_gate,
            "feature_names": [item.feature_name for item in observations],
        })
        return validate_batch_for_job(AdapterBatch(
            schema_version="adapter-batch/1.0", job_id=job.job_id, module=MODULE,
            adapter_version=ADAPTER_VERSION, status=status, started_at=started_at,
            completed_at=_now(), observations=observations, evidences=evidences,
            diagnostics=diagnostics,
        ), job)
    except (OSError, ValueError, json.JSONDecodeError, csv.Error) as exc:
        return _failed(job, started_at, "FEATURE_INPUT_INVALID")


async def run(job: AlgorithmJob) -> AdapterBatch:
    return await run_with_config(job, quality_gate=True)
