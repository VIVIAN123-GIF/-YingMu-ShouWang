from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from dataclasses import dataclass

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from scipy.signal import find_peaks

from recorded_replay_adapter import (
    CORE_IDS,
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_SHOULDER,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    safe_mean,
    smooth as smooth_series,
)


@dataclass
class SequencePaths:
    sequence_id: str
    label: str
    image_dir: pathlib.Path
    metadata_csv: pathlib.Path


def build_landmarker(model_path: pathlib.Path) -> vision.PoseLandmarker:
    # Match the C6c replay adapter and avoid native-path encoding failures on
    # Windows workspaces with non-ASCII directory names.
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


def discover_sequences(extracted_root: pathlib.Path, original_root: pathlib.Path, camera_filter: str) -> list[SequencePaths]:
    sequences: list[SequencePaths] = []
    for outer_dir in sorted(path for path in extracted_root.iterdir() if path.is_dir()):
        nested_dir = outer_dir / outer_dir.name
        image_dir = nested_dir if nested_dir.exists() else outer_dir
        name = outer_dir.name
        if camera_filter and camera_filter not in name:
            continue
        if name.startswith("fall-"):
            sequence_id = name.rsplit("-", 2)[0]
            label = "fall"
        elif name.startswith("adl-"):
            sequence_id = name.rsplit("-", 2)[0]
            label = "adl"
        else:
            continue
        metadata_csv = original_root / f"{sequence_id}-data.csv"
        if not metadata_csv.exists():
            continue
        sequences.append(
            SequencePaths(
                sequence_id=name,
                label=label,
                image_dir=image_dir,
                metadata_csv=metadata_csv,
            )
        )
    return sequences


def load_timestamps(metadata_csv: pathlib.Path) -> dict[int, int]:
    timestamps: dict[int, int] = {}
    with metadata_csv.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 2:
                continue
            frame_number = int(row[0])
            timestamp_ms = int(row[1])
            timestamps[frame_number] = timestamp_ms
    return timestamps


def parse_frame_number(image_path: pathlib.Path) -> int:
    return int(image_path.stem.split("-")[-1])


def dominant_frequency_hz(signal_values: list[float], timestamps_ms: list[int]) -> float:
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


def asymmetry_ratio(left_series: list[float], right_series: list[float]) -> float:
    left = np.asarray(left_series, dtype=np.float64)
    right = np.asarray(right_series, dtype=np.float64)
    if left.size == 0 or right.size == 0:
        return 0.0

    peak_distance = max(1, left.size // 10)
    left_peaks, _ = find_peaks(left, distance=peak_distance)
    right_peaks, _ = find_peaks(right, distance=peak_distance)

    left_values = left[left_peaks] if left_peaks.size > 0 else np.sort(left)[-min(3, left.size) :]
    right_values = right[right_peaks] if right_peaks.size > 0 else np.sort(right)[-min(3, right.size) :]

    left_mean = float(np.mean(left_values)) if left_values.size > 0 else 0.0
    right_mean = float(np.mean(right_values)) if right_values.size > 0 else 0.0
    denom = max(left_mean, right_mean, 1e-6)
    return abs(left_mean - right_mean) / denom


def extract_sequence_rows(
    detector: vision.PoseLandmarker,
    sequence: SequencePaths,
    timestamps: dict[int, int],
    visibility_threshold: float,
    frame_stride: int,
    timestamp_offset_ms: int,
) -> tuple[list[dict[str, float | int | str]], dict[str, float | int | str]]:
    image_paths = sorted(path for path in sequence.image_dir.iterdir() if path.suffix.lower() == ".png")[::frame_stride]
    frame_rows: list[dict[str, float | int | str]] = []
    total_frames = len(image_paths)
    detected_frames = 0

    for sample_index, image_path in enumerate(image_paths):
        frame_number = parse_frame_number(image_path)
        _ = timestamps.get(frame_number, (frame_number - 1) * 33)
        timestamp_ms = timestamp_offset_ms + sample_index * 33 * frame_stride
        frame_bgr = cv2.imread(str(image_path))
        if frame_bgr is None:
            continue
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        detection_result = detector.detect_for_video(mp_image, int(timestamp_ms))

        if not detection_result.pose_landmarks:
            continue
        pose = detection_result.pose_landmarks[0]
        if len(pose) < 33:
            continue

        core_visibility = [float(getattr(pose[idx], "visibility", 0.0)) for idx in CORE_IDS]
        if min(core_visibility) < visibility_threshold:
            continue

        detected_frames += 1
        left_shoulder = pose[LEFT_SHOULDER]
        right_shoulder = pose[RIGHT_SHOULDER]
        left_hip = pose[LEFT_HIP]
        right_hip = pose[RIGHT_HIP]
        left_ankle = pose[LEFT_ANKLE]
        right_ankle = pose[RIGHT_ANKLE]

        pelvis_x = (left_hip.x + right_hip.x) / 2.0
        pelvis_y = (left_hip.y + right_hip.y) / 2.0
        shoulder_x = (left_shoulder.x + right_shoulder.x) / 2.0
        shoulder_y = (left_shoulder.y + right_shoulder.y) / 2.0
        trunk_dx = shoulder_x - pelvis_x
        trunk_dy = shoulder_y - pelvis_y
        trunk_angle_deg = math.degrees(math.atan2(trunk_dx, -trunk_dy))
        left_stride_extent = abs(left_ankle.x - pelvis_x)
        right_stride_extent = abs(right_ankle.x - pelvis_x)

        frame_rows.append(
            {
                "sequence_id": sequence.sequence_id,
                "label": sequence.label,
                "frame_number": frame_number,
                "timestamp_ms": int(timestamp_ms),
                "pelvis_x": pelvis_x,
                "pelvis_y": pelvis_y,
                "shoulder_x": shoulder_x,
                "shoulder_y": shoulder_y,
                "trunk_angle_deg": trunk_angle_deg,
                "ankle_gap": abs(left_ankle.x - right_ankle.x),
                "left_stride_extent": left_stride_extent,
                "right_stride_extent": right_stride_extent,
                "core_visibility_min": min(core_visibility),
                "core_visibility_mean": safe_mean(core_visibility),
            }
        )

    if not frame_rows:
        return [], {
            "sequence_id": sequence.sequence_id,
            "label": sequence.label,
            "total_frames": total_frames,
            "detected_frames": 0,
            "valid_frame_ratio": 0.0,
            "step_speed": 0.0,
            "sway_frequency_hz": 0.0,
            "step_length_asymmetry_ratio": 0.0,
            "mean_core_visibility": 0.0,
        }

    pelvis_x_series = smooth_series([float(row["pelvis_x"]) for row in frame_rows])
    pelvis_y_series = smooth_series([float(row["pelvis_y"]) for row in frame_rows])
    trunk_angle_series = smooth_series([float(row["trunk_angle_deg"]) for row in frame_rows])
    left_extent_series = smooth_series([float(row["left_stride_extent"]) for row in frame_rows])
    right_extent_series = smooth_series([float(row["right_stride_extent"]) for row in frame_rows])
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

    summary_row = {
        "sequence_id": sequence.sequence_id,
        "label": sequence.label,
        "total_frames": total_frames,
        "detected_frames": len(frame_rows),
        "valid_frame_ratio": len(frame_rows) / max(total_frames, 1),
        "step_speed": step_speed,
        "sway_frequency_hz": dominant_frequency_hz(trunk_angle_series, timestamps_ms_series),
        "step_length_asymmetry_ratio": asymmetry_ratio(left_extent_series, right_extent_series),
        "mean_core_visibility": safe_mean(float(row["core_visibility_mean"]) for row in frame_rows),
    }
    return frame_rows, summary_row


def write_csv(path: pathlib.Path, rows: list[dict[str, float | int | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build cleaned URFD gait feature datasets.")
    parser.add_argument("--model", default="models/pose_landmarker_heavy.task", help="Path to pose model.")
    parser.add_argument("--urfd-root", default="data/raw/urfd", help="URFD dataset root.")
    parser.add_argument(
        "--output-dir",
        default="deliverables/zy/pose-demo/processed",
        help="Directory for cleaned datasets.",
    )
    parser.add_argument("--visibility-threshold", type=float, default=0.5, help="Minimum visibility for core joints.")
    parser.add_argument("--frame-stride", type=int, default=2, help="Use every N-th frame.")
    parser.add_argument("--camera-filter", default="cam0", help="Only process sequence directories containing this camera tag.")
    args = parser.parse_args()

    urfd_root = pathlib.Path(args.urfd_root).resolve()
    extracted_root = urfd_root / "extracted"
    original_root = urfd_root / "original"
    output_dir = pathlib.Path(args.output_dir).resolve()

    sequences = discover_sequences(extracted_root, original_root, camera_filter=args.camera_filter)
    frame_rows_all: list[dict[str, float | int | str]] = []
    summary_rows: list[dict[str, float | int | str]] = []
    timestamp_offset_ms = 0

    for sequence in sequences:
        print(f"Processing {sequence.sequence_id} ...")
        detector = build_landmarker(pathlib.Path(args.model).resolve())
        try:
            timestamps = load_timestamps(sequence.metadata_csv)
            frame_rows, summary_row = extract_sequence_rows(
                detector=detector,
                sequence=sequence,
                timestamps=timestamps,
                visibility_threshold=args.visibility_threshold,
                frame_stride=max(args.frame_stride, 1),
                timestamp_offset_ms=timestamp_offset_ms,
            )
            frame_rows_all.extend(frame_rows)
            summary_rows.append(summary_row)
            if frame_rows:
                timestamp_offset_ms = int(frame_rows[-1]["timestamp_ms"]) + 1000
            else:
                timestamp_offset_ms += 1000
        finally:
            detector.close()

    write_csv(output_dir / "urfd_pose_cleaned_frames.csv", frame_rows_all)
    write_csv(output_dir / "urfd_gait_features.csv", summary_rows)

    summary_payload = {
        "sequence_count": len(summary_rows),
        "frame_row_count": len(frame_rows_all),
        "feature_columns": [
            "step_speed",
            "sway_frequency_hz",
            "step_length_asymmetry_ratio",
            "valid_frame_ratio",
            "mean_core_visibility",
        ],
        "label_counts": {
            "fall": sum(1 for row in summary_rows if row["label"] == "fall"),
            "adl": sum(1 for row in summary_rows if row["label"] == "adl"),
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "build_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary_payload, handle, ensure_ascii=False, indent=2)

    print(f"Sequences processed: {summary_payload['sequence_count']}")
    print(f"Cleaned frame rows: {summary_payload['frame_row_count']}")
    print(f"Sequence feature dataset: {output_dir / 'urfd_gait_features.csv'}")
    print(f"Frame-level cleaned dataset: {output_dir / 'urfd_pose_cleaned_frames.csv'}")
    print(f"Summary: {output_dir / 'build_summary.json'}")


if __name__ == "__main__":
    main()
