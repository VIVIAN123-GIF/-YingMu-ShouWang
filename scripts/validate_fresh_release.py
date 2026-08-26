"""Validate source and Windows release ZIPs from clean extraction roots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from scripts.release_integrity import scan_zip


SOURCE_REQUIRED = (
    "adapters/trajectory_adapter.py",
    "backend/schemas/risk_review.py",
    "backend/service/stream_buffer_service.py",
    "backend/worker/stream_buffer_worker.py",
    "scene-calibrations/scene-living-room-v1.json",
    "scene-calibrations/scene-recorded-demo-v1.json",
    "scripts/check_stream_buffer.py",
)
WINDOWS_REQUIRED = (
    "YingMuShouWang.exe",
    "config/.env.example",
    "models/pose_landmarker_heavy.task",
    "scene-calibrations/scene-living-room-v1.json",
    "scene-calibrations/scene-recorded-demo-v1.json",
)
CONFIG_REQUIRED_KEYS = (
    "YINGMU_CAPTURE_MEDIA_MODE",
    "YINGMU_GAIT_ADAPTER",
    "YINGMU_TRAJECTORY_ADAPTER",
    "YINGMU_SCENE_CONFIG_ID",
    "YINGMU_SCENE_CONFIG_DIR",
    "YINGMU_STREAM_BUFFER_ENABLED",
    "YINGMU_STREAM_BUFFER_ROOT",
    "EZVIZ_LIVE_PLAYBACK_VERIFIED",
    "EZVIZ_VOICE_VERIFIED",
)


class FreshReleaseError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--windows-zip", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--npm", default="npm")
    parser.add_argument("--negative-input", type=Path)
    parser.add_argument("--negative-captured-at")
    parser.add_argument("--retention-until")
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for item in archive.infolist():
        target = (root / item.filename).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise FreshReleaseError("release ZIP contains an unsafe path") from exc
    archive.extractall(root)


def _verify_manifest(root: Path) -> int:
    manifests = list(root.rglob("MANIFEST-SHA256.txt"))
    if len(manifests) != 1:
        raise FreshReleaseError("release must contain exactly one MANIFEST-SHA256.txt")
    manifest = manifests[0]
    content_root = manifest.parent
    checked = 0
    for line in manifest.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as exc:
            raise FreshReleaseError("release manifest line is invalid") from exc
        path = (content_root / relative).resolve()
        try:
            path.relative_to(content_root.resolve())
        except ValueError as exc:
            raise FreshReleaseError("release manifest contains an unsafe path") from exc
        if not path.is_file() or _sha256(path) != expected.lower():
            raise FreshReleaseError("release manifest verification failed")
        checked += 1
    if checked == 0:
        raise FreshReleaseError("release manifest is empty")
    return checked


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    if completed.returncode != 0:
        raise FreshReleaseError(f"fresh command failed with exit code {completed.returncode}")


def _resolve_npm(command: str) -> str:
    candidates = [command]
    if sys.platform == "win32" and Path(command).suffix == "":
        candidates.insert(0, f"{command}.cmd")
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise FreshReleaseError(f"npm executable was not found: {command}")


def _source_root(extracted: Path) -> Path:
    candidates = [path.parent for path in extracted.rglob("SOURCE-RELEASE.json")]
    if len(candidates) != 1:
        raise FreshReleaseError("source ZIP root could not be identified")
    return candidates[0]


def _windows_root(extracted: Path) -> Path:
    candidates = [path.parent for path in extracted.rglob("YingMuShouWang.exe")]
    if len(candidates) != 1:
        raise FreshReleaseError("Windows ZIP root could not be identified")
    return candidates[0]


def _assert_files(root: Path, required: tuple[str, ...]) -> None:
    missing = [relative for relative in required if not (root / relative).is_file()]
    if missing:
        raise FreshReleaseError(f"release is missing required files: {', '.join(missing)}")


def _negative_runtime_root(extracted_source: Path) -> Path:
    return extracted_source.parent / "negative-runtime"


def validate_source(args: argparse.Namespace, extracted: Path) -> dict[str, Any]:
    with zipfile.ZipFile(args.source_zip) as archive:
        _safe_extract(archive, extracted)
    manifest_count = _verify_manifest(extracted)
    root = _source_root(extracted)
    _assert_files(root, SOURCE_REQUIRED)
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)
    import_probe = (
        "from pathlib import Path; "
        "root=Path.cwd().resolve(); "
        "import adapters.trajectory_adapter as a; "
        "import backend.schemas.risk_review as r; "
        "import backend.service.stream_buffer_service as s; "
        "assert Path(a.__file__).resolve().is_relative_to(root); "
        "assert Path(r.__file__).resolve().is_relative_to(root); "
        "assert Path(s.__file__).resolve().is_relative_to(root)"
    )
    _run([str(args.python), "-c", import_probe], cwd=root, env=clean_env)
    _run([str(args.python), "-m", "pytest", "-q"], cwd=root, env=clean_env)
    frontend = root / "frontend"
    npm = _resolve_npm(args.npm)
    _run([npm, "ci"], cwd=frontend, env=clean_env)
    _run([npm, "test", "--", "--run"], cwd=frontend, env=clean_env)
    _run([npm, "run", "build"], cwd=frontend, env=clean_env)

    negative_replay = "NOT_REQUESTED"
    negative_args = (args.negative_input, args.negative_captured_at, args.retention_until)
    if any(value is not None for value in negative_args):
        if any(value is None for value in negative_args):
            raise FreshReleaseError(
                "negative-input, negative-captured-at, and retention-until must be supplied together"
            )
        replay_runtime = _negative_runtime_root(extracted)
        replay_runtime.mkdir(parents=True, exist_ok=True)
        replay_root = replay_runtime / "private"
        replay_db = replay_runtime / "negative.db"
        replay_report = replay_runtime / "negative-report.json"
        _run([
            str(args.python),
            "scripts/run_v13_closed_loop_acceptance.py",
            "--expected-outcome", "NO_EVENT",
            "--input", str(args.negative_input.resolve()),
            "--database", str(replay_db),
            "--private-root", str(replay_root),
            "--captured-at", args.negative_captured_at,
            "--retention-until", args.retention_until,
            "--report", str(replay_report),
        ], cwd=root, env=clean_env)
        negative_replay = "PASS"
    return {
        "status": "PASS",
        "manifest_files": manifest_count,
        "imports_from_extracted_root": True,
        "python_tests": "PASS",
        "frontend_tests_and_build": "PASS",
        "negative_replay": negative_replay,
    }


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def validate_windows(args: argparse.Namespace, extracted: Path) -> dict[str, Any]:
    with zipfile.ZipFile(args.windows_zip) as archive:
        _safe_extract(archive, extracted)
    manifest_count = _verify_manifest(extracted)
    root = _windows_root(extracted)
    _assert_files(root, WINDOWS_REQUIRED)
    config_text = (root / "config" / ".env.example").read_text(encoding="utf-8-sig")
    missing_keys = [key for key in CONFIG_REQUIRED_KEYS if f"{key}=" not in config_text]
    if missing_keys:
        raise FreshReleaseError(f"packaged config template is missing keys: {', '.join(missing_keys)}")
    executable = root / "YingMuShouWang.exe"
    _run([str(executable), "self-check"], cwd=root)
    runtime = extracted / "windows-runtime"
    port = _free_port()
    _run([
        str(executable), "demo", "--host", "127.0.0.1", "--port", str(port),
        "--runtime-dir", str(runtime), "--no-browser", "--smoke-test",
    ], cwd=root)
    database = runtime / "demo.db"
    if not database.is_file():
        raise FreshReleaseError("packaged demo did not create its isolated database")
    with sqlite3.connect(database) as connection:
        statuses = [row[0] for row in connection.execute("SELECT status FROM risk_event")]
    if statuses != ["RESOLVED"]:
        raise FreshReleaseError("packaged demo did not finish with one RESOLVED event")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise FreshReleaseError("packaged demo left a process listening on its port") from exc
    return {
        "status": "PASS",
        "manifest_files": manifest_count,
        "self_check": "PASS",
        "demo_final_status": "RESOLVED",
        "residual_listener": False,
    }


def main() -> int:
    args = parse_args()
    report: dict[str, Any] = {
        "schema_version": "fresh-release-validation/1.0",
        "privacy_scan": "PASS",
        "source": None,
        "windows": None,
        "status": "FAIL",
    }
    diagnostic_root = Path(tempfile.mkdtemp(prefix="yingmu-fresh-release-"))
    passed = False
    try:
        for archive in (args.source_zip, args.windows_zip):
            if not archive.is_file():
                raise FreshReleaseError("release ZIP does not exist")
            findings = scan_zip(archive)
            if findings:
                raise FreshReleaseError("release ZIP failed privacy scanning")
        report["source"] = validate_source(args, diagnostic_root / "source")
        report["windows"] = validate_windows(args, diagnostic_root / "windows")
        report["status"] = "PASS"
        passed = True
        return_code = 0
    except (FreshReleaseError, OSError, ValueError, zipfile.BadZipFile) as exc:
        report["error"] = str(exc)
        report["diagnostics_retained"] = True
        return_code = 1
    finally:
        if passed:
            shutil.rmtree(diagnostic_root)
            report["diagnostics_retained"] = False
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
