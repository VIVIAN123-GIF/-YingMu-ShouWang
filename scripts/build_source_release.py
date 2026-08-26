"""Build a privacy-safe, allowlisted source release ZIP."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

from scripts.release_integrity import IGNORED_PARTS, scan_files, sha256_file


RECURSIVE_ROOTS = (
    ".github/workflows",
    "adapters",
    "backend",
    "contracts",
    "deliverables/cym/audio-behavior-demo/src",
    "deliverables/zy/pose-demo/scripts",
    "deliverables/zhang-d2-snapshot-2026-08-15/batch-1",
    "experiments/structured_scenarios",
    "experiments/three-participant/templates",
    "final-delivery/docs",
    "final-delivery/official-docs",
    "final-delivery/video",
    "frontend/e2e",
    "frontend/e2e-pages",
    "frontend/contracts",
    "frontend/public",
    "frontend/scripts",
    "frontend/src",
    "packaging",
    "scene-calibrations",
    "scripts",
    "tests",
)
REQUIRED_RELEASE_PATHS = (
    "adapters/trajectory_adapter.py",
    "backend/schemas/risk_review.py",
    "backend/service/stream_buffer_service.py",
    "backend/worker/stream_buffer_worker.py",
    "deliverables/zy/pose-demo/scripts/build_provisional_baseline_package.py",
    "deliverables/zy/pose-demo/scripts/download_pose_model.py",
    "deliverables/zy/pose-demo/scripts/recorded_replay_adapter.py",
    "deliverables/zy/pose-demo/scripts/submit_golden_package.py",
    "experiments/structured_scenarios/scenarios.py",
    "frontend/contracts/v1/examples/four-objects.json",
    "deliverables/zhang-d2-snapshot-2026-08-15/batch-1/ezviz-live-validation-run-1.json",
    "deliverables/zhang-d3-agent-llm/ezviz-qwen-live-validation-final.json",
    "deliverables/zhang-d3-agent-llm/ezviz-qwen-live-validation-timeout-15.json",
    "scene-calibrations/scene-living-room-v1.json",
    "scene-calibrations/scene-recorded-demo-v1.json",
    "scripts/check_stream_buffer.py",
)
EXACT_FILES = (
    ".env.example",
    "LICENSE",
    "README.md",
    "pytest.ini",
    "experiments/three-participant/README.md",
    "final-delivery/README.md",
    "final-delivery/online-entry-verification.template.json",
    "final-delivery/submission-documents.json",
    "final-delivery/submission-profile.example.json",
    "frontend/.env.pages",
    "frontend/.env.example",
    "frontend/.gitignore",
    "frontend/README.md",
    "frontend/index.html",
    "frontend/package-lock.json",
    "frontend/package.json",
    "frontend/playwright.api.config.js",
    "frontend/playwright.config.js",
    "frontend/playwright.pages.config.js",
    "frontend/vite.config.js",
    "models/pose_landmarker_heavy.task",
    "deliverables/zhang-d3-agent-llm/ezviz-qwen-live-validation-final.json",
    "deliverables/zhang-d3-agent-llm/ezviz-qwen-live-validation-timeout-15.json",
)
PINNED_EXTERNAL_FILES = {
    "models/pose_landmarker_heavy.task": (
        "64437af838a65d18e5ba7a0d39b465540069bc8aae8308de3e318aad31fcbc7b"
    ),
}


def _include_file(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts & {part.lower() for part in IGNORED_PARTS}:
        return False
    if path.name == ".env":
        return False
    return path.suffix.lower() not in {".db", ".pyc", ".tmp"}


def _tracked_paths(root: Path) -> set[str] | None:
    if not (root / ".git").exists():
        return None
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "-z"],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ValueError("unable to read the Git index for source release")
    return {
        item.decode("utf-8").replace("\\", "/")
        for item in completed.stdout.split(b"\0")
        if item
    }


def collect_source_files(root: Path) -> list[tuple[Path, str]]:
    tracked = _tracked_paths(root)
    selected: dict[str, Path] = {}
    for relative in EXACT_FILES:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"required source release file is missing: {relative}")
        relative_name = Path(relative).as_posix()
        expected_hash = PINNED_EXTERNAL_FILES.get(relative_name)
        if expected_hash is not None and sha256_file(path) != expected_hash:
            raise ValueError(f"pinned external release file checksum mismatch: {relative}")
        if tracked is not None and relative_name not in tracked and expected_hash is None:
            raise ValueError(f"required source release file is not tracked by Git: {relative}")
        selected[relative_name] = path
    for relative in RECURSIVE_ROOTS:
        directory = root / relative
        if not directory.is_dir():
            raise ValueError(f"required source release directory is missing: {relative}")
        for path in directory.rglob("*"):
            relative_path = path.relative_to(root)
            relative_name = relative_path.as_posix()
            if (
                path.is_file()
                and _include_file(relative_path)
                and (tracked is None or relative_name in tracked)
            ):
                selected[relative_name] = path
    missing = [relative for relative in REQUIRED_RELEASE_PATHS if relative not in selected]
    if missing:
        raise ValueError(f"required source release file is missing: {', '.join(missing)}")
    return [(selected[name], name) for name in sorted(selected)]


def build_source_release(root: Path, output: Path) -> dict[str, object]:
    root = root.resolve()
    files = collect_source_files(root)
    findings = scan_files(files)
    if findings:
        details = "\n".join(f"- {item.path}: {item.kind} ({item.detail})" for item in findings)
        raise ValueError(f"source release privacy scan failed:\n{details}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    manifest = [f"{sha256_file(path)}  {name}" for path, name in files]
    metadata = {
        "schema_version": "yingmu-source-release/1.0",
        "status": "COMPLETE",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "file_count": len(files),
        "privacy_scan": "PASS",
        "includes_private_data": False,
    }
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path, name in files:
                archive.write(path, name)
            archive.writestr("SOURCE-RELEASE.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
            archive.writestr("MANIFEST-SHA256.txt", "\n".join(manifest) + "\n")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {**metadata, "output": str(output), "sha256": sha256_file(output)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("output/source/萤目守望-Source.zip"))
    args = parser.parse_args()
    try:
        result = build_source_release(args.root, args.output)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
