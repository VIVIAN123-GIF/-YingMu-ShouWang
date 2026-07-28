from __future__ import annotations

import argparse
import pathlib

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify MediaPipe pose landmarker environment.")
    parser.add_argument("--model", default="models/pose_landmarker_heavy.task", help="Model file path.")
    args = parser.parse_args()

    model_path = pathlib.Path(args.model).resolve()
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    base_options = python.BaseOptions(model_asset_path=str(model_path))
    options = vision.PoseLandmarkerOptions(base_options=base_options, running_mode=vision.RunningMode.VIDEO)
    detector = vision.PoseLandmarker.create_from_options(options)
    detector.close()

    print(f"numpy: {np.__version__}")
    print(f"opencv: {cv2.getVersionString()}")
    print(f"mediapipe: {mp.__version__}")
    print("PoseLandmarker initialization: OK")


if __name__ == "__main__":
    main()
