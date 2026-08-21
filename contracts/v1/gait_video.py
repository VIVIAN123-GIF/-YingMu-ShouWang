"""Extract frozen gait features from one local video without persisting frames."""

from __future__ import annotations

import math
import os
from pathlib import Path
from statistics import mean, median
from typing import Any


POSE_MODEL_ENV = "YINGMU_GAIT_POSE_MODEL"
DEFAULT_POSE_MODEL = "models/pose_landmarker_heavy.task"
VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".webm"}

LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_ANKLE, RIGHT_ANKLE = 27, 28
CORE_IDS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP, LEFT_ANKLE, RIGHT_ANKLE)


class GaitVideoError(ValueError):
    """A sanitized video-extraction failure safe to return in diagnostics."""


def _mean(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _smooth(values: list[float], radius: int = 2) -> list[float]:
    return [
        _mean(values[max(0, index - radius) : min(len(values), index + radius + 1)])
        for index in range(len(values))
    ]


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
) -> tuple[dict[str, float], dict[str, Any]]:
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
    opening = [row["trunk_angle_deg_smooth"] for row in rows if row["timestamp_ms"] <= 3000]
    trunk_reference = median(opening or [row["trunk_angle_deg_smooth"] for row in rows])
    pelvis_reference = median(
        [row["pelvis_x_smooth"] for row in rows if row["timestamp_ms"] <= 3000]
        or [row["pelvis_x_smooth"] for row in rows]
    )

    best_rise: tuple[float, float] | None = None
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
            if best_rise is None or speed > best_rise[1]:
                best_rise = (window_s, speed)

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
        "trunk_sway_angle_deg": max(
            abs(row["trunk_angle_deg_smooth"] - trunk_reference) for row in rows
        ),
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
    }
    if best_rise is not None:
        features["rise_duration_s"] = best_rise[0]
        features["hip_vertical_speed_norm_s"] = best_rise[1]

    rounded = {key: round(float(value), 3) for key, value in features.items()}
    diagnostics = {
        "feature_source_type": "video",
        "video_format": "local_file",
        "fps": round(fps, 3),
        "duration_s": round(duration_s, 3),
        "frames_processed": total_frames,
        "pose_frames": len(rows),
        "pose_model": "mediapipe_pose_landmarker_heavy",
    }
    return rounded, diagnostics


def extract_gait_features(video_path: Path) -> tuple[dict[str, float], dict[str, Any]]:
    """Run MediaPipe Pose on a local video and return only sanitized features."""
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
            result = detector.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
                timestamp_ms,
            )
            if result.pose_landmarks and len(result.pose_landmarks[0]) >= 33:
                pose = result.pose_landmarks[0]
                left_shoulder, right_shoulder = pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]
                left_hip, right_hip = pose[LEFT_HIP], pose[RIGHT_HIP]
                left_ankle, right_ankle = pose[LEFT_ANKLE], pose[RIGHT_ANKLE]
                pelvis_x = (left_hip.x + right_hip.x) / 2
                pelvis_y = (left_hip.y + right_hip.y) / 2
                shoulder_x = (left_shoulder.x + right_shoulder.x) / 2
                shoulder_y = (left_shoulder.y + right_shoulder.y) / 2
                visibility = [float(getattr(pose[index], "visibility", 0.0)) for index in CORE_IDS]
                rows.append({
                    "timestamp_ms": float(timestamp_ms),
                    "pelvis_x": float(pelvis_x),
                    "pelvis_y": float(pelvis_y),
                    "trunk_angle_deg": math.degrees(math.atan2(shoulder_x - pelvis_x, -(shoulder_y - pelvis_y))),
                    "left_stride_extent": abs(float(left_ankle.x) - pelvis_x),
                    "right_stride_extent": abs(float(right_ankle.x) - pelvis_x),
                    "support_distance": abs(float(left_ankle.x) - float(right_ankle.x)),
                    "core_visibility_mean": _mean(visibility),
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
    return _derive_gait_features(
        rows, total_frames=max(frame_index, declared_frames), fps=fps, duration_s=duration_s,
    )
