from __future__ import annotations

import argparse
import csv
import pathlib
from dataclasses import dataclass

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.framework.formats import landmark_pb2
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}


@dataclass
class FramePacket:
    frame_bgr: np.ndarray
    frame_index: int
    timestamp_ms: int


def list_image_frames(directory: pathlib.Path) -> list[pathlib.Path]:
    return sorted(path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)


def iter_frames(input_path: pathlib.Path, fps_hint: float) -> tuple[list[FramePacket], float]:
    if input_path.is_dir():
        image_paths = list_image_frames(input_path)
        if not image_paths:
            raise ValueError(f"No image frames found in directory: {input_path}")
        fps = fps_hint
        frames: list[FramePacket] = []
        for index, image_path in enumerate(image_paths):
            frame = cv2.imread(str(image_path))
            if frame is None:
                continue
            timestamp_ms = int(index * 1000 / fps)
            frames.append(FramePacket(frame_bgr=frame, frame_index=index, timestamp_ms=timestamp_ms))
        return frames, fps

    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise ValueError(f"Unable to open video: {input_path}")

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


def build_landmarker(model_path: pathlib.Path) -> vision.PoseLandmarker:
    base_options = python.BaseOptions(model_asset_path=str(model_path))
    options = vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return vision.PoseLandmarker.create_from_options(options)


def annotate_frame(frame_rgb: np.ndarray, detection_result: vision.PoseLandmarkerResult) -> np.ndarray:
    annotated = frame_rgb.copy()
    for pose_landmarks in detection_result.pose_landmarks:
        landmark_list = landmark_pb2.NormalizedLandmarkList()
        landmark_list.landmark.extend(
            landmark_pb2.NormalizedLandmark(
                x=landmark.x,
                y=landmark.y,
                z=landmark.z,
                visibility=landmark.visibility,
                presence=landmark.presence,
            )
            for landmark in pose_landmarks
        )
        mp.solutions.drawing_utils.draw_landmarks(
            annotated,
            landmark_list,
            mp.solutions.pose.POSE_CONNECTIONS,
            landmark_drawing_spec=mp.solutions.drawing_styles.get_default_pose_landmarks_style(),
        )
    return annotated


def write_landmark_rows(
    writer: csv.DictWriter,
    source_name: str,
    frame_index: int,
    timestamp_ms: int,
    detection_result: vision.PoseLandmarkerResult,
) -> None:
    if not detection_result.pose_landmarks:
        return

    normalized_landmarks = detection_result.pose_landmarks[0]
    world_landmarks = detection_result.pose_world_landmarks[0] if detection_result.pose_world_landmarks else []

    for landmark_id, landmark in enumerate(normalized_landmarks):
        world_landmark = world_landmarks[landmark_id] if landmark_id < len(world_landmarks) else None
        writer.writerow(
            {
                "source_video": source_name,
                "frame_idx": frame_index,
                "timestamp_ms": timestamp_ms,
                "landmark_id": landmark_id,
                "x": landmark.x,
                "y": landmark.y,
                "z": landmark.z,
                "world_x": "" if world_landmark is None else world_landmark.x,
                "world_y": "" if world_landmark is None else world_landmark.y,
                "world_z": "" if world_landmark is None else world_landmark.z,
                "visibility": getattr(landmark, "visibility", ""),
                "presence": getattr(landmark, "presence", ""),
            }
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MediaPipe pose landmarker on a video or image sequence.")
    parser.add_argument("--input", required=True, help="Video file path or image-directory path.")
    parser.add_argument("--model", default="models/pose_landmarker_heavy.task", help="Pose model path.")
    parser.add_argument("--output-dir", default="outputs/demo", help="Directory for CSV and annotated video.")
    parser.add_argument("--fps-hint", type=float, default=30.0, help="FPS to use when the input is an image directory.")
    parser.add_argument("--max-frames", type=int, default=0, help="Optional frame limit for smoke tests.")
    args = parser.parse_args()

    input_path = pathlib.Path(args.input).resolve()
    model_path = pathlib.Path(args.model).resolve()
    output_dir = pathlib.Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    frames, fps = iter_frames(input_path, fps_hint=args.fps_hint)
    if args.max_frames > 0:
        frames = frames[: args.max_frames]
    if not frames:
        raise ValueError(f"No frames available from input: {input_path}")

    csv_path = output_dir / f"{input_path.stem}_landmarks.csv"
    video_path = output_dir / f"{input_path.stem}_annotated.mp4"

    writer_fields = [
        "source_video",
        "frame_idx",
        "timestamp_ms",
        "landmark_id",
        "x",
        "y",
        "z",
        "world_x",
        "world_y",
        "world_z",
        "visibility",
        "presence",
    ]

    video_writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (frames[0].frame_bgr.shape[1], frames[0].frame_bgr.shape[0]),
    )

    detector = build_landmarker(model_path)
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=writer_fields)
        writer.writeheader()

        try:
            for packet in frames:
                frame_rgb = cv2.cvtColor(packet.frame_bgr, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
                detection_result = detector.detect_for_video(mp_image, packet.timestamp_ms)
                write_landmark_rows(writer, input_path.name, packet.frame_index, packet.timestamp_ms, detection_result)

                annotated_rgb = annotate_frame(frame_rgb, detection_result)
                annotated_bgr = cv2.cvtColor(annotated_rgb, cv2.COLOR_RGB2BGR)
                video_writer.write(annotated_bgr)
        finally:
            detector.close()

    video_writer.release()
    print(f"Annotated video: {video_path}")
    print(f"Landmark CSV: {csv_path}")


if __name__ == "__main__":
    main()
