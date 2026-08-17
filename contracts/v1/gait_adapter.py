"""Async GaitAdapter entrypoint for backend algorithm jobs.

The adapter accepts a backend AlgorithmJob, extracts gait features from a
local video or reads precomputed JSON/CSV features, and returns a pure adapter
batch. It does not persist media or evaluate final risk levels.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.v1.algorithm import (
    AdapterBatch,
    AdapterError,
    AdapterStatus,
    AlgorithmJob,
    AlgorithmModule,
    MediaType,
    validate_batch_for_job,
)
from contracts.v1.models import Evidence, Observation, RiskDomain, TimeScale
from contracts.v1.gait_video import GaitVideoError, VIDEO_SUFFIXES, extract_gait_features


ADAPTER_VERSION = "gait-adapter-v1"
MODULE = AlgorithmModule.GAIT

FROZEN_FEATURES: tuple[str, ...] = (
    "rise_duration_s",
    "hip_vertical_speed_norm_s",
    "trunk_sway_angle_deg",
    "com_offset_norm",
    "step_speed_norm_s",
    "step_asymmetry_ratio",
    "turn_angular_velocity_deg_s",
    "support_distance_norm",
    "stable_posture_duration",
    "stable_trunk_angle_deg",
    "valid_frame_ratio",
)

FEATURE_ALIASES = {
    "sit_to_stand_duration": "rise_duration_s",
    "rise_duration": "rise_duration_s",
    "trunk_sway_angle": "trunk_sway_angle_deg",
    "step_speed": "step_speed_norm_s",
    "step_length_asymmetry_ratio": "step_asymmetry_ratio",
    "tracking_ratio": "valid_frame_ratio",
}

FEATURE_UNITS = {
    "rise_duration_s": "second",
    "hip_vertical_speed_norm_s": "norm_per_second",
    "trunk_sway_angle_deg": "degree",
    "com_offset_norm": "norm",
    "step_speed_norm_s": "norm_per_second",
    "step_asymmetry_ratio": "ratio",
    "turn_angular_velocity_deg_s": "degree_per_second",
    "support_distance_norm": "norm",
    "stable_posture_duration": "second",
    "stable_trunk_angle_deg": "degree",
    "valid_frame_ratio": "ratio",
}


class _FeatureInputError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _stable_id(prefix: str, *parts: object) -> str:
    text = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _read_feature_payload(media_locator: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not media_locator:
        raise _FeatureInputError("missing_media_locator")

    if media_locator.startswith("file://"):
        media_locator = media_locator[7:]
    if "://" in media_locator:
        raise _FeatureInputError("only_local_media_supported")
    path = Path(media_locator).expanduser()
    if not path.exists() or not path.is_file():
        raise _FeatureInputError("media_locator_not_readable")

    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = _features_from_json(payload)
        if not features:
            raise _FeatureInputError("feature_payload_empty")
        return features, {"feature_source_type": "json"}

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            raise _FeatureInputError("empty_feature_csv")
        features = _features_from_mapping(rows[0])
        if not features:
            raise _FeatureInputError("feature_payload_empty")
        return features, {"feature_source_type": "csv", "feature_rows": len(rows)}

    if path.suffix.lower() in VIDEO_SUFFIXES:
        try:
            return extract_gait_features(path)
        except GaitVideoError as exc:
            raise _FeatureInputError(str(exc)) from exc

    raise _FeatureInputError("unsupported_media_locator")


def _features_from_json(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in ("features", "gait_features", "metrics"):
        if isinstance(payload.get(key), dict):
            return _features_from_mapping(payload[key])
    if isinstance(payload.get("observation"), dict):
        return _features_from_mapping({payload["observation"].get("feature_name"): payload["observation"].get("feature_value")})
    if isinstance(payload.get("observations"), list):
        return _features_from_mapping(
            {
                item.get("feature_name"): item.get("feature_value")
                for item in payload["observations"]
                if isinstance(item, dict)
            }
        )
    return _features_from_mapping(payload)


def _features_from_mapping(payload: dict[Any, Any]) -> dict[str, Any]:
    features: dict[str, Any] = {}
    for raw_key, value in payload.items():
        if raw_key is None or value in (None, ""):
            continue
        key = FEATURE_ALIASES.get(str(raw_key), str(raw_key))
        if key in FROZEN_FEATURES:
            features[key] = _coerce_value(value)
    return features


def _coerce_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 3)
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return value


def _score(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def _quality(features: dict[str, Any]) -> float:
    valid_ratio = features.get("valid_frame_ratio")
    if isinstance(valid_ratio, (int, float)):
        return _score(float(valid_ratio))
    return 0.85


def _observation(job: AlgorithmJob, feature_name: str, value: Any, data_quality: float) -> Observation:
    return Observation(
        schema_version="1.0",
        observation_id=_stable_id("obs-gait", job.job_id, job.resident_id, job.asset_id, feature_name),
        resident_id=job.resident_id,
        timestamp=job.captured_at,
        source="gait_adapter",
        feature_name=feature_name,
        feature_value=value,
        unit=FEATURE_UNITS[feature_name],
        location=job.location,
        confidence=_score(0.72 + 0.25 * data_quality),
        data_quality=data_quality,
        source_mode=job.source_mode,
        asset_id=job.asset_id,
        simulated=job.simulated,
        metadata={
            "adapter_module": MODULE.value,
            "media_type": job.media_type.value,
            "camera_position_id": job.camera_position_id,
            "scene_config_id": job.scene_config_id,
        },
    )


def _evidence(
    job: AlgorithmJob,
    evidence_type: str,
    observation: Observation,
    severity: float,
    current_value: float | None,
    baseline_value: float | None,
    explanation: str,
) -> Evidence:
    deviation = None
    if current_value is not None and baseline_value not in (None, 0):
        deviation = (current_value - baseline_value) / baseline_value
    return Evidence(
        schema_version="1.0",
        evidence_id=_stable_id("evi-gait", job.job_id, job.resident_id, job.asset_id, evidence_type, observation.observation_id),
        observation_ids=[observation.observation_id],
        resident_id=job.resident_id,
        timestamp=job.captured_at,
        risk_domain=RiskDomain.FALL,
        evidence_type=evidence_type,
        severity=_score(severity),
        confidence=_score(observation.confidence),
        data_quality=_score(observation.data_quality),
        baseline_value=None if baseline_value is None else round(baseline_value, 3),
        current_value=None if current_value is None else round(current_value, 3),
        baseline_deviation=None if deviation is None else round(deviation, 3),
        time_scale=TimeScale.SHORT,
        location=job.location,
        explanation=explanation,
        adapter_version=ADAPTER_VERSION,
        source_mode=job.source_mode,
        simulated=job.simulated,
    )


def _build_evidences(job: AlgorithmJob, observations: list[Observation]) -> list[Evidence]:
    by_feature = {item.feature_name: item for item in observations}
    evidences: list[Evidence] = []

    rise = by_feature.get("rise_duration_s")
    if rise and isinstance(rise.feature_value, (int, float)):
        value = float(rise.feature_value)
        if value <= 1.5:
            evidences.append(_evidence(job, "rapid_rise", rise, (1.5 - value) / 1.5, value, 2.5, "起身时长短于规则基线，提示快速起身。"))
        elif value >= 3.5:
            evidences.append(_evidence(job, "slow_rise", rise, (value - 3.5) / 3.5, value, 2.5, "起身时长长于规则阈值，提示缓慢起身。"))

    sway = by_feature.get("trunk_sway_angle_deg")
    if sway and isinstance(sway.feature_value, (int, float)) and float(sway.feature_value) >= 12.0:
        value = float(sway.feature_value)
        evidences.append(_evidence(job, "trunk_sway", sway, (value - 12.0) / 18.0, value, 8.0, "躯干摆动角度超过步态稳定阈值。"))

    asymmetry = by_feature.get("step_asymmetry_ratio")
    if asymmetry and isinstance(asymmetry.feature_value, (int, float)) and float(asymmetry.feature_value) >= 0.35:
        value = float(asymmetry.feature_value)
        evidences.append(_evidence(job, "gait_instability", asymmetry, (value - 0.35) / 0.45, value, 0.18, "步态左右不对称超过规则阈值。"))

    speed = by_feature.get("step_speed_norm_s")
    if speed and isinstance(speed.feature_value, (int, float)):
        value = float(speed.feature_value)
        if value <= 0.45 or value >= 1.55:
            evidences.append(_evidence(job, "relative_speed_change", speed, abs(value - 1.0), value, 1.0, "相对步速偏离规则基线。"))

    stable_duration = by_feature.get("stable_posture_duration")
    stable_angle = by_feature.get("stable_trunk_angle_deg")
    if stable_duration and stable_angle and isinstance(stable_duration.feature_value, (int, float)) and isinstance(stable_angle.feature_value, (int, float)):
        duration = float(stable_duration.feature_value)
        angle = float(stable_angle.feature_value)
        if duration >= 15.0 and angle <= 8.0:
            evidences.append(_evidence(job, "posture_recovered", stable_duration, min(duration / 30.0, 1.0), duration, 15.0, "稳定姿态持续时间达到恢复观察阈值。"))

    valid_ratio = by_feature.get("valid_frame_ratio")
    if valid_ratio and isinstance(valid_ratio.feature_value, (int, float)) and float(valid_ratio.feature_value) < 0.65:
        value = float(valid_ratio.feature_value)
        evidences.append(_evidence(job, "tracking_lost", valid_ratio, (0.65 - value) / 0.65, value, 0.65, "有效姿态帧比例低于输入质量阈值。"))

    return evidences


def _failed_batch(
    job: AlgorithmJob,
    started_at: datetime,
    *,
    code: str,
    message: str,
) -> AdapterBatch:
    batch = AdapterBatch(
        schema_version="adapter-batch/1.0",
        job_id=job.job_id,
        module=MODULE,
        adapter_version=ADAPTER_VERSION,
        status=AdapterStatus.FAILED,
        started_at=started_at,
        completed_at=_now(),
        observations=[],
        evidences=[],
        resident_response_candidate=None,
        diagnostics={},
        error=AdapterError(code=code, message=message, retryable=False),
    )
    return validate_batch_for_job(batch, job)


async def run(job: AlgorithmJob) -> AdapterBatch:
    started_at = _now()
    try:
        features, diagnostics = await asyncio.to_thread(_read_feature_payload, job.media_locator)
        data_quality = _quality(features)
        observations = [
            _observation(job, feature_name, features[feature_name], data_quality)
            for feature_name in FROZEN_FEATURES
            if feature_name in features
        ]
        evidences = _build_evidences(job, observations)

        if job.media_type == MediaType.IMAGE:
            evidences = []
            status = AdapterStatus.NO_EVIDENCE
        elif data_quality < 0.65:
            evidences = [item for item in evidences if item.evidence_type == "tracking_lost"]
            status = AdapterStatus.LOW_QUALITY
        elif evidences:
            status = AdapterStatus.SUCCESS
        else:
            status = AdapterStatus.NO_EVIDENCE

        diagnostics.update(
            {
                "feature_names": [item.feature_name for item in observations],
                "evidence_types": [item.evidence_type for item in evidences],
                "quality_threshold": 0.65,
            }
        )
        batch = AdapterBatch(
            schema_version="adapter-batch/1.0",
            job_id=job.job_id,
            module=MODULE,
            adapter_version=ADAPTER_VERSION,
            status=status,
            started_at=started_at,
            completed_at=_now(),
            observations=observations,
            evidences=evidences,
            resident_response_candidate=None,
            diagnostics=diagnostics,
            error=None,
        )
        return validate_batch_for_job(batch, job)
    except _FeatureInputError as exc:
        return _failed_batch(
            job,
            started_at,
            code="FEATURE_INPUT_INVALID",
            message=f"Invalid gait feature input: {exc}",
        )
    except (json.JSONDecodeError, UnicodeDecodeError, csv.Error, OSError, TypeError, ValueError) as exc:
        return _failed_batch(
            job,
            started_at,
            code="FEATURE_INPUT_INVALID",
            message=f"Unable to read a valid gait feature payload ({type(exc).__name__})",
        )
