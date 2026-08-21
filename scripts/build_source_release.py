"""Build a privacy-safe, allowlisted source release ZIP."""

from __future__ import annotations

import argparse
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

from scripts.release_integrity import IGNORED_PARTS, scan_files, sha256_file


RECURSIVE_ROOTS = (
    "backend",
    "contracts",
    "deliverables/cym/audio-behavior-demo/src",
    "experiments/three-participant/templates",
    "final-delivery/docs",
    "final-delivery/video",
    "frontend/e2e",
    "frontend/public",
    "frontend/scripts",
    "frontend/src",
    "packaging",
    "scripts",
    "tests",
)
EXACT_FILES = (
    ".env.example",
    "LICENSE",
    "README.md",
    "pytest.ini",
    "experiments/three-participant/README.md",
    "final-delivery/README.md",
    "frontend/.env.example",
    "frontend/.gitignore",
    "frontend/README.md",
    "frontend/index.html",
    "frontend/package-lock.json",
    "frontend/package.json",
    "frontend/playwright.api.config.js",
    "frontend/playwright.config.js",
    "frontend/vite.config.js",
    "models/pose_landmarker_heavy.task",
)


def _include_file(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts & {part.lower() for part in IGNORED_PARTS}:
        return False
    if path.name == ".env":
        return False
    return path.suffix.lower() not in {".db", ".pyc", ".tmp"}


def collect_source_files(root: Path) -> list[tuple[Path, str]]:
    selected: dict[str, Path] = {}
    for relative in EXACT_FILES:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"required source release file is missing: {relative}")
        selected[Path(relative).as_posix()] = path
    for relative in RECURSIVE_ROOTS:
        directory = root / relative
        if not directory.is_dir():
            raise ValueError(f"required source release directory is missing: {relative}")
        for path in directory.rglob("*"):
            if path.is_file() and _include_file(path.relative_to(root)):
                selected[path.relative_to(root).as_posix()] = path
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
