from __future__ import annotations

import argparse
import hashlib
import pathlib
import urllib.request


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task"
)
EXPECTED_SHA256 = "64437af838a65d18e5ba7a0d39b465540069bc8aae8308de3e318aad31fcbc7b"


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(url: str, destination: pathlib.Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "YingMu-ShouWang/1.0"})
    # urllib uses the platform trust store and verifies TLS certificates by default.
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
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
    partial_path = output_path.with_name(f"{output_path.name}.part")
    partial_path.unlink(missing_ok=True)
    try:
        download_file(MODEL_URL, partial_path)
        actual_hash = sha256_file(partial_path)
        if actual_hash != EXPECTED_SHA256:
            raise RuntimeError(f"Downloaded model checksum mismatch: {actual_hash}")
        partial_path.replace(output_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
    print(f"Downloaded model to: {output_path}")
    print(f"SHA256: {EXPECTED_SHA256}")


if __name__ == "__main__":
    main()
