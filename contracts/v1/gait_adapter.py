"""Async GaitAdapter entrypoint for backend algorithm jobs.

The adapter accepts a backend AlgorithmJob, reads precomputed gait features
from a JSON/CSV media locator, and returns a pure adapter batch. It does not
write storage or evaluate final risk levels.
"""

from __future__ import annotations

import csv
import hashlib
import math
import json
import re
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import cv2
import mediapipe as mp
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from contracts.v1.models import Evidence, Observation, RiskDomain, SourceMode, TimeScale


ADAPTER_BATCH_SCHEMA_VERSION = "adapter-batch/1.0"
ADAPTER_VERSION = "gait-adapter-v1"
MODULE = "GAIT"
VIDEO_STEP_SPEED_SCALE = 25.0

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


class AlgorithmInputError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class FramePacket:
    frame_bgr: np.ndarray
    frame_index: int
    timestamp_ms: int


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


def _build_landmarker(model_path: Path) -> vision.PoseLandmarker:
    base_options = python.BaseOptions(model_asset_buffer=model_path.read_bytes())
    options = vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return vision.PoseLandmarker.create_from_options(options)


def _iter_video_frames(video_path: Path, fps_hint: float = 30.0) -> tuple[list[FramePacket], float]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Unable to open video: {video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or fps_hint
    frames: list[FramePacket] = []
    frame_index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        timestamp_ms = int(frame_index * 1000 / fps)
        frames.append(FramePacket(frame_bgr=frame, frame_index=frame_index, timestamp_ms=timestamp_ms))
        frame_index += 1
    capture.release()
    return frames, fps


def _safe_mean(values: list[float]) -> float:
    return float(np.mean(np.asarray(values, dtype=np.float64))) if values else 0.0


def _smooth(values: list[float], window: int = 5) -> list[float]:
    if len(values) <= 2 or window <= 1:
        return values[:]
    radius = max(window // 2, 1)
    smoothed: list[float] = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        smoothed.append(float(np.mean(values[start:end])))
    return smoothed


def _dominant_frequency_hz(signal_values: list[float], timestamps_ms: list[int]) -> float:
    if len(signal_values) < 8 or len(timestamps_ms) < 8:
        return 0.0
    durations = np.diff(np.asarray(timestamps_ms, dtype=np.float64)) / 1000.0
    if np.any(durations <= 0):
        return 0.0
    sample_spacing = float(np.mean(durations))
    centered = np.asarray(signal_values, dtype=np.float64) - float(np.mean(signal_values))
    freqs = np.fft.rfftfreq(len(centered), d=sample_spacing)
    power = np.abs(np.fft.rfft(centered)) ** 2
    mask = (freqs >= 0.1) & (freqs <= 3.0)
    if not np.any(mask):
        return 0.0
    masked_freqs = freqs[mask]
    masked_power = power[mask]
    if masked_power.size == 0:
        return 0.0
    return float(masked_freqs[int(np.argmax(masked_power))])


def _asymmetry_ratio(left_series: list[float], right_series: list[float]) -> float:
    left = np.asarray(left_series, dtype=np.float64)
    right = np.asarray(right_series, dtype=np.float64)
    if left.size == 0 or right.size == 0:
        return 0.0
    left_mean = float(np.mean(left))
    right_mean = float(np.mean(right))
    denom = max(left_mean, right_mean, 1e-6)
    return abs(left_mean - right_mean) / denom


def _find_upward_window(
    rows: list[dict[str, Any]],
    min_duration_s: float,
    max_duration_s: float,
    min_upward_displacement: float,
) -> tuple[float, float] | None:
    best: tuple[float, float] | None = None
    for start_index in range(len(rows)):
        for end_index in range(start_index + 1, len(rows)):
            duration_s = (int(rows[end_index]["timestamp_ms"]) - int(rows[start_index]["timestamp_ms"])) / 1000.0
            if duration_s < min_duration_s:
                continue
            if duration_s > max_duration_s:
                break
            upward_displacement = float(rows[start_index]["pelvis_y"]) - float(rows[end_index]["pelvis_y"])
            if upward_displacement < min_upward_displacement:
                continue
            upward_speed = upward_displacement / max(duration_s, 1e-6)
            if best is None or upward_speed > best[1]:
                best = (duration_s, upward_speed)
    return best


def _detect_video_features(video_path: Path, model_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        frames, fps = _iter_video_frames(video_path)
    except Exception as exc:
        return {}, {"quality_reason": "video_unreadable", "error_code": "INPUT_NOT_FOUND", "message": _redact_reference(str(exc))}
    if not frames:
        return {}, {"quality_reason": "empty_video", "error_code": "EMPTY_FEATURES"}

    detector = _build_landmarker(model_path)
    frame_rows: list[dict[str, Any]] = []
    try:
        for packet in frames:
            frame_rgb = cv2.cvtColor(packet.frame_bgr, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
            detection_result = detector.detect_for_video(mp_image, packet.timestamp_ms)
            if not detection_result.pose_landmarks:
                continue
            pose = detection_result.pose_landmarks[0]
            if len(pose) < 33:
                continue

            left_shoulder = pose[11]
            right_shoulder = pose[12]
            left_hip = pose[23]
            right_hip = pose[24]
            left_ankle = pose[27]
            right_ankle = pose[28]
            core_visibility = [float(getattr(pose[idx], "visibility", 0.0)) for idx in (11, 12, 23, 24, 27, 28)]
            pelvis_x = (left_hip.x + right_hip.x) / 2.0
            pelvis_y = (left_hip.y + right_hip.y) / 2.0
            shoulder_x = (left_shoulder.x + right_shoulder.x) / 2.0
            shoulder_y = (left_shoulder.y + right_shoulder.y) / 2.0
            trunk_dx = shoulder_x - pelvis_x
            trunk_dy = shoulder_y - pelvis_y
            trunk_angle_deg = math.degrees(math.atan2(trunk_dx, -trunk_dy))

            frame_rows.append(
                {
                    "timestamp_ms": int(packet.timestamp_ms),
                    "pelvis_x": pelvis_x,
                    "pelvis_y": pelvis_y,
                    "trunk_angle_deg": trunk_angle_deg,
                    "left_stride_extent": abs(left_ankle.x - pelvis_x),
                    "right_stride_extent": abs(right_ankle.x - pelvis_x),
                    "core_visibility_mean": _safe_mean(core_visibility),
                    "frame_quality": min(core_visibility),
                }
            )
    finally:
        detector.close()

    if not frame_rows:
        return {}, {
            "feature_source": "video_mediapipe",
            "input_kind": "video",
            "fps": round(float(fps), 3),
            "detected_frames": 0,
            "total_frames": len(frames),
            "valid_frame_ratio": 0.0,
            "error_code": "EMPTY_FEATURES",
            "quality_reason": "no_pose_detected",
        }

    pelvis_x_series = _smooth([float(row["pelvis_x"]) for row in frame_rows])
    pelvis_y_series = _smooth([float(row["pelvis_y"]) for row in frame_rows])
    trunk_angle_series = _smooth([float(row["trunk_angle_deg"]) for row in frame_rows])
    left_extent_series = _smooth([float(row["left_stride_extent"]) for row in frame_rows])
    right_extent_series = _smooth([float(row["right_stride_extent"]) for row in frame_rows])
    timestamps_ms_series = [int(row["timestamp_ms"]) for row in frame_rows]

    for index, row in enumerate(frame_rows):
        row["pelvis_x_smooth"] = pelvis_x_series[index]
        row["pelvis_y_smooth"] = pelvis_y_series[index]
        row["trunk_angle_deg_smooth"] = trunk_angle_series[index]
        row["left_stride_extent_smooth"] = left_extent_series[index]
        row["right_stride_extent_smooth"] = right_extent_series[index]

    if len(frame_rows) > 1:
        path_length = 0.0
        for idx in range(1, len(frame_rows)):
            dx = pelvis_x_series[idx] - pelvis_x_series[idx - 1]
            dy = pelvis_y_series[idx] - pelvis_y_series[idx - 1]
            path_length += math.hypot(dx, dy)
        duration_seconds = max((timestamps_ms_series[-1] - timestamps_ms_series[0]) / 1000.0, 1e-6)
        step_speed = path_length / duration_seconds
    else:
        step_speed = 0.0

    rapid_window = _find_upward_window(frame_rows, 0.4, 1.5, 0.05)
    rise_duration_s = None if rapid_window is None else round(rapid_window[0], 3)
    valid_frame_ratio = len(frame_rows) / max(len(frames), 1)
    summary = {
        "feature_source": "video_mediapipe",
        "input_kind": "video",
        "fps": round(float(fps), 3),
        "total_frames": len(frames),
        "detected_frames": len(frame_rows),
        "valid_frame_ratio": round(float(valid_frame_ratio), 3),
        "step_speed_norm_s": round(float(step_speed) * VIDEO_STEP_SPEED_SCALE, 3),
        "trunk_sway_angle_deg": round(max(abs(value) for value in trunk_angle_series), 3),
        "step_asymmetry_ratio": round(_asymmetry_ratio(left_extent_series, right_extent_series), 3),
        "stable_posture_duration": 0.0,
        "stable_trunk_angle_deg": round(min(abs(value) for value in trunk_angle_series), 3),
        "mean_core_visibility": round(_safe_mean([float(row["core_visibility_mean"]) for row in frame_rows]), 3),
    }
    if rise_duration_s is not None:
        summary["rise_duration_s"] = rise_duration_s
    return summary, {
        "feature_source": "video_mediapipe",
        "input_kind": "video",
        "fps": round(float(fps), 3),
        "total_frames": len(frames),
        "detected_frames": len(frame_rows),
        "valid_frame_ratio": round(float(valid_frame_ratio), 3),
        "quality_reason": "ok",
        "error_code": None,
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
            return _detect_video_features(path, model)
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
            raise AlgorithmInputError(str(error_code), diagnostics.get("quality_reason") or "algorithm_input_invalid")

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
