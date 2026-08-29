"""Extract frozen gait features from one local video without persisting frames."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from statistics import mean, median
from typing import Any


POSE_MODEL_ENV = "YINGMU_GAIT_POSE_MODEL"
DEFAULT_POSE_MODEL = "models/pose_landmarker_heavy.task"
VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
POST_RISE_SWAY_WINDOW_SECONDS = 5.0
MIN_SWAY_WINDOW_SAMPLES = 5
MIN_TRANSITION_CONTEXT_SECONDS = 0.5
MIN_ORIENTATION_QUALITY = 0.45
MAX_ORIENTATION_CHANGE = 0.45
MIN_POST_RISE_TRACKING_RATIO = 0.65
COMPENSATORY_STEP_MOTION_NORM = 0.30
LOCOMOTION_PATH_NORM = 0.80

LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_KNEE, RIGHT_KNEE = 25, 26
LEFT_ANKLE, RIGHT_ANKLE = 27, 28
CORE_IDS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP, LEFT_ANKLE, RIGHT_ANKLE)


class GaitVideoError(ValueError):
    """A sanitized video-extraction failure safe to return in diagnostics."""


@dataclass(frozen=True)
class PoseVideoAnalysis:
    features: dict[str, Any]
    diagnostics: dict[str, Any]
    trajectory_points: tuple[tuple[float, float, float, float], ...]
    illumination_norm: float


def _mean(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _smooth(values: list[float], radius: int = 2) -> list[float]:
    return [
        _mean(values[max(0, index - radius) : min(len(values), index + radius + 1)])
        for index in range(len(values))
    ]


def _percentile(values: list[float], quantile: float) -> float:
    """Deterministic linear percentile matching the common P95/P5 definition."""
    if not values:
        raise ValueError("percentile_requires_values")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _median(rows: list[dict[str, float]], key: str, default: float = 0.0) -> float:
    values = [float(row[key]) for row in rows if key in row and math.isfinite(float(row[key]))]
    return float(median(values)) if values else default


def _range(values: list[float]) -> float:
    return max(values) - min(values) if values else 0.0


def _joint_angle(a: Any, b: Any, c: Any) -> float:
    ab = (float(a.x) - float(b.x), float(a.y) - float(b.y))
    cb = (float(c.x) - float(b.x), float(c.y) - float(b.y))
    denominator = math.hypot(*ab) * math.hypot(*cb)
    if denominator <= 1e-9:
        return 0.0
    cosine = max(-1.0, min(1.0, (ab[0] * cb[0] + ab[1] * cb[1]) / denominator))
    return math.degrees(math.acos(cosine))


def _orientation_quality_from_world(world_pose: Any) -> float | None:
    if not world_pose or len(world_pose) < 33:
        return None
    qualities = []
    for left_id, right_id in ((LEFT_SHOULDER, RIGHT_SHOULDER), (LEFT_HIP, RIGHT_HIP)):
        left, right = world_pose[left_id], world_pose[right_id]
        dx = float(right.x) - float(left.x)
        dz = float(right.z) - float(left.z)
        width = math.hypot(dx, dz)
        if width > 1e-6:
            qualities.append(abs(dx) / width)
    return _mean(qualities) if qualities else None


def _transition_context(
    rows: list[dict[str, float]], start_s: float, end_s: float,
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    pre = [
        row for row in rows
        if start_s - MIN_TRANSITION_CONTEXT_SECONDS <= row["timestamp_ms"] / 1000.0 <= start_s
    ]
    post = [
        row for row in rows
        if end_s <= row["timestamp_ms"] / 1000.0 <= end_s + MIN_TRANSITION_CONTEXT_SECONDS
    ]
    return pre, post


def _transition_confirmed(
    rows: list[dict[str, float]], start_s: float, end_s: float,
) -> tuple[bool, str | None]:
    pre, post = _transition_context(rows, start_s, end_s)
    if len(pre) < 2 or len(post) < 2:
        return False, "TRANSITION_CONTEXT_INSUFFICIENT"
    pre_y = [row["pelvis_y_smooth"] for row in pre]
    post_y = [row["pelvis_y_smooth"] for row in post]
    if _range(pre_y) > 0.035:
        return False, "SITTING_NOT_CONFIRMED"
    if _range(post_y) > 0.035:
        return False, "STANDING_NOT_CONFIRMED"
    pre_knee = [_median(pre, side, default=0.0) for side in ("left_knee_angle_deg", "right_knee_angle_deg")]
    post_knee = [_median(post, side, default=0.0) for side in ("left_knee_angle_deg", "right_knee_angle_deg")]
    if all(value > 0 for value in (*pre_knee, *post_knee)):
        if _mean(post_knee) < _mean(pre_knee) + 8.0:
            return False, "KNEE_EXTENSION_NOT_CONFIRMED"
    return True, None


def _reversal_count(values: list[float], deadband: float) -> int:
    if not values:
        return 0
    center = median(values)
    states = []
    for value in values:
        delta = value - center
        state = 1 if delta >= deadband else -1 if delta <= -deadband else 0
        if state and (not states or states[-1] != state):
            states.append(state)
    return max(0, len(states) - 1)


def _ankle_motion_norm(
    rows: list[dict[str, float]], x_key: str, y_key: str, body_scale: float,
) -> float:
    usable = [row for row in rows if x_key in row and y_key in row]
    if len(usable) < 2:
        return 0.0
    initial_count = max(1, min(len(usable), 3))
    initial_x = median([row[x_key] for row in usable[:initial_count]])
    initial_y = median([row[y_key] for row in usable[:initial_count]])
    return max(
        math.hypot(row[x_key] - initial_x, row[y_key] - initial_y) / body_scale
        for row in usable
    )


def _resolve_model_path() -> Path:
    configured = os.getenv(POSE_MODEL_ENV, DEFAULT_POSE_MODEL).strip() or DEFAULT_POSE_MODEL
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    if not path.is_file():
        raise GaitVideoError("pose_model_not_readable")
    return path


def _derive_gait_features(
    rows: list[dict[str, float]], *, total_frames: int, fps: float, duration_s: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not rows:
        raise GaitVideoError("no_pose_detected")

    for field in ("pelvis_x", "pelvis_y", "trunk_angle_deg"):
        smoothed = _smooth([row[field] for row in rows])
        for row, value in zip(rows, smoothed):
            row[f"{field}_smooth"] = value

    elapsed_s = max((rows[-1]["timestamp_ms"] - rows[0]["timestamp_ms"]) / 1000.0, 1e-6)
    distance = sum(
        math.hypot(
            rows[index]["pelvis_x_smooth"] - rows[index - 1]["pelvis_x_smooth"],
            rows[index]["pelvis_y_smooth"] - rows[index - 1]["pelvis_y_smooth"],
        )
        for index in range(1, len(rows))
    )
    left_extent = _mean([row["left_stride_extent"] for row in rows])
    right_extent = _mean([row["right_stride_extent"] for row in rows])
    pelvis_reference = median(
        [row["pelvis_x_smooth"] for row in rows if row["timestamp_ms"] <= 3000]
        or [row["pelvis_x_smooth"] for row in rows]
    )

    rise_candidates: list[dict[str, Any]] = []
    for start_index, start in enumerate(rows):
        for end in rows[start_index + 1 :]:
            window_s = (end["timestamp_ms"] - start["timestamp_ms"]) / 1000.0
            if window_s < 0.4:
                continue
            if window_s > 3.5:
                break
            displacement = start["pelvis_y_smooth"] - end["pelvis_y_smooth"]
            if displacement < 0.05:
                continue
            speed = displacement / window_s
            start_s = start["timestamp_ms"] / 1000.0
            end_s = end["timestamp_ms"] / 1000.0
            confirmed, reason = _transition_confirmed(rows, start_s, end_s)
            rise_candidates.append({
                "duration_s": window_s,
                "speed": speed,
                "displacement": displacement,
                "start_s": start_s,
                "end_s": end_s,
                "confirmed": confirmed,
                "failure_reason": reason,
            })

    confirmed_candidates = [item for item in rise_candidates if item["confirmed"]]
    candidate_pool = confirmed_candidates or rise_candidates
    best_rise = max(
        candidate_pool,
        key=lambda item: (item["speed"], item["displacement"]),
        default=None,
    )

    sway_diagnostics: dict[str, Any]
    sway_values: list[float] = []
    post_rise_rows: list[dict[str, float]] = []
    assessment_status = "NO_TRANSITION"
    assessment_reason = "NO_SIT_TO_STAND_TRANSITION"
    post_rise_metrics: dict[str, float] = {}
    if best_rise is not None:
        window_start_s = best_rise["end_s"]
        window_end_s = window_start_s + POST_RISE_SWAY_WINDOW_SECONDS
        candidate_rows = [
            row
            for row in rows
            if window_start_s <= row["timestamp_ms"] / 1000.0 <= window_end_s
        ]
        post_rise_rows = [
            row
            for row in candidate_rows
            if row["core_visibility_mean"] >= 0.70
        ]
        coverage_tolerance_s = max(0.25, 2.0 / max(fps, 1.0))
        complete = bool(
            len(post_rise_rows) >= MIN_SWAY_WINDOW_SAMPLES
            and rows[-1]["timestamp_ms"] / 1000.0
            >= window_end_s - coverage_tolerance_s
        )
        tracking_ratio = len(post_rise_rows) / max(len(candidate_rows), 1)
        orientation_values = [row.get("orientation_quality", 1.0) for row in post_rise_rows]
        orientation_quality = _mean(orientation_values) if orientation_values else 0.0
        orientation_change = _range(orientation_values)
        if not best_rise["confirmed"]:
            assessment_status = "INDETERMINATE"
            assessment_reason = best_rise["failure_reason"] or "TRANSITION_UNCONFIRMED"
        elif not complete:
            assessment_status = "INDETERMINATE"
            assessment_reason = "POST_RISE_WINDOW_INSUFFICIENT"
        elif tracking_ratio < MIN_POST_RISE_TRACKING_RATIO:
            assessment_status = "INDETERMINATE"
            assessment_reason = "POST_RISE_TRACKING_LOW"
        elif orientation_quality < MIN_ORIENTATION_QUALITY:
            assessment_status = "INDETERMINATE"
            assessment_reason = "CAMERA_ORIENTATION_UNSUITABLE"
        elif orientation_change > MAX_ORIENTATION_CHANGE:
            assessment_status = "INDETERMINATE"
            assessment_reason = "TURNING_DURING_ASSESSMENT"
        else:
            assessment_status = "VALID"
            assessment_reason = "ASSESSABLE_POST_RISE_WINDOW"

        if complete:
            sway_values = [row["trunk_angle_deg"] for row in post_rise_rows]
            body_scale = max(_median(post_rise_rows, "body_scale", default=1.0), 1e-6)
            pelvis_values = [row["pelvis_x_smooth"] for row in post_rise_rows]
            lateral_excursion = (
                _percentile(pelvis_values, 0.95) - _percentile(pelvis_values, 0.05)
            ) / body_scale
            support_values = [row["support_distance"] for row in post_rise_rows]
            support_reference = median(support_values[: max(1, min(3, len(support_values)))])
            support_change = max(abs(value - support_reference) for value in support_values) / body_scale
            left_motion = _ankle_motion_norm(
                post_rise_rows, "left_ankle_x", "left_ankle_y", body_scale,
            )
            right_motion = _ankle_motion_norm(
                post_rise_rows, "right_ankle_x", "right_ankle_y", body_scale,
            )
            compensatory_steps = sum(
                motion >= COMPENSATORY_STEP_MOTION_NORM for motion in (left_motion, right_motion)
            )
            pelvis_path = sum(
                math.hypot(
                    current["pelvis_x_smooth"] - previous["pelvis_x_smooth"],
                    current["pelvis_y_smooth"] - previous["pelvis_y_smooth"],
                )
                for previous, current in zip(post_rise_rows, post_rise_rows[1:])
            ) / body_scale
            pelvis_net = math.hypot(
                post_rise_rows[-1]["pelvis_x_smooth"] - post_rise_rows[0]["pelvis_x_smooth"],
                post_rise_rows[-1]["pelvis_y_smooth"] - post_rise_rows[0]["pelvis_y_smooth"],
            ) / body_scale
            locomotion_detected = bool(
                compensatory_steps >= 1
                and pelvis_path >= LOCOMOTION_PATH_NORM
                and pelvis_net / max(pelvis_path, 1e-6) >= 0.75
            )
            if assessment_status == "VALID" and locomotion_detected:
                assessment_status = "INDETERMINATE"
                assessment_reason = "LOCOMOTION_DURING_ASSESSMENT"
            post_rise_metrics = {
                "post_rise_pelvis_lateral_excursion_norm": lateral_excursion,
                "post_rise_support_width_change_norm": support_change,
                "post_rise_compensatory_step_count": float(compensatory_steps),
                "post_rise_left_ankle_motion_norm": left_motion,
                "post_rise_right_ankle_motion_norm": right_motion,
                "post_rise_pelvis_path_norm": pelvis_path,
                "post_rise_locomotion_detected": float(locomotion_detected),
                "post_rise_orientation_quality": orientation_quality,
                "post_rise_feet_visibility": _median(
                    post_rise_rows, "feet_visibility_mean", default=1.0
                ),
                "post_rise_tracking_ratio": tracking_ratio,
            }
            sway_diagnostics = {
                "trunk_sway_window_type": "POST_RISE",
                "trunk_sway_window_start_s": round(window_start_s, 3),
                "trunk_sway_window_end_s": round(window_end_s, 3),
                "trunk_sway_sample_count": len(sway_values),
                "post_rise_tracking_ratio": round(tracking_ratio, 3),
                "post_rise_orientation_quality": round(orientation_quality, 3),
            }
        else:
            sway_diagnostics = {
                "trunk_sway_window_type": "POST_RISE_WINDOW_INSUFFICIENT",
                "trunk_sway_window_start_s": round(window_start_s, 3),
                "trunk_sway_window_end_s": round(window_end_s, 3),
                "trunk_sway_sample_count": len(post_rise_rows),
                "trunk_sway_failure_reason": "POST_RISE_WINDOW_INSUFFICIENT",
            }
    else:
        sway_values = [
            row["trunk_angle_deg"]
            for row in rows
            if row["core_visibility_mean"] >= 0.70
        ]
        sway_diagnostics = {
            "trunk_sway_window_type": "FULL_CLIP_FALLBACK",
            "trunk_sway_window_start_s": round(rows[0]["timestamp_ms"] / 1000.0, 3),
            "trunk_sway_window_end_s": round(rows[-1]["timestamp_ms"] / 1000.0, 3),
            "trunk_sway_sample_count": len(sway_values),
        }

    sway_amplitude = None
    if len(sway_values) >= MIN_SWAY_WINDOW_SAMPLES:
        sway_p5 = _percentile(sway_values, 0.05)
        sway_p95 = _percentile(sway_values, 0.95)
        sway_amplitude = sway_p95 - sway_p5
        sway_diagnostics.update(
            {
                "trunk_sway_p5_deg": round(sway_p5, 3),
                "trunk_sway_p95_deg": round(sway_p95, 3),
            }
        )
        post_rise_metrics["post_rise_sway_reversal_count"] = float(
            _reversal_count(sway_values, deadband=2.0)
        )

    angular_velocities = []
    for previous, current in zip(rows, rows[1:]):
        delta_s = (current["timestamp_ms"] - previous["timestamp_ms"]) / 1000.0
        if delta_s > 0:
            angular_velocities.append(
                abs(current["trunk_angle_deg_smooth"] - previous["trunk_angle_deg_smooth"]) / delta_s
            )

    best_stable: list[dict[str, float]] = []
    current_stable: list[dict[str, float]] = []
    for row in rows:
        if abs(row["trunk_angle_deg_smooth"]) <= 8.0 and row["core_visibility_mean"] >= 0.70:
            current_stable.append(row)
            if len(current_stable) > len(best_stable):
                best_stable = list(current_stable)
        else:
            current_stable = []
    stable_duration = (
        (best_stable[-1]["timestamp_ms"] - best_stable[0]["timestamp_ms"]) / 1000.0
        if len(best_stable) >= 2 else 0.0
    )

    features = {
        "com_offset_norm": max(abs(row["pelvis_x_smooth"] - pelvis_reference) for row in rows),
        "step_speed_norm_s": distance / elapsed_s,
        "step_asymmetry_ratio": abs(left_extent - right_extent) / max(left_extent, right_extent, 1e-6),
        "turn_angular_velocity_deg_s": max(angular_velocities, default=0.0),
        "support_distance_norm": _mean([row["support_distance"] for row in rows]),
        "stable_posture_duration": stable_duration,
        "stable_trunk_angle_deg": max(
            (abs(row["trunk_angle_deg_smooth"]) for row in best_stable), default=0.0
        ),
        "valid_frame_ratio": len(rows) / max(total_frames, 1),
        "assessment_status": assessment_status,
        "assessment_reason_code": assessment_reason,
        **post_rise_metrics,
    }
    if sway_amplitude is not None:
        features["trunk_sway_angle_deg"] = sway_amplitude
    if best_rise is not None:
        features["sit_to_stand_transition_confirmed"] = bool(best_rise["confirmed"])
        features["rise_duration_s"] = best_rise["duration_s"]
        features["hip_vertical_speed_norm_s"] = best_rise["speed"]

    rounded = {
        key: round(float(value), 3) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
        for key, value in features.items()
    }
    diagnostics = {
        "feature_source_type": "video",
        "video_format": "local_file",
        "fps": round(fps, 3),
        "duration_s": round(duration_s, 3),
        "frames_processed": total_frames,
        "pose_frames": len(rows),
        "pose_model": "mediapipe_pose_landmarker_heavy",
        "rise_window_start_s": round(best_rise["start_s"], 3) if best_rise is not None else None,
        "rise_window_end_s": round(best_rise["end_s"], 3) if best_rise is not None else None,
        "sit_to_stand_transition_confirmed": bool(best_rise and best_rise["confirmed"]),
        "assessment_status": assessment_status,
        "assessment_reason_code": assessment_reason,
        **sway_diagnostics,
    }
    return rounded, diagnostics


def _extract_pose_video_analysis(video_path: Path) -> PoseVideoAnalysis:
    """Run MediaPipe once and retain only an ephemeral normalized pose series."""
    if video_path.suffix.lower() not in VIDEO_SUFFIXES:
        raise GaitVideoError("unsupported_video_format")
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
    except ImportError as exc:
        raise GaitVideoError("pose_runtime_unavailable") from exc

    model_path = _resolve_model_path()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise GaitVideoError("video_not_readable")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not math.isfinite(fps) or fps <= 0:
        capture.release()
        raise GaitVideoError("video_fps_invalid")
    declared_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    try:
        options = vision.PoseLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_buffer=model_path.read_bytes()),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        detector = vision.PoseLandmarker.create_from_options(options)
    except Exception as exc:
        capture.release()
        raise GaitVideoError("pose_runtime_initialization_failed") from exc
    rows: list[dict[str, float]] = []
    luminance_values: list[float] = []
    frame_index = 0
    last_timestamp = -1
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            captured_ms = capture.get(cv2.CAP_PROP_POS_MSEC)
            fallback_ms = frame_index * 1000.0 / fps
            timestamp_ms = int(round(captured_ms if captured_ms > last_timestamp else fallback_ms))
            timestamp_ms = max(timestamp_ms, last_timestamp + 1)
            last_timestamp = timestamp_ms
            luminance_values.append(float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean()) / 255.0)
            result = detector.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
                timestamp_ms,
            )
            if result.pose_landmarks and len(result.pose_landmarks[0]) >= 33:
                pose = result.pose_landmarks[0]
                left_shoulder, right_shoulder = pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]
                left_hip, right_hip = pose[LEFT_HIP], pose[RIGHT_HIP]
                left_knee, right_knee = pose[LEFT_KNEE], pose[RIGHT_KNEE]
                left_ankle, right_ankle = pose[LEFT_ANKLE], pose[RIGHT_ANKLE]
                pelvis_x = (left_hip.x + right_hip.x) / 2
                pelvis_y = (left_hip.y + right_hip.y) / 2
                shoulder_x = (left_shoulder.x + right_shoulder.x) / 2
                shoulder_y = (left_shoulder.y + right_shoulder.y) / 2
                visibility = [float(getattr(pose[index], "visibility", 0.0)) for index in CORE_IDS]
                torso_visibility = [
                    float(getattr(pose[index], "visibility", 0.0))
                    for index in (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)
                ]
                feet_visibility = [
                    float(getattr(pose[index], "visibility", 0.0))
                    for index in (LEFT_ANKLE, RIGHT_ANKLE)
                ]
                body_scale = max(math.hypot(shoulder_x - pelvis_x, shoulder_y - pelvis_y), 1e-6)
                shoulder_width = math.hypot(
                    float(right_shoulder.x) - float(left_shoulder.x),
                    float(right_shoulder.y) - float(left_shoulder.y),
                )
                hip_width = math.hypot(
                    float(right_hip.x) - float(left_hip.x),
                    float(right_hip.y) - float(left_hip.y),
                )
                projected_orientation_quality = min(
                    1.0, ((shoulder_width + hip_width) / 2.0) / max(body_scale * 0.65, 1e-6)
                )
                world_pose = (
                    result.pose_world_landmarks[0]
                    if getattr(result, "pose_world_landmarks", None)
                    else None
                )
                world_orientation_quality = _orientation_quality_from_world(world_pose)
                rows.append({
                    "timestamp_ms": float(timestamp_ms),
                    "pelvis_x": float(pelvis_x),
                    "pelvis_y": float(pelvis_y),
                    "trunk_angle_deg": math.degrees(math.atan2(shoulder_x - pelvis_x, -(shoulder_y - pelvis_y))),
                    "body_scale": body_scale,
                    "orientation_quality": (
                        projected_orientation_quality
                        if world_orientation_quality is None
                        else min(projected_orientation_quality, world_orientation_quality)
                    ),
                    "left_knee_angle_deg": _joint_angle(left_hip, left_knee, left_ankle),
                    "right_knee_angle_deg": _joint_angle(right_hip, right_knee, right_ankle),
                    "left_ankle_x": float(left_ankle.x),
                    "left_ankle_y": float(left_ankle.y),
                    "right_ankle_x": float(right_ankle.x),
                    "right_ankle_y": float(right_ankle.y),
                    "left_stride_extent": abs(float(left_ankle.x) - pelvis_x),
                    "right_stride_extent": abs(float(right_ankle.x) - pelvis_x),
                    "support_distance": abs(float(left_ankle.x) - float(right_ankle.x)),
                    "core_visibility_mean": _mean(visibility),
                    "torso_visibility_mean": _mean(torso_visibility),
                    "feet_visibility_mean": _mean(feet_visibility),
                })
            frame_index += 1
    except Exception as exc:
        raise GaitVideoError("pose_inference_failed") from exc
    finally:
        try:
            detector.close()
        except Exception:
            pass
        capture.release()

    if frame_index == 0:
        raise GaitVideoError("video_contains_no_frames")
    duration_s = last_timestamp / 1000.0 if last_timestamp >= 0 else frame_index / fps
    features, diagnostics = _derive_gait_features(
        rows, total_frames=max(frame_index, declared_frames), fps=fps, duration_s=duration_s,
    )
    points = tuple(
        (
            round(float(row["timestamp_ms"]) / 1000.0, 3),
            round(float(row.get("pelvis_x_smooth", row["pelvis_x"])), 6),
            round(float(row.get("pelvis_y_smooth", row["pelvis_y"])), 6),
            round(float(row["core_visibility_mean"]), 4),
        )
        for row in rows
    )
    return PoseVideoAnalysis(
        features=features,
        diagnostics=diagnostics,
        trajectory_points=points,
        illumination_norm=round(float(median(luminance_values)), 4) if luminance_values else 0.0,
    )


@lru_cache(maxsize=4)
def _cached_pose_video_analysis(
    resolved_path: str, byte_size: int, modified_ns: int,
) -> PoseVideoAnalysis:
    del byte_size, modified_ns
    return _extract_pose_video_analysis(Path(resolved_path))


def extract_pose_video_analysis(video_path: Path) -> PoseVideoAnalysis:
    if video_path.suffix.lower() not in VIDEO_SUFFIXES:
        raise GaitVideoError("unsupported_video_format")
    try:
        stat = video_path.stat()
    except OSError as exc:
        raise GaitVideoError("video_not_readable") from exc
    return _cached_pose_video_analysis(str(video_path.resolve()), stat.st_size, stat.st_mtime_ns)


def extract_gait_features(video_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return sanitized gait features from the shared ephemeral pose analysis."""
    analysis = extract_pose_video_analysis(video_path)
    return dict(analysis.features), dict(analysis.diagnostics)


def _active_gait_metrics(
    rows: list[dict[str, float]], *, speed_threshold: float = 0.08,
) -> dict[str, float]:
    """Measure gait only while the person is moving, excluding static clip time."""
    active_indices: set[int] = set()
    normalized_distances: list[tuple[float, float]] = []
    for index, (previous, current) in enumerate(zip(rows, rows[1:]), start=1):
        delta_s = (current["timestamp_ms"] - previous["timestamp_ms"]) / 1000.0
        if not 0 < delta_s <= 0.5:
            continue
        scale = max((previous.get("body_scale", 1.0) + current.get("body_scale", 1.0)) / 2.0, 1e-6)
        pelvis_distance = math.hypot(
            current["pelvis_x_smooth"] - previous["pelvis_x_smooth"],
            current["pelvis_y_smooth"] - previous["pelvis_y_smooth"],
        ) / scale
        ankle_speed = 0.0
        if all(
            key in previous and key in current
            for key in ("left_ankle_x", "right_ankle_x")
        ):
            ankle_speed = max(
                abs(
                    (current[key] - current["pelvis_x_smooth"])
                    - (previous[key] - previous["pelvis_x_smooth"])
                ) / scale / delta_s
                for key in ("left_ankle_x", "right_ankle_x")
            )
        if pelvis_distance / delta_s >= speed_threshold or ankle_speed >= 0.12:
            active_indices.update((index - 1, index))
            normalized_distances.append((pelvis_distance, delta_s))

    active_rows = [row for index, row in enumerate(rows) if index in active_indices]
    active_seconds = sum(delta_s for _, delta_s in normalized_distances)
    speed = (
        sum(distance for distance, _ in normalized_distances) / active_seconds
        if active_seconds > 0 else 0.0
    )
    left = [row["left_stride_extent"] for row in active_rows if "left_stride_extent" in row]
    right = [row["right_stride_extent"] for row in active_rows if "right_stride_extent" in row]
    left_extent = median(left) if left else 0.0
    right_extent = median(right) if right else 0.0
    asymmetry = abs(left_extent - right_extent) / max(left_extent, right_extent, 1e-6)
    return {
        "step_speed_norm_s": speed,
        "step_asymmetry_ratio": asymmetry,
        "locomotion_frame_ratio": len(active_rows) / max(len(rows), 1),
        "locomotion_duration_s": active_seconds,
    }


def _turning_points(values: list[float], deadband: float) -> list[float]:
    """Return alternating extrema after suppressing pose jitter."""
    if len(values) < 3:
        return []
    smoothed = _smooth(values, radius=2)
    points: list[float] = []
    direction = 0
    candidate = smoothed[0]
    for previous, current in zip(smoothed, smoothed[1:]):
        delta = current - previous
        next_direction = 1 if delta > deadband else -1 if delta < -deadband else direction
        if direction and next_direction and next_direction != direction:
            points.append(candidate)
            candidate = current
        elif next_direction > 0:
            candidate = max(candidate, current)
        elif next_direction < 0:
            candidate = min(candidate, current)
        direction = next_direction
    if direction:
        points.append(candidate)
    return points


def _stride_amplitudes(points: list[float], minimum: float = 0.08) -> list[float]:
    return [
        abs(current - previous)
        for previous, current in zip(points, points[1:])
        if abs(current - previous) >= minimum
    ]


def _gait_cycle_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    """Estimate bilateral gait cycles in the pelvis-relative image axis.

    This is an engineering proxy for a fixed camera. It requires alternating
    ankle excursions and reports insufficiency instead of averaging static
    frames or claiming asymmetry from one partial step.
    """
    usable = [
        row for row in rows
        if all(key in row for key in (
            "left_ankle_x", "right_ankle_x", "pelvis_x_smooth", "body_scale",
        ))
    ]
    if len(usable) < 8:
        return {
            "gait_cycle_count": 0.0,
            "stride_length_asymmetry_ratio": 0.0,
            "gait_cycle_assessment_valid": 0.0,
        }
    left = [
        (row["left_ankle_x"] - row["pelvis_x_smooth"]) / max(row["body_scale"], 1e-6)
        for row in usable
    ]
    right = [
        (row["right_ankle_x"] - row["pelvis_x_smooth"]) / max(row["body_scale"], 1e-6)
        for row in usable
    ]
    left_amplitudes = _stride_amplitudes(_turning_points(left, deadband=0.006))
    right_amplitudes = _stride_amplitudes(_turning_points(right, deadband=0.006))
    complete_cycles = min(len(left_amplitudes), len(right_amplitudes)) // 2
    if not left_amplitudes or not right_amplitudes:
        asymmetry = 0.0
    else:
        left_extent = median(left_amplitudes)
        right_extent = median(right_amplitudes)
        asymmetry = abs(left_extent - right_extent) / max(left_extent, right_extent, 1e-6)
    return {
        "gait_cycle_count": float(complete_cycles),
        "left_stride_excursion_norm": median(left_amplitudes) if left_amplitudes else 0.0,
        "right_stride_excursion_norm": median(right_amplitudes) if right_amplitudes else 0.0,
        "stride_length_asymmetry_ratio": asymmetry,
        "gait_cycle_assessment_valid": float(complete_cycles >= 2),
    }


def _derive_gait_features_v14(
    rows: list[dict[str, float]], *, total_frames: int, fps: float,
    duration_s: float, illumination_norm: float, multi_person_frames: int,
    multi_person_max_frames: int, occlusion_max_frames: int,
    include_cycle_metrics: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    features, diagnostics = _derive_gait_features(
        rows, total_frames=total_frames, fps=fps, duration_s=duration_s,
    )
    legacy_full_clip_metrics = {
        "step_speed_norm_s": features.get("step_speed_norm_s"),
        "step_asymmetry_ratio": features.get("step_asymmetry_ratio"),
    }
    gait = _active_gait_metrics(rows)
    feet_values = [row.get("feet_visibility_mean", 0.0) for row in rows]
    core_values = [row.get("core_visibility_mean", 0.0) for row in rows]
    features.update(gait)
    if include_cycle_metrics:
        cycle_metrics = _gait_cycle_metrics(rows)
        features.update(cycle_metrics)
        if cycle_metrics["gait_cycle_assessment_valid"]:
            features["step_asymmetry_ratio"] = cycle_metrics["stride_length_asymmetry_ratio"]
    features.update({
        "illumination_norm": illumination_norm,
        "multi_person_frame_ratio": multi_person_frames / max(total_frames, 1),
        "multi_person_max_consecutive_s": multi_person_max_frames / max(fps, 1.0),
        "feet_visibility_mean": _mean(feet_values),
        "feet_low_visibility_ratio": sum(value < 0.65 for value in feet_values) / max(len(feet_values), 1),
        "core_low_visibility_ratio": sum(value < 0.70 for value in core_values) / max(total_frames, 1),
        "core_low_visibility_max_consecutive_s": occlusion_max_frames / max(fps, 1.0),
    })
    quality_reasons: list[str] = []
    if (
        float(features.get("valid_frame_ratio", 0.0)) < 0.70
        or features["core_low_visibility_max_consecutive_s"] >= 1.50
    ):
        quality_reasons.append("HUMAN_TRACKING_OR_OCCLUSION")
    if features["feet_visibility_mean"] < 0.65:
        quality_reasons.append("FEET_OUT_OF_FRAME")
    if illumination_norm < 0.18:
        quality_reasons.append("LOW_ILLUMINATION")
    if features["multi_person_max_consecutive_s"] >= 0.50:
        quality_reasons.append("MULTIPLE_PEOPLE")
    if quality_reasons:
        features["pre_quality_assessment_status"] = features.get("assessment_status", "NO_TRANSITION")
        features["pre_quality_assessment_reason_code"] = features.get("assessment_reason_code", "NO_SIT_TO_STAND_TRANSITION")
        features["assessment_status"] = "INDETERMINATE"
        features["assessment_reason_code"] = quality_reasons[0]
    elif (
        features.get("assessment_status") == "INDETERMINATE"
        and gait["locomotion_duration_s"] >= 0.5
    ):
        features["pre_quality_assessment_status"] = features["assessment_status"]
        features["pre_quality_assessment_reason_code"] = features.get(
            "assessment_reason_code", "POST_RISE_ASSESSMENT_INDETERMINATE"
        )
        features["assessment_status"] = "GAIT_ONLY"
        features["assessment_reason_code"] = "POST_RISE_UNUSABLE_GAIT_WINDOW_VALID"
        features["sit_to_stand_transition_confirmed"] = False
    diagnostics.update({
        "gait_window_type": "ACTIVE_LOCOMOTION",
        "locomotion_duration_s": round(gait["locomotion_duration_s"], 3),
        "multi_person_frames": multi_person_frames,
        "multi_person_max_consecutive_s": round(features["multi_person_max_consecutive_s"], 3),
        "core_low_visibility_max_consecutive_s": round(
            features["core_low_visibility_max_consecutive_s"], 3
        ),
        "quality_gate_reasons": quality_reasons,
        "quality_gate_status": "FAILED" if quality_reasons else "PASS",
        "legacy_full_clip_metrics": legacy_full_clip_metrics,
    })
    rounded = {
        key: round(float(value), 3)
        if isinstance(value, (int, float)) and not isinstance(value, bool) else value
        for key, value in features.items()
    }
    return rounded, diagnostics


def _extract_pose_video_analysis_v14(
    video_path: Path, *, include_cycle_metrics: bool = False,
) -> PoseVideoAnalysis:
    """v1.4 extraction with active gait windows and multi-person quality gates."""
    if video_path.suffix.lower() not in VIDEO_SUFFIXES:
        raise GaitVideoError("unsupported_video_format")
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
    except ImportError as exc:
        raise GaitVideoError("pose_runtime_unavailable") from exc

    model_path = _resolve_model_path()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise GaitVideoError("video_not_readable")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not math.isfinite(fps) or fps <= 0:
        capture.release()
        raise GaitVideoError("video_fps_invalid")
    declared_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    try:
        options = vision.PoseLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_buffer=model_path.read_bytes()),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=2,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        detector = vision.PoseLandmarker.create_from_options(options)
    except Exception as exc:
        capture.release()
        raise GaitVideoError("pose_runtime_initialization_failed") from exc

    rows: list[dict[str, float]] = []
    luminance_values: list[float] = []
    frame_index = 0
    last_timestamp = -1
    multi_person_frames = 0
    multi_person_run = 0
    multi_person_max_frames = 0
    missing_pose_run = 0
    low_core_visibility_run = 0
    occlusion_max_frames = 0
    seen_pose = False
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            captured_ms = capture.get(cv2.CAP_PROP_POS_MSEC)
            fallback_ms = frame_index * 1000.0 / fps
            timestamp_ms = int(round(captured_ms if captured_ms > last_timestamp else fallback_ms))
            timestamp_ms = max(timestamp_ms, last_timestamp + 1)
            last_timestamp = timestamp_ms
            luminance_values.append(float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean()) / 255.0)
            result = detector.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
                timestamp_ms,
            )
            poses = [pose for pose in (result.pose_landmarks or []) if len(pose) >= 33]
            if len(poses) >= 2:
                multi_person_frames += 1
                multi_person_run += 1
                multi_person_max_frames = max(multi_person_max_frames, multi_person_run)
            else:
                multi_person_run = 0
            if not poses:
                if seen_pose:
                    missing_pose_run += 1
                frame_index += 1
                continue
            if missing_pose_run:
                occlusion_max_frames = max(occlusion_max_frames, missing_pose_run)
                missing_pose_run = 0
            seen_pose = True
            pose_index, pose = max(
                enumerate(poses),
                key=lambda item: _mean([
                    float(getattr(item[1][index], "visibility", 0.0)) for index in CORE_IDS
                ]),
            )
            left_shoulder, right_shoulder = pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]
            left_hip, right_hip = pose[LEFT_HIP], pose[RIGHT_HIP]
            left_knee, right_knee = pose[LEFT_KNEE], pose[RIGHT_KNEE]
            left_ankle, right_ankle = pose[LEFT_ANKLE], pose[RIGHT_ANKLE]
            pelvis_x = (left_hip.x + right_hip.x) / 2
            pelvis_y = (left_hip.y + right_hip.y) / 2
            shoulder_x = (left_shoulder.x + right_shoulder.x) / 2
            shoulder_y = (left_shoulder.y + right_shoulder.y) / 2
            visibility = [float(getattr(pose[index], "visibility", 0.0)) for index in CORE_IDS]
            if _mean(visibility) < 0.70:
                low_core_visibility_run += 1
                occlusion_max_frames = max(
                    occlusion_max_frames, low_core_visibility_run
                )
            else:
                low_core_visibility_run = 0
            torso_visibility = [
                float(getattr(pose[index], "visibility", 0.0))
                for index in (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)
            ]
            feet_visibility = [
                1.0
                if (
                    0.0 <= float(pose[index].x) <= 1.0
                    and 0.0 <= float(pose[index].y) <= 1.0
                    and float(getattr(pose[index], "visibility", 0.0)) >= 0.30
                )
                else 0.0
                for index in (LEFT_ANKLE, RIGHT_ANKLE)
            ]
            body_scale = max(math.hypot(shoulder_x - pelvis_x, shoulder_y - pelvis_y), 1e-6)
            shoulder_width = math.hypot(right_shoulder.x - left_shoulder.x, right_shoulder.y - left_shoulder.y)
            hip_width = math.hypot(right_hip.x - left_hip.x, right_hip.y - left_hip.y)
            projected_orientation_quality = min(
                1.0, ((shoulder_width + hip_width) / 2.0) / max(body_scale * 0.65, 1e-6)
            )
            world_poses = getattr(result, "pose_world_landmarks", None) or []
            world_pose = world_poses[pose_index] if pose_index < len(world_poses) else None
            world_orientation_quality = _orientation_quality_from_world(world_pose)
            rows.append({
                "timestamp_ms": float(timestamp_ms),
                "pelvis_x": float(pelvis_x), "pelvis_y": float(pelvis_y),
                "trunk_angle_deg": math.degrees(math.atan2(shoulder_x - pelvis_x, -(shoulder_y - pelvis_y))),
                "body_scale": body_scale,
                "orientation_quality": projected_orientation_quality if world_orientation_quality is None else min(projected_orientation_quality, world_orientation_quality),
                "left_knee_angle_deg": _joint_angle(left_hip, left_knee, left_ankle),
                "right_knee_angle_deg": _joint_angle(right_hip, right_knee, right_ankle),
                "left_ankle_x": float(left_ankle.x), "left_ankle_y": float(left_ankle.y),
                "right_ankle_x": float(right_ankle.x), "right_ankle_y": float(right_ankle.y),
                "left_stride_extent": abs(float(left_ankle.x) - pelvis_x),
                "right_stride_extent": abs(float(right_ankle.x) - pelvis_x),
                "support_distance": abs(float(left_ankle.x) - float(right_ankle.x)),
                "core_visibility_mean": _mean(visibility),
                "torso_visibility_mean": _mean(torso_visibility),
                "feet_visibility_mean": _mean(feet_visibility),
            })
            frame_index += 1
    except Exception as exc:
        raise GaitVideoError("pose_inference_failed") from exc
    finally:
        try:
            detector.close()
        except Exception:
            pass
        capture.release()
    if frame_index == 0:
        raise GaitVideoError("video_contains_no_frames")
    if not rows:
        raise GaitVideoError("no_pose_detected")
    duration_s = last_timestamp / 1000.0 if last_timestamp >= 0 else frame_index / fps
    illumination = float(median(luminance_values)) if luminance_values else 0.0
    total_frames = max(frame_index, declared_frames)
    features, diagnostics = _derive_gait_features_v14(
        rows, total_frames=total_frames, fps=fps, duration_s=duration_s,
        illumination_norm=illumination, multi_person_frames=multi_person_frames,
        multi_person_max_frames=multi_person_max_frames,
        occlusion_max_frames=occlusion_max_frames,
        include_cycle_metrics=include_cycle_metrics,
    )
    points = tuple(
        (
            round(float(row["timestamp_ms"]) / 1000.0, 3),
            round(float(row.get("pelvis_x_smooth", row["pelvis_x"])), 6),
            round(float(row.get("pelvis_y_smooth", row["pelvis_y"])), 6),
            round(float(row["core_visibility_mean"]), 4),
        )
        for row in rows
    )
    return PoseVideoAnalysis(
        features=features,
        diagnostics=diagnostics,
        trajectory_points=points,
        illumination_norm=round(illumination, 4),
    )


@lru_cache(maxsize=4)
def _cached_pose_video_analysis_v14(
    resolved_path: str, byte_size: int, modified_ns: int,
) -> PoseVideoAnalysis:
    del byte_size, modified_ns
    return _extract_pose_video_analysis_v14(Path(resolved_path))


def extract_pose_video_analysis_v14(video_path: Path) -> PoseVideoAnalysis:
    stat = video_path.stat()
    return _cached_pose_video_analysis_v14(
        str(video_path.resolve()), stat.st_size, stat.st_mtime_ns,
    )


def extract_gait_features_v14(video_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    analysis = extract_pose_video_analysis_v14(video_path)
    return dict(analysis.features), dict(analysis.diagnostics)


def extract_gait_features_v15(video_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return v1.5 exploratory features without changing v1.4 output."""
    analysis = _extract_pose_video_analysis_v14(
        video_path.resolve(), include_cycle_metrics=True,
    )
    roi_features = _person_roi_quality_v15(video_path, analysis.trajectory_points)
    features = {**analysis.features, **roi_features}
    quality_reasons = list(analysis.diagnostics.get("quality_gate_reasons", []))
    if (
        roi_features["person_roi_illumination_median"] < 0.18
        or roi_features["person_roi_illumination_p10"] < 0.08
    ) and "LOW_ILLUMINATION" not in quality_reasons:
        quality_reasons.append("LOW_ILLUMINATION")
    if (
        roi_features["pose_freeze_visual_change_max_consecutive_s"] >= 0.5
        and "HUMAN_TRACKING_OR_OCCLUSION" not in quality_reasons
    ):
        quality_reasons.append("HUMAN_TRACKING_OR_OCCLUSION")
    if quality_reasons:
        features["pre_quality_assessment_status"] = features.get("assessment_status", "NO_TRANSITION")
        features["pre_quality_assessment_reason_code"] = features.get(
            "assessment_reason_code", "NO_SIT_TO_STAND_TRANSITION"
        )
        features["assessment_status"] = "INDETERMINATE"
        features["assessment_reason_code"] = quality_reasons[0]
    return features, {
        **analysis.diagnostics,
        "v15_cycle_metrics_available": True,
        "quality_gate_reasons": quality_reasons,
        "quality_gate_status": "FAILED" if quality_reasons else "PASS",
        "quality_proxy_version": "PERSON_ROI_V15",
    }


def _person_roi_quality_v15(
    video_path: Path, points: tuple[tuple[float, float, float, float], ...],
) -> dict[str, float]:
    """Measure luminance around the tracked person and flag pose freezing.

    The crop intentionally uses only ephemeral pelvis coordinates. No frames or
    identity-bearing crops are retained.
    """
    try:
        import cv2
    except ImportError as exc:
        raise GaitVideoError("pose_runtime_unavailable") from exc
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise GaitVideoError("video_not_readable")
    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 1.0
    medians: list[float] = []
    p10_values: list[float] = []
    contrasts: list[float] = []
    freeze_run = freeze_max = 0
    previous_gray = None
    previous_point = None
    frame_index = 0
    point_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            current_s = frame_index / max(fps, 1.0)
            while point_index + 1 < len(points) and points[point_index + 1][0] <= current_s:
                point_index += 1
            if not points or abs(points[point_index][0] - current_s) > 0.25:
                frame_index += 1
                continue
            _, pelvis_x, pelvis_y, _ = points[point_index]
            height, width = frame.shape[:2]
            x0, x1 = max(0, int((pelvis_x - 0.22) * width)), min(width, int((pelvis_x + 0.22) * width))
            y0, y1 = max(0, int((pelvis_y - 0.42) * height)), min(height, int((pelvis_y + 0.48) * height))
            roi = frame[y0:y1, x0:x1]
            if roi.size:
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                medians.append(float(cv2.mean(gray)[0]) / 255.0)
                import numpy as np
                p10_values.append(float(np.percentile(gray, 10)) / 255.0)
                contrasts.append(float(np.percentile(gray, 90) - np.percentile(gray, 10)) / 255.0)
                if previous_gray is not None and previous_point is not None and previous_gray.shape == gray.shape:
                    pose_delta = math.hypot(pelvis_x - previous_point[0], pelvis_y - previous_point[1])
                    visual_delta = float(np.mean(cv2.absdiff(gray, previous_gray))) / 255.0
                    if pose_delta < 0.0008 and visual_delta > 0.025:
                        freeze_run += 1
                        freeze_max = max(freeze_max, freeze_run)
                    else:
                        freeze_run = 0
                previous_gray = gray
                previous_point = (pelvis_x, pelvis_y)
            frame_index += 1
    finally:
        capture.release()
    return {
        "person_roi_illumination_median": round(float(median(medians)), 4) if medians else 0.0,
        "person_roi_illumination_p10": round(float(median(p10_values)), 4) if p10_values else 0.0,
        "person_roi_contrast": round(float(median(contrasts)), 4) if contrasts else 0.0,
        "pose_freeze_visual_change_max_consecutive_s": round(freeze_max / max(fps, 1.0), 3),
    }
