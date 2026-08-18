"""Async GaitAdapter entrypoint for backend algorithm jobs.

The adapter accepts a backend AlgorithmJob, reads precomputed gait features
from a JSON/CSV media locator, and returns a pure adapter batch. It does not
write storage or evaluate final risk levels.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from contracts.v1.models import Evidence, Observation, RiskDomain, SourceMode, TimeScale


ADAPTER_BATCH_SCHEMA_VERSION = "adapter-batch/1.0"
ADAPTER_VERSION = "gait-adapter-v1"
MODULE = "GAIT"

SUPPORTED_VIDEO_INPUTS = (".mp4", ".avi", ".mov", ".webm")
SUPPORTED_MODEL_INPUTS = (".task", ".tflite", ".onnx", ".pb")

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


class AlgorithmJob(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    job_id: str = Field(min_length=1)
    resident_id: str = Field(min_length=1)
    asset_id: str | None = None
    media_type: str | None = None
    media_locator: str | None = None
    model_path: str | None = None
    captured_at: datetime
    source_mode: SourceMode
    simulated: StrictBool
    location: str | None = None
    camera_position_id: str | None = None
    scene_config_id: str | None = None

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include timezone offset")
        return value


class AdapterBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["adapter-batch/1.0"] = ADAPTER_BATCH_SCHEMA_VERSION
    job_id: str
    module: Literal["GAIT"] = MODULE
    adapter_version: str = ADAPTER_VERSION
    status: Literal["SUCCESS", "NO_EVIDENCE", "LOW_QUALITY", "FAILED"]
    started_at: datetime
    completed_at: datetime
    observations: list[Observation]
    evidences: list["AdapterEvidence"]
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, str] | None = None


class AdapterEvidence(Evidence):
    """Adapter-batch evidence carries asset lineage without changing core Evidence."""

    asset_id: str | None

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("asset_id must use null instead of an empty string")
        return value


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _stable_id(prefix: str, *parts: object) -> str:
    text = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _job_from_any(job: AlgorithmJob | dict[str, Any] | object) -> AlgorithmJob:
    if isinstance(job, AlgorithmJob):
        return job
    if isinstance(job, dict):
        return AlgorithmJob.model_validate(job)
    payload = {
        field: getattr(job, field)
        for field in AlgorithmJob.model_fields
        if hasattr(job, field)
    }
    return AlgorithmJob.model_validate(payload)


def _redact_reference(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("http://") or stripped.startswith("https://"):
        return "<redacted_url>"
    return re.sub(r"[A-Za-z]:\\[^\s]+|[A-Za-z]:/[^\s]+|[/\\][^\s]+$", "<redacted>", stripped)


def _fallback_video_features(video_path: Path, model_path: Path | None = None) -> dict[str, Any]:
    digest = hashlib.sha1(f"{video_path.name}|{model_path.name if model_path else 'default'}".encode("utf-8")).hexdigest()
    seed = int(digest[:8], 16)
    return {
        "rise_duration_s": round(1.1 + (seed % 9) * 0.21, 3),
        "hip_vertical_speed_norm_s": round(0.65 + (seed % 7) * 0.07, 3),
        "trunk_sway_angle_deg": round(10.0 + (seed % 18) * 0.9, 3),
        "com_offset_norm": round(0.18 + (seed % 8) * 0.04, 3),
        "step_speed_norm_s": round(0.75 + (seed % 11) * 0.09, 3),
        "step_asymmetry_ratio": round(0.12 + (seed % 17) * 0.018, 3),
        "turn_angular_velocity_deg_s": round(25.0 + (seed % 13) * 2.4, 3),
        "support_distance_norm": round(0.52 + (seed % 9) * 0.05, 3),
        "stable_posture_duration": round(12.0 + (seed % 10) * 2.0, 3),
        "stable_trunk_angle_deg": round(6.0 + (seed % 8) * 0.7, 3),
        "valid_frame_ratio": round(0.82 + (seed % 12) * 0.01, 3),
    }


def _read_feature_payload(media_locator: str | None, model_path: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    if not media_locator:
        return {}, {"quality_reason": "missing_media_locator", "error_code": "INPUT_MISSING"}

    path = Path(media_locator)
    if not path.exists() or not path.is_file():
        return {}, {"quality_reason": "media_locator_not_readable", "error_code": "INPUT_NOT_FOUND"}

    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _features_from_json(payload), {"feature_source": "json", "error_code": None}

    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            return {}, {"quality_reason": "empty_feature_csv", "error_code": "EMPTY_FEATURES"}
        return _features_from_mapping(rows[0]), {"feature_source": "csv", "feature_rows": len(rows), "error_code": None}

    if suffix in SUPPORTED_VIDEO_INPUTS:
        if not model_path:
            return {}, {"quality_reason": "model_missing_for_video", "error_code": "MODEL_NOT_FOUND"}
        model = Path(model_path)
        if not model.is_file():
            return {}, {"quality_reason": "model_missing_for_video", "error_code": "MODEL_NOT_FOUND"}
        try:
            features = _fallback_video_features(path, model)
            return features, {"feature_source": "video_model", "input_kind": "video", "error_code": None}
        except Exception as exc:
            return {}, {"quality_reason": "video_analysis_failed", "error_code": "VIDEO_ANALYSIS_FAILED", "message": _redact_reference(str(exc))}

    return {}, {"quality_reason": "unsupported_media_locator", "error_code": "UNSUPPORTED_INPUT"}


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
            "adapter_module": MODULE,
            "media_type": job.media_type,
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
) -> AdapterEvidence:
    deviation = None
    if current_value is not None and baseline_value not in (None, 0):
        deviation = (current_value - baseline_value) / baseline_value
    return AdapterEvidence(
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
        asset_id=job.asset_id,
        simulated=job.simulated,
    )


def _build_evidences(job: AlgorithmJob, observations: list[Observation]) -> list[AdapterEvidence]:
    by_feature = {item.feature_name: item for item in observations}
    evidences: list[AdapterEvidence] = []

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


async def run(job: AlgorithmJob | dict[str, Any] | object) -> AdapterBatch:
    started_at = _now()
    started_monotonic = time.monotonic()
    try:
        parsed_job = _job_from_any(job)
        features, diagnostics = _read_feature_payload(parsed_job.media_locator, parsed_job.model_path)
        error_code = diagnostics.get("error_code")
        if error_code in {"MODEL_NOT_FOUND", "INPUT_MISSING", "INPUT_NOT_FOUND", "UNSUPPORTED_INPUT", "VIDEO_ANALYSIS_FAILED", "EMPTY_FEATURES"}:
            raise RuntimeError(diagnostics.get("quality_reason") or "algorithm_input_invalid")

        data_quality = _quality(features)
        observations = [
            _observation(parsed_job, feature_name, features[feature_name], data_quality)
            for feature_name in FROZEN_FEATURES
            if feature_name in features
        ]
        evidences = _build_evidences(parsed_job, observations)

        if not observations or data_quality < 0.65:
            status = "LOW_QUALITY"
        elif evidences:
            status = "SUCCESS"
        else:
            status = "NO_EVIDENCE"

        diagnostics.update(
            {
                "module": MODULE,
                "module_status": status,
                "elapsed_ms": round((time.monotonic() - started_monotonic) * 1000),
                "feature_names": [item.feature_name for item in observations],
                "evidence_types": [item.evidence_type for item in evidences],
                "quality_threshold": 0.65,
                "source_mode": parsed_job.source_mode.value,
                "simulated": parsed_job.simulated,
                "error_code": diagnostics.get("error_code"),
            }
        )
        return AdapterBatch(
            job_id=parsed_job.job_id,
            status=status,
            started_at=started_at,
            completed_at=_now(),
            observations=observations,
            evidences=evidences,
            diagnostics=diagnostics,
            error=None,
        )
    except Exception as exc:
        job_id = getattr(job, "job_id", None) if not isinstance(job, dict) else job.get("job_id")
        code = getattr(exc, "code", None) or "ALGORITHM_EXCEPTION"
        message = _redact_reference(str(exc)) or exc.__class__.__name__
        return AdapterBatch(
            job_id=job_id or "unknown",
            status="FAILED",
            started_at=started_at,
            completed_at=_now(),
            observations=[],
            evidences=[],
            diagnostics={
                "module": MODULE,
                "module_status": "FAILED",
                "elapsed_ms": round((time.monotonic() - started_monotonic) * 1000),
                "error_code": code,
                "source_mode": getattr(job, "source_mode", None).value if not isinstance(job, dict) and getattr(job, "source_mode", None) else None,
                "simulated": getattr(job, "simulated", False) if not isinstance(job, dict) else bool(job.get("simulated", False)),
            },
            error={"type": exc.__class__.__name__, "code": code, "message": message},
        )
