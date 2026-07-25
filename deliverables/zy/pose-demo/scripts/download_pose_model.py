from __future__ import annotations

import argparse
import hashlib
import pathlib
import ssl
import urllib.request


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task"
)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(url: str, destination: pathlib.Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(url, context=context) as response, destination.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the official MediaPipe pose landmarker model.")
    parser.add_argument("--output", default="models/pose_landmarker_heavy.task", help="Target model path.")
    args = parser.parse_args()

    output_path = pathlib.Path(args.output).resolve()
    download_file(MODEL_URL, output_path)
    print(f"Downloaded model to: {output_path}")
    print(f"SHA256: {sha256_file(output_path)}")


if __name__ == "__main__":
    main()
