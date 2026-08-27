from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from pathlib import Path


SELECTIONS = {
    "P01": [
        ("BASE_NORMAL_WALK_L2R", "P01-DAY1-008"),
        ("BASE_NORMAL_WALK_L2R", "P01-DAY1-009"),
        ("BASE_NORMAL_WALK_R2L", "P01-DAY1-002"),
        ("BASE_NORMAL_WALK_R2L", "P01-DAY1-003"),
        ("BASE_SIT_RISE_STABLE", "P01-DAY1-011"),
        ("BASE_SIT_RISE_STABLE", "P01-DAY1-012"),
        ("BASE_WALK_STOP_TURN", "P01-DAY1-001"),
        ("BASE_WALK_STOP_TURN", "P01-DAY1-014"),
    ],
    "P02": [
        ("BASE_NORMAL_WALK_L2R", "P02-DAY1-001"),
        ("BASE_NORMAL_WALK_L2R", "P02-DAY1-002"),
        ("BASE_NORMAL_WALK_R2L", "P02-DAY1-003"),
        ("BASE_NORMAL_WALK_R2L", "P02-DAY1-004"),
        ("BASE_SIT_RISE_STABLE", "P02-DAY1-005"),
        ("BASE_SIT_RISE_STABLE", "P02-DAY1-006"),
        ("BASE_WALK_STOP_TURN", "P02-DAY1-007"),
        ("BASE_WALK_STOP_TURN", "P02-DAY1-008"),
    ],
    "P03": [
        ("BASE_NORMAL_WALK_L2R", "P03-DAY1-004"),
        ("BASE_NORMAL_WALK_L2R", "P03-DAY1-005"),
        ("BASE_NORMAL_WALK_R2L", "P03-DAY1-001"),
        ("BASE_NORMAL_WALK_R2L", "P03-DAY1-002"),
        ("BASE_SIT_RISE_STABLE", "P03-DAY1-008"),
        ("BASE_SIT_RISE_STABLE", "P03-DAY1-009"),
        ("BASE_WALK_STOP_TURN", "P03-DAY1-006"),
        ("BASE_WALK_STOP_TURN", "P03-DAY1-012"),
    ],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    audit = repo / "outputs" / "three-participant-review-20260826-final"
    desktop = Path(r"D:\OneDrive\Desktop")
    package_root = desktop / "3人个人基线-最终版"
    zip_path = desktop / "3人个人基线-最终版.zip"
    if package_root.exists() or zip_path.exists():
        raise SystemExit("Output already exists; refusing to overwrite it.")

    with (audit / "video-confirmation.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        candidates = {row["candidate_id"]: row for row in csv.DictReader(handle)}

    records: list[dict[str, object]] = []
    for participant in ("P01", "P02", "P03"):
        if len(SELECTIONS[participant]) != 8:
            raise RuntimeError(f"{participant} does not have 8 baseline selections")
        counts: dict[str, int] = {}
        for scenario, candidate_id in SELECTIONS[participant]:
            if candidate_id not in candidates:
                raise RuntimeError(f"Missing candidate {candidate_id}")
            source = candidates[candidate_id]
            counts[scenario] = counts.get(scenario, 0) + 1
            slot_id = f"{participant}-{scenario}-{counts[scenario]:02d}"
            destination = package_root / participant / "day1_baseline" / f"{slot_id}.mp4"
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_path = audit / source["normalized_relpath"]
            shutil.copy2(source_path, destination)
            copied_hash = sha256(destination)
            if copied_hash.lower() != source["sha256"].lower():
                raise RuntimeError(f"Hash mismatch after copy: {candidate_id}")
            records.append(
                {
                    "slot_id": slot_id,
                    "participant_id": participant,
                    "scenario_id": scenario,
                    "record_role": "BASELINE",
                    "ground_truth": "NORMAL_CONTROL",
                    "candidate_id": candidate_id,
                    "capture_date": source["capture_date"],
                    "duration_ms": int(source["duration_ms"]),
                    "source_original_relpath": source["original_relpath"],
                    "package_relpath": destination.relative_to(package_root).as_posix(),
                    "sha256": copied_hash,
                    "dataset_split": {"P01": "CALIBRATION", "P02": "VALIDATION", "P03": "TEST"}[participant],
                    "label_status": "PROVISIONAL_VISUAL_INFERENCE",
                }
            )

    if len(records) != 24 or len({record["candidate_id"] for record in records}) != 24:
        raise RuntimeError("Baseline package must contain 24 unique clips")

    manifest = {
        "schema_version": "three-participant-personal-baseline-package/1.0",
        "status": "READY_FOR_BASELINE_BUILD_AFTER_SCENARIO_CONFIRMATION",
        "created_from": str(audit),
        "video_count": len(records),
        "participant_counts": {participant: sum(r["participant_id"] == participant for r in records) for participant in ("P01", "P02", "P03")},
        "records": records,
        "notes": [
            "本包只用于建立三名参与者的个人基线，不包含第二天评测视频。",
            "P01/P02/P03分别对应CALIBRATION/VALIDATION/TEST；参与者不得混合。",
            "场景编号依据拍摄顺序和画面动作整理，正式建模前应由拍摄人员确认。",
            "文件系统时间可能受压缩、复制影响；研究报告中的capture_date应以相机画面时间或拍摄台账为准。",
        ],
    }
    (package_root / "baseline-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (package_root / "SHA256SUMS.txt").write_text(
        "\n".join(f'{record["sha256"]}  {record["package_relpath"]}' for record in records) + "\n",
        encoding="utf-8",
    )
    (package_root / "README-使用说明.md").write_text(
        """# 三参与者个人基线最终包

本包包含P01、P02、P03各8段第一天正式基线，共24段。用于建立个人步态、起身、躯干姿态和质量阈值基线，不用于直接计算第二天场景的Precision、Recall或F1。

目录中的视频均为原始候选的规范副本，原始压缩包未被修改。`baseline-manifest.json`记录参与者、场景、原始路径和数据集分组；`SHA256SUMS.txt`用于完整性校验。

正式建模前，请确认每个参与者的8段是否按四类场景各2段，以及capture_date是否以相机画面时间为准。P01、P02、P03必须分别隔离建立基线，不能混合计算统一个人阈值。
""",
        encoding="utf-8",
    )

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(path, Path(package_root.name) / path.relative_to(package_root))
    print(json.dumps({"package_dir": str(package_root), "zip": str(zip_path), "videos": 24, "zip_sha256": sha256(zip_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
