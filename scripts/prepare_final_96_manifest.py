"""Verify the final 96-clip archive and prepare the protocol manifest draft.

This command keeps the archive as private input, verifies every media hash, and
converts its confirmed capture manifest to the repository's CSV protocol shape.
It deliberately leaves event bounds, authorization ids, and VALIDITY blank;
those are human/audit fields required before P03 locking and must not be guessed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.three_participant_experiment import MANIFEST_FIELDS, write_csv, write_json


EXPECTED_PARTICIPANTS = {"P01": 32, "P02": 32, "P03": 32}
EXPECTED_ROLE_COUNTS = {"BASELINE": 24, "EVALUATION": 72}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def locate_root(archive: zipfile.ZipFile) -> str:
    manifests = [name for name in archive.namelist() if name.endswith("capture-manifest.json")]
    if len(manifests) != 1:
        raise ValueError("capture-manifest.json was not found uniquely")
    return manifests[0].rsplit("/", 1)[0]


def verify_archive(archive_path: Path) -> tuple[str, dict[str, Any], dict[str, str]]:
    with zipfile.ZipFile(archive_path) as archive:
        root = locate_root(archive)
        manifest_name = f"{root}/capture-manifest.json"
        manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
        if manifest.get("schema_version") != "three-participant-final-package/1.0":
            raise ValueError("FINAL_PACKAGE_SCHEMA_INVALID")
        records = manifest.get("records")
        if not isinstance(records, list) or len(records) != 96:
            raise ValueError("FINAL_PACKAGE_RECORD_COUNT_INVALID")
        if manifest.get("participant_counts") != EXPECTED_PARTICIPANTS:
            raise ValueError("FINAL_PACKAGE_PARTICIPANT_COUNTS_INVALID")
        if manifest.get("role_counts") != EXPECTED_ROLE_COUNTS:
            raise ValueError("FINAL_PACKAGE_ROLE_COUNTS_INVALID")
        expected_paths = {f"{root}/{record['package_relpath']}": record["sha256"] for record in records}
        video_names = {name for name in archive.namelist() if name.lower().endswith(".mp4")}
        if video_names != set(expected_paths):
            raise ValueError(f"FINAL_PACKAGE_MEDIA_SET_INVALID: missing={len(set(expected_paths)-video_names)} extra={len(video_names-set(expected_paths))}")
        bad = [name for name, expected in expected_paths.items() if sha256_bytes(archive.read(name)) != str(expected).lower()]
        if bad:
            raise ValueError(f"FINAL_PACKAGE_HASH_MISMATCH: {bad[0]}")
        return root, manifest, {name: sha256_bytes(archive.read(name)) for name in video_names}


def extract_archive(archive_path: Path, output_dir: Path) -> Path:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"refusing to overwrite non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(output_dir)
    roots = [path for path in output_dir.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise ValueError("extracted archive root is not unique")
    return roots[0]


def build_rows(root: Path, manifest: dict[str, Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in manifest["records"]:
        duration_ms = int(record["duration_ms"])
        golden = record["protocol_variant"] == "GOLDEN_115S"
        rows.append({
            "planned_slot_id": record["slot_id"],
            "clip_id": record["slot_id"],
            "participant_id": record["participant_id"],
            "capture_date": record["capture_date"],
            "scenario_id": record["scenario_id"],
            "record_role": record["record_role"],
            "repeat_index": record["repeat_index"],
            "protocol_variant": record["protocol_variant"],
            "ground_truth": record["ground_truth"],
            "event_start_ms": "",
            "event_end_ms": "",
            "lighting": "INDOOR",
            "camera_position_id": "C6c-pos01",
            "source_mode": "RECORDED_REPLAY",
            "simulated": "true",
            "authorization_record_id": "",
            "dataset_split": record["dataset_split"],
            "validity": "",
            "exclusion_reason": "",
            "video_relpath": record["package_relpath"],
            "sha256": record["sha256"],
            "planned_duration_seconds": 115 if golden else math.ceil(duration_ms / 1000),
            "notes": f"label_status={record.get('label_status', '')}; candidate_id={record.get('candidate_id', '')}",
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify final 96-clip archive and prepare capture-manifest.csv draft.")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve()
    output_dir = args.output_dir.resolve()
    try:
        root_name, manifest, media_hashes = verify_archive(archive)
        extracted_root = extract_archive(archive, output_dir / "archive")
        rows = build_rows(extracted_root, manifest)
        manifest_path = output_dir / "capture-manifest.csv"
        write_csv(manifest_path, MANIFEST_FIELDS, rows)
        verification = {
            "schema_version": "three-participant-final-package-verification/1.0",
            "status": "PASS",
            "archive": str(archive),
            "archive_sha256": sha256_file(archive),
            "archive_root": root_name,
            "record_count": len(rows),
            "video_count": len(media_hashes),
            "participant_counts": manifest["participant_counts"],
            "role_counts": manifest["role_counts"],
            "extracted_root": str(extracted_root),
            "capture_manifest": str(manifest_path),
            "event_bounds_status": "PENDING_HUMAN_CONFIRMATION",
            "authorization_status": "PENDING_HUMAN_CONFIRMATION",
            "validity_status": "PENDING_HUMAN_CONFIRMATION",
            "p03_lock_status": "NOT_READY",
        }
        write_json(output_dir / "archive-verification.json", verification)
        (output_dir / "README.md").write_text(
            "# 96段最终可用包导入结果\n\n"
            "已验证 96 段视频及 SHA-256，并生成 `capture-manifest.csv` 草稿。\n\n"
            "事件起止时间、授权编号和 VALID/ABORTED/EXCLUDED 状态仍为空，完成人工确认后才能运行 captured 校验和 P03 lock。\n",
            encoding="utf-8",
        )
        print(json.dumps(verification, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
