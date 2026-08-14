from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1]
ROOT = FRONTEND.parent
ARTIFACTS = FRONTEND / "artifacts" / "api-evidence"
DELIVERABLES = ROOT / "deliverables" / "frontend-api-2026-07-31"


def wait_for(url: str, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"service did not become ready: {url}")


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_videos() -> None:
    videos = sorted(ARTIFACTS.glob("run-*/screen-recording.webm"))
    if len(videos) != 3:
        raise RuntimeError(f"expected 3 recordings, found {len(videos)}")
    manifest = {
        "schema_version": "1.0",
        "data_mode": "api",
        "source_mode": "MOCK",
        "simulated": True,
        "real_device_claimed": False,
        "videos": [
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in videos
        ],
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    DELIVERABLES.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "video-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DELIVERABLES / "video-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = ARTIFACTS / "frontend-api-evidence-2026-07-31.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for path in videos:
            package.write(path, path.relative_to(ARTIFACTS))
        package.write(ARTIFACTS / "video-manifest.json", "video-manifest.json")
        for path in sorted(ARTIFACTS.glob("run-*/*")):
            if path.suffix.lower() not in {".json", ".png"}:
                continue
            package.write(path, path.relative_to(ARTIFACTS))
    print(f"API evidence package: {archive}")


def clean_generated_outputs() -> None:
    if ARTIFACTS.exists():
        shutil.rmtree(ARTIFACTS)
    if DELIVERABLES.exists():
        for run_directory in DELIVERABLES.glob("run-*"):
            if run_directory.is_dir() and run_directory.parent.resolve() == DELIVERABLES.resolve():
                shutil.rmtree(run_directory)


def main() -> None:
    clean_generated_outputs()
    env = os.environ.copy()
    env.update({
        "YINGMU_ENV": "mock",
        "MIN_EVIDENCE_QUALITY": "0.70",
        "MIN_EVIDENCE_CONFIDENCE": "0.70",
        "API_BASE_URL": "http://127.0.0.1:8010",
        "VITE_API_BASE_URL": "http://127.0.0.1:8010/api/v1",
        "VITE_DATA_MODE": "api",
        "VITE_RESIDENT_ID": "resident-frontend-api",
    })
    with tempfile.TemporaryDirectory(prefix="yingmu-frontend-api-") as temp_dir:
        env["YINGMU_DB_PATH"] = str(Path(temp_dir) / "frontend-api.db")
        backend = subprocess.Popen(
            [os.environ.get("PYTHON", "python"), "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8010"],
            cwd=ROOT,
            env=env,
        )
        try:
            wait_for("http://127.0.0.1:8010/health")
            npx = "npx.cmd" if os.name == "nt" else "npx"
            result = subprocess.run(
                [npx, "playwright", "test", "--config", "playwright.api.config.js"],
                cwd=FRONTEND,
                env=env,
                check=False,
            )
            if result.returncode:
                raise SystemExit(result.returncode)
        finally:
            stop_process(backend)
    package_videos()


if __name__ == "__main__":
    main()
