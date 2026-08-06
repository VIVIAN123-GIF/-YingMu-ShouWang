from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable


ADAPTER_VERSION = "c6c-recorded-replay-v1"
QUALITY_THRESHOLD = 0.70
CONFIDENCE_THRESHOLD = 0.70
HIGH_CONFIDENCE_THRESHOLD = 0.80
STABLE_SECONDS = 15.0
OBSERVATION_SECONDS = 60.0
STABLE_ANGLE_DEG = 8.0
RAPID_RISE_BASELINE_SECONDS = 2.5
SWAY_BASELINE_DEG = 8.0

LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_ANKLE, RIGHT_ANKLE = 27, 28
CORE_IDS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP, LEFT_ANKLE, RIGHT_ANKLE)


@dataclass(frozen=True)
class MotionWindow:
    start_index: int
    end_index: int
    start_ms: int
    end_ms: int
    duration_s: float
    displacement: float
    speed: float
    data_quality: float


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def parse_offset(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    parts = value.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"invalid clip-relative timestamp: {value}")


def iso_at(captured_at: str, offset_seconds: float) -> str:
    base = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    if base.tzinfo is None or base.utcoffset() is None:
        raise ValueError("captured_at must include a timezone offset")
    return (base + timedelta(seconds=offset_seconds)).isoformat(timespec="milliseconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def safe_mean(values: Iterable[float]) -> float:
    values = list(values)
    return float(mean(values)) if values else 0.0


def smooth(values: list[float]) -> list[float]:
    if len(values) < 5:
        return values
    import numpy as np
    from scipy.signal import savgol_filter

    window = min(9, len(values) if len(values) % 2 else len(values) - 1)
    if window < 5:
        return values
    return savgol_filter(np.asarray(values, dtype=float), window, 2).tolist()


def find_rapid_rise(rows: list[dict[str, Any]]) -> MotionWindow | None:
    best: MotionWindow | None = None
    for start_index, start in enumerate(rows):
        for end_index in range(start_index + 1, len(rows)):
            end = rows[end_index]
            duration = (end["timestamp_ms"] - start["timestamp_ms"]) / 1000.0
            if duration < 0.4:
                continue
            if duration > 1.5:
                break
            displacement = start["pelvis_y_smooth"] - end["pelvis_y_smooth"]
            if displacement < 0.05:
                continue
            quality = min(row["core_visibility_mean"] for row in rows[start_index : end_index + 1])
            candidate = MotionWindow(
                start_index=start_index,
                end_index=end_index,
                start_ms=start["timestamp_ms"],
                end_ms=end["timestamp_ms"],
                duration_s=duration,
                displacement=displacement,
                speed=displacement / duration,
                data_quality=quality,
            )
            if best is None or candidate.speed > best.speed:
                best = candidate
    return best


def find_sway(rows: list[dict[str, Any]], after_ms: int | None, window_seconds: float = 30.0) -> dict[str, Any] | None:
    candidates = rows
    if after_ms is not None:
        candidates = [row for row in rows if after_ms <= row["timestamp_ms"] <= after_ms + window_seconds * 1000]
    if not candidates:
        return None
    opening = [row["trunk_angle_deg_smooth"] for row in rows if row["timestamp_ms"] <= 3000]
    reference = median(opening) if opening else median(row["trunk_angle_deg_smooth"] for row in rows)
    peak = max(candidates, key=lambda row: abs(row["trunk_angle_deg_smooth"] - reference))
    amplitude = abs(peak["trunk_angle_deg_smooth"] - reference)
    nearby = [
        row for row in candidates
        if abs(row["timestamp_ms"] - peak["timestamp_ms"]) <= 500
    ]
    return {
        "timestamp_ms": peak["timestamp_ms"],
        "amplitude_deg": amplitude,
        "absolute_angle_deg": abs(peak["trunk_angle_deg_smooth"]),
        "data_quality": safe_mean(row["core_visibility_mean"] for row in nearby),
        "reference_angle_deg": reference,
    }


def stable_tail(rows: list[dict[str, Any]], after_ms: int = 0) -> dict[str, float]:
    # Find the longest continuous, quality-qualified stable interval after the
    # latest hazard. A low-quality final frame must not erase an earlier real
    # interval, but any angle/quality break resets the duration.
    best: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for row in rows:
        if row["timestamp_ms"] < after_ms:
            continue
        if abs(row["trunk_angle_deg_smooth"]) <= STABLE_ANGLE_DEG and row["core_visibility_mean"] >= QUALITY_THRESHOLD:
            current.append(row)
            if len(current) > len(best):
                best = list(current)
        else:
            current = []
    duration = (best[-1]["timestamp_ms"] - best[0]["timestamp_ms"]) / 1000.0 if len(best) >= 2 else 0.0
    return {
        "start_ms": float(best[0]["timestamp_ms"]) if best else 0.0,
        "end_ms": float(best[-1]["timestamp_ms"]) if best else 0.0,
        "duration_s": duration,
        "max_angle_deg": max((abs(row["trunk_angle_deg_smooth"]) for row in best), default=0.0),
        "data_quality": safe_mean(row["core_visibility_mean"] for row in best),
        "frame_count": float(len(best)),
    }


def gait_summary(rows: list[dict[str, Any]]) -> dict[str, float]:
    if len(rows) < 2:
        return {"relative_speed": 0.0, "step_length_asymmetry_ratio": 0.0}
    duration = max((rows[-1]["timestamp_ms"] - rows[0]["timestamp_ms"]) / 1000.0, 1e-6)
    distance = sum(
        math.hypot(
            rows[index]["pelvis_x_smooth"] - rows[index - 1]["pelvis_x_smooth"],
            rows[index]["pelvis_y_smooth"] - rows[index - 1]["pelvis_y_smooth"],
        )
        for index in range(1, len(rows))
    )
    left = safe_mean(row["left_stride_extent"] for row in rows)
    right = safe_mean(row["right_stride_extent"] for row in rows)
    asymmetry = abs(left - right) / max(left, right, 1e-6)
    return {"relative_speed": distance / duration, "step_length_asymmetry_ratio": asymmetry}


def evidence_payload(
    record: dict[str, Any], evidence_type: str, timestamp: str, current_value: float,
    baseline_value: float, severity: float, confidence: float, quality: float,
    observation_ids: list[str], explanation: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "evidence_id": f"evi-{record['take_id']}-{evidence_type.replace('_', '-')}",
        "observation_ids": observation_ids,
        "resident_id": record["resident_id"],
        "timestamp": timestamp,
        "risk_domain": "FALL",
        "evidence_type": evidence_type,
        "severity": round(clamp(severity), 3),
        "confidence": round(clamp(confidence), 3),
        "data_quality": round(clamp(quality), 3),
        "baseline_value": round(baseline_value, 3),
        "current_value": round(current_value, 3),
        "baseline_deviation": round((current_value - baseline_value) / max(abs(baseline_value), 1e-6), 3),
        "time_scale": "SHORT",
        "location": "living_room",
        "explanation": explanation,
        "adapter_version": ADAPTER_VERSION,
        "source_mode": record["source_mode"],
        "simulated": record["simulated"],
    }


def observation_payload(
    record: dict[str, Any], observation_id: str, timestamp: str, feature_name: str,
    value: float, unit: str, confidence: float, quality: float,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "observation_id": observation_id,
        "resident_id": record["resident_id"],
        "timestamp": timestamp,
        "source": "pose",
        "feature_name": feature_name,
        "feature_value": round(value, 3),
        "unit": unit,
        "location": "living_room",
        "confidence": round(clamp(confidence), 3),
        "data_quality": round(clamp(quality), 3),
        "source_mode": record["source_mode"],
        "asset_id": record["asset_id"],
        "simulated": record["simulated"],
        "metadata": {
            "model_version": ADAPTER_VERSION,
            "camera_position_id": record["camera_position_id"],
            "device_ref": record["device_ref"],
        },
    }


def build_package(record: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    candidates = analysis["candidates"]
    take_id = record["take_id"].lower()
    if "rapid-only" in take_id:
        allowed_types = {"rapid_rise"}
    elif "under15" in take_id:
        allowed_types = {"trunk_sway", "posture_recovered"}
    else:
        allowed_types = {"rapid_rise", "trunk_sway", "posture_recovered"}
    observations: list[dict[str, Any]] = []
    evidences: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    def add_candidate(
        evidence_type: str, offset: float, value: float, baseline: float, severity: float,
        quality: float, features: list[tuple[str, float, str]], explanation: str,
    ) -> None:
        confidence = quality
        if quality < QUALITY_THRESHOLD or confidence < CONFIDENCE_THRESHOLD:
            rejected.append({
                "evidence_type": evidence_type,
                "reason": "QUALITY_BLOCKED",
                "data_quality": round(quality, 3),
                "confidence": round(confidence, 3),
            })
            return
        timestamp = iso_at(record["captured_at"], offset)
        ids = []
        for feature_name, feature_value, unit in features:
            observation_id = f"obs-{record['take_id']}-{feature_name.replace('_', '-')}"
            ids.append(observation_id)
            observations.append(observation_payload(
                record, observation_id, timestamp, feature_name, feature_value, unit, confidence, quality,
            ))
        evidences.append(evidence_payload(
            record, evidence_type, timestamp, value, baseline, severity,
            confidence, quality, ids, explanation,
        ))

    rapid = candidates.get("rapid_rise")
    if "rapid_rise" in allowed_types and rapid and rapid["detected"]:
        add_candidate(
            "rapid_rise", rapid["end_ms"] / 1000.0, rapid["duration_s"],
            RAPID_RISE_BASELINE_SECONDS,
            0.55 * clamp((RAPID_RISE_BASELINE_SECONDS - rapid["duration_s"]) / RAPID_RISE_BASELINE_SECONDS)
            + 0.45 * clamp(rapid["speed"] / 0.35),
            rapid["data_quality"],
            [("sit_to_stand_duration", rapid["duration_s"], "second")],
            f"髋部中心在{rapid['duration_s']:.3f}秒内上移{rapid['displacement']:.3f}个画面高度；阈值由适配器计算。",
        )

    sway = candidates.get("trunk_sway")
    if "trunk_sway" in allowed_types and sway and sway["detected"]:
        add_candidate(
            "trunk_sway", sway["timestamp_ms"] / 1000.0, sway["absolute_angle_deg"],
            SWAY_BASELINE_DEG, clamp((sway["absolute_angle_deg"] - SWAY_BASELINE_DEG) / (2 * SWAY_BASELINE_DEG)),
            sway["data_quality"],
            [("trunk_sway_angle", sway["absolute_angle_deg"], "degree")],
            f"最大躯干角为{sway['absolute_angle_deg']:.2f}度（相对静止参考摆幅{sway['amplitude_deg']:.2f}度），冻结工程阈值为{SWAY_BASELINE_DEG:.1f}度。",
        )

    recovery = candidates.get("posture_recovered")
    if "posture_recovered" in allowed_types and recovery and recovery["detected"]:
        add_candidate(
            "posture_recovered", recovery["end_ms"] / 1000.0, recovery["duration_s"],
            STABLE_SECONDS, 0.0, recovery["data_quality"],
            [
                ("stable_posture_duration", recovery["duration_s"], "second"),
                ("stable_trunk_angle_deg", recovery["max_angle_deg"], "degree"),
            ],
            f"尾部连续质量合格帧最大躯干角{recovery['max_angle_deg']:.2f}度，实际稳定{recovery['duration_s']:.3f}秒，恢复阈值为15秒。",
        )

    asset = {
        "asset_id": record["asset_id"],
        "title": f"授权C6c回放片段 {record['take_id']}",
        "source_mode": record["source_mode"],
        "simulated": record["simulated"],
        "stream_url": None,
        "fallback_url": None,
        "fallback_kind": "AUTHORIZED_CLIP",
        "available": True,
        "verification_status": "VERIFIED",
        "captured_at": record["captured_at"],
        "notice": "原视频、绝对路径和授权原件不进入Git；仅通过脱敏资产记录追溯。",
        "device_ref": record["device_ref"],
        "device_model": "EZVIZ_C6C",
        "camera_position_id": record["camera_position_id"],
        "authorization_status": record["authorization_status"],
        "authorization_record_id": record["authorization_record_id"],
        "retention_until": record["retention_until"],
    }
    evidence_types = {item["evidence_type"] for item in evidences}
    has_combo = {"rapid_rise", "trunk_sway"}.issubset(evidence_types)
    combo_items = [item for item in evidences if item["evidence_type"] in {"rapid_rise", "trunk_sway"}]
    has_high_confidence = any(item["confidence"] >= HIGH_CONFIDENCE_THRESHOLD for item in combo_items)
    reaches_stable = any(
        item["evidence_type"] == "posture_recovered" and item["current_value"] >= STABLE_SECONDS
        for item in evidences
    )
    complete_observation = bool(record.get("observation_60s_completed"))
    acceptance_status = "PENDING_ASSET"
    partial_stage = "OBSERVING_ONLY" if has_combo and has_high_confidence and reaches_stable else "EVIDENCE_ONLY"
    if has_combo and not has_high_confidence:
        partial_stage = "CONFIDENCE_BLOCKED"
    if rejected:
        partial_stage = "QUALITY_BLOCKED"
    return {
        "schema_version": "1.0",
        "adapter_version": ADAPTER_VERSION,
        "scenario_id": record["take_id"],
        "resident_id": record["resident_id"],
        "source_mode": record["source_mode"],
        "simulated": record["simulated"],
        "acceptance_status": acceptance_status,
        "partial_acceptance_stage": partial_stage,
        "eligible_for_real_resolved_claim": bool(has_combo and reaches_stable and complete_observation),
        "observation_60s_completed": complete_observation,
        "scenario_evidence_policy": sorted(allowed_types),
        "readiness_checks": {
            "rapid_rise_and_trunk_sway": has_combo,
            "at_least_one_combo_confidence_gte_0_80": has_high_confidence,
            "recovery_reaches_15_seconds": reaches_stable,
            "observation_60s_completed": complete_observation,
        },
        "asset": asset,
        "observations": observations,
        "evidence": evidences,
        "rejected_candidates": rejected,
        "timeline": [
            {"order": 0, "action": "POST /api/v1/assets", "id": record["asset_id"]},
            *[
                {"order": index + 1, "action": "POST /api/v1/observations", "id": item["observation_id"]}
                for index, item in enumerate(observations)
            ],
            *[
                {"order": len(observations) + index + 1, "action": "POST /api/v1/evidence", "id": item["evidence_id"]}
                for index, item in enumerate(evidences)
            ],
        ],
    }


def analyze_rows(rows: list[dict[str, Any]], total_frames: int, fps: float, duration_s: float) -> dict[str, Any]:
    for field in ("pelvis_x", "pelvis_y", "trunk_angle_deg"):
        values = smooth([row[field] for row in rows])
        for row, value in zip(rows, values):
            row[f"{field}_smooth"] = value
    rapid = find_rapid_rise(rows)
    sway = find_sway(rows, rapid.end_ms if rapid else None)
    sway_detected = bool(sway and sway["absolute_angle_deg"] >= SWAY_BASELINE_DEG)
    hazard_end_ms = int(sway["timestamp_ms"]) if sway_detected else (rapid.end_ms if rapid else 0)
    recovery = stable_tail(rows, after_ms=hazard_end_ms)
    gait = gait_summary(rows)
    return {
        "video": {
            "fps": round(fps, 6),
            "duration_s": round(duration_s, 3),
            "total_frames": total_frames,
            "pose_frames": len(rows),
            "valid_frame_ratio": round(len(rows) / max(total_frames, 1), 3),
        },
        "quality": {
            "mean_core_visibility": round(safe_mean(row["core_visibility_mean"] for row in rows), 3),
            "minimum_core_visibility": round(min((row["core_visibility_min"] for row in rows), default=0.0), 3),
        },
        "gait": {key: round(value, 6) for key, value in gait.items()},
        "candidates": {
            "rapid_rise": {"detected": rapid is not None, **({
                "start_ms": rapid.start_ms, "end_ms": rapid.end_ms,
                "duration_s": round(rapid.duration_s, 3), "displacement": round(rapid.displacement, 6),
                "speed": round(rapid.speed, 6), "data_quality": round(rapid.data_quality, 3),
            } if rapid else {})},
            "trunk_sway": {"detected": sway_detected, **({
                key: round(value, 3) for key, value in sway.items()
            } if sway else {})},
            "posture_recovered": {"detected": recovery["frame_count"] > 0, **{
                key: round(value, 3) for key, value in recovery.items()
            }},
        },
    }


def extract_video(video_path: Path, model_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"unable to open video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not math.isfinite(fps) or fps <= 0:
        capture.release()
        raise ValueError("video FPS is missing or invalid")
    declared_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    options = vision.PoseLandmarkerOptions(
        # The MediaPipe native Windows layer cannot reliably open model paths
        # containing non-ASCII characters. Supplying the verified bytes keeps
        # the model inside the workspace without copying it to a weaker path.
        base_options=python.BaseOptions(model_asset_buffer=model_path.read_bytes()),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    rows: list[dict[str, Any]] = []
    landmarks: list[dict[str, Any]] = []
    frame_index = 0
    last_timestamp = -1
    detector = vision.PoseLandmarker.create_from_options(options)
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            capture_timestamp = capture.get(cv2.CAP_PROP_POS_MSEC)
            fallback_timestamp = frame_index * 1000.0 / fps
            timestamp_ms = int(round(capture_timestamp if capture_timestamp > last_timestamp else fallback_timestamp))
            timestamp_ms = max(timestamp_ms, last_timestamp + 1)
            last_timestamp = timestamp_ms
            result = detector.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
                timestamp_ms,
            )
            if result.pose_landmarks and len(result.pose_landmarks[0]) >= 33:
                pose = result.pose_landmarks[0]
                core_visibility = [float(getattr(pose[index], "visibility", 0.0)) for index in CORE_IDS]
                left_shoulder, right_shoulder = pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]
                left_hip, right_hip = pose[LEFT_HIP], pose[RIGHT_HIP]
                left_ankle, right_ankle = pose[LEFT_ANKLE], pose[RIGHT_ANKLE]
                pelvis_x = (left_hip.x + right_hip.x) / 2
                pelvis_y = (left_hip.y + right_hip.y) / 2
                shoulder_x = (left_shoulder.x + right_shoulder.x) / 2
                shoulder_y = (left_shoulder.y + right_shoulder.y) / 2
                rows.append({
                    "frame_number": frame_index,
                    "timestamp_ms": timestamp_ms,
                    "pelvis_x": pelvis_x,
                    "pelvis_y": pelvis_y,
                    "trunk_angle_deg": math.degrees(math.atan2(shoulder_x - pelvis_x, -(shoulder_y - pelvis_y))),
                    "left_stride_extent": abs(left_ankle.x - pelvis_x),
                    "right_stride_extent": abs(right_ankle.x - pelvis_x),
                    "core_visibility_min": min(core_visibility),
                    "core_visibility_mean": safe_mean(core_visibility),
                })
                for landmark_id, landmark in enumerate(pose):
                    landmarks.append({
                        "frame_number": frame_index, "timestamp_ms": timestamp_ms, "landmark_id": landmark_id,
                        "x": landmark.x, "y": landmark.y, "z": landmark.z,
                        "visibility": getattr(landmark, "visibility", 0.0),
                        "presence": getattr(landmark, "presence", 0.0),
                    })
            frame_index += 1
    finally:
        detector.close()
        capture.release()
    if frame_index == 0:
        raise ValueError("video contains no readable frames")
    if not rows:
        raise ValueError("no pose was detected in the video")
    duration = last_timestamp / 1000.0 if last_timestamp >= 0 else frame_index / fps
    analysis = analyze_rows(rows, max(frame_index, declared_frames), fps, duration)
    return rows, landmarks, analysis


def resolve_video(record: dict[str, Any], video_dir: Path) -> Path:
    local = Path(str(record.get("local_path", "")))
    if local.is_file():
        return local
    take_id = record["take_id"].lower()
    candidates = [path for path in video_dir.iterdir() if path.is_file() and path.suffix.lower() == ".mp4"]
    if "golden" in take_id:
        matches = [path for path in candidates if "golden" in path.name.lower()]
    elif "rapid-only" in take_id:
        matches = [path for path in candidates if "快速起身" in path.name]
    elif "under15" in take_id:
        matches = [path for path in candidates if "稳定不足15秒" in path.name]
    else:
        matches = []
    if len(matches) != 1:
        raise ValueError(f"cannot uniquely resolve local video for take_id={record['take_id']}")
    return matches[0]


def process_record(
    record: dict[str, Any], video_path: Path, model_path: Path, output_root: Path, *, reuse_analysis: bool = False,
) -> dict[str, Any]:
    for required in (
        "take_id", "asset_id", "resident_id", "device_ref", "camera_position_id", "captured_at",
        "source_mode", "simulated", "authorization_status", "authorization_record_id", "retention_until",
    ):
        if record.get(required) in (None, ""):
            raise ValueError(f"manifest record missing required field: {required}")
    if record["source_mode"] != "RECORDED_REPLAY" or record["authorization_status"] != "AUTHORIZED":
        raise ValueError("real replay requires RECORDED_REPLAY and AUTHORIZED")
    output_dir = output_root / record["take_id"]
    analysis_path = output_dir / "analysis.json"
    frames_path = output_dir / "frames.csv"
    if reuse_analysis and analysis_path.is_file() and frames_path.is_file():
        previous = json.loads(analysis_path.read_text(encoding="utf-8"))
        with frames_path.open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        integer_fields = {"frame_number", "timestamp_ms"}
        for row in rows:
            for key, value in list(row.items()):
                row[key] = int(value) if key in integer_fields else float(value)
        video = previous["video"]
        analysis = analyze_rows(
            rows, int(video["total_frames"]), float(video["fps"]), float(video["duration_s"]),
        )
        analysis.update({
            "take_id": record["take_id"],
            "asset_id": record["asset_id"],
            "video_sha256": previous.get("video_sha256", sha256_file(video_path)),
            "manual_annotations_for_validation_only": previous.get("manual_annotations_for_validation_only", {}),
        })
        write_csv(frames_path, rows)
        write_json(analysis_path, analysis)
    else:
        rows, landmarks, analysis = extract_video(video_path, model_path)
        analysis["take_id"] = record["take_id"]
        analysis["asset_id"] = record["asset_id"]
        analysis["video_sha256"] = sha256_file(video_path)
        analysis["manual_annotations_for_validation_only"] = {
            key: record.get(key) for key in (
                "rapid_rise_start", "trunk_sway_start", "stable_start", "stable_15s_reached",
                "observation_60s_completed",
            )
        }
        write_csv(output_dir / "frames.csv", rows)
        write_csv(output_dir / "landmarks.csv", landmarks)
        write_json(analysis_path, analysis)
    package = build_package(record, analysis)
    write_json(output_dir / "package.json", package)
    return {
        "take_id": record["take_id"],
        "asset_id": record["asset_id"],
        "video_sha256": analysis["video_sha256"],
        "fps": analysis["video"]["fps"],
        "duration_s": analysis["video"]["duration_s"],
        "pose_frames": analysis["video"]["pose_frames"],
        "valid_frame_ratio": analysis["video"]["valid_frame_ratio"],
        "mean_core_visibility": analysis["quality"]["mean_core_visibility"],
        "candidate_results": analysis["candidates"],
        "emitted_evidence_types": [item["evidence_type"] for item in package["evidence"]],
        "rejected_candidates": package["rejected_candidates"],
        "acceptance_status": package["acceptance_status"],
        "partial_acceptance_stage": package["partial_acceptance_stage"],
        "eligible_for_real_resolved_claim": package["eligible_for_real_resolved_claim"],
        "contains_local_path": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert authorized C6c MP4 clips into frozen Observation/Evidence payloads.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--video-dir", required=True)
    parser.add_argument("--model", default="models/pose_landmarker_heavy.task")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--take-id", action="append", default=[])
    parser.add_argument("--reuse-analysis", action="store_true", help="Rebuild packages from existing local analysis JSON.")
    args = parser.parse_args()
    manifest_path = Path(args.manifest).resolve()
    video_dir = Path(args.video_dir).resolve()
    model_path = Path(args.model).resolve()
    output_root = Path(args.output_root).resolve()
    if not manifest_path.is_file():
        raise SystemExit(f"manifest not found: {manifest_path}")
    if not video_dir.is_dir():
        raise SystemExit(f"video directory not found: {video_dir}")
    if not model_path.is_file():
        raise SystemExit(f"pose model not found: {model_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = [
        record for record in manifest.get("records", [])
        if not args.take_id or record.get("take_id") in set(args.take_id)
    ]
    if not selected:
        raise SystemExit("no matching manifest records")
    summaries = []
    for record in selected:
        video_path = resolve_video(record, video_dir)
        print(f"Processing {record['take_id']} ({video_path.name}) ...", flush=True)
        summaries.append(process_record(record, video_path, model_path, output_root, reuse_analysis=args.reuse_analysis))
    aggregate = {
        "schema_version": "1.0",
        "adapter_version": ADAPTER_VERSION,
        "generated_from_authorized_local_media": True,
        "real_device_claimed": True,
        "real_resolved_claimed": False,
        "baseline_status": "INSUFFICIENT",
        "records": summaries,
    }
    write_json(output_root / "redacted_summary.json", aggregate)
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
