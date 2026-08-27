from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path


BASELINE_SELECTIONS = {
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
        ("BASE_NORMAL_WALK_L2R", "P02-DAY1-002"),
        ("BASE_NORMAL_WALK_L2R", "P02-DAY1-003"),
        ("BASE_NORMAL_WALK_R2L", "P02-DAY1-008"),
        ("BASE_NORMAL_WALK_R2L", "P02-DAY2-022"),
        ("BASE_SIT_RISE_STABLE", "P02-DAY1-004"),
        ("BASE_SIT_RISE_STABLE", "P02-DAY1-005"),
        ("BASE_WALK_STOP_TURN", "P02-DAY1-006"),
        ("BASE_WALK_STOP_TURN", "P02-DAY1-007"),
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

EVALUATION_GROUPS = [
    "POS_RAPID_RISE_SWAY",
    "POS_SLOW_SMALL_STEP_SWAY",
    "POS_ASYMMETRIC_STEP",
    "NEG_NORMAL_RISE_WALK",
    "NEG_RAPID_RISE_STABLE",
    "NEG_BOUNDARY_NORMAL",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluation_selections(participant: str) -> list[tuple[str, str]]:
    candidates = [f"{participant}-DAY2-{index:03d}" for index in range(1, 25)]
    if participant == "P02":
        candidates = [f"P02-DAY2-{index:03d}" for index in range(1, 22)]
        candidates.extend(["P02-DAY2-023", "P02-DAY2-024", "P02-DAY2-025"])
    selections: list[tuple[str, str]] = []
    for group_index, scenario in enumerate(EVALUATION_GROUPS):
        start = group_index * 4
        for candidate in candidates[start : start + 4]:
            selections.append((scenario, candidate))
    return selections


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    audit = repo / "outputs" / "three-participant-review-20260825-full"
    desktop = Path(r"D:\OneDrive\Desktop")
    package_root = desktop / "3人96段-调整版"
    zip_path = desktop / "3人96段-调整版.zip"
    if package_root.exists() or zip_path.exists():
        raise SystemExit("Output already exists; refusing to overwrite it.")

    with (audit / "video-confirmation.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        candidates = {row["candidate_id"]: row for row in csv.DictReader(handle)}

    records: list[dict[str, object]] = []
    used_candidates: set[str] = set()
    repeat_counts: dict[tuple[str, str], int] = {}
    for participant in ("P01", "P02", "P03"):
        planned = [("BASELINE", scenario, candidate) for scenario, candidate in BASELINE_SELECTIONS[participant]]
        planned.extend(("EVALUATION", scenario, candidate) for scenario, candidate in evaluation_selections(participant))
        if len(planned) != 32:
            raise RuntimeError(f"{participant} selection count is {len(planned)}, expected 32")
        for role, scenario, candidate_id in planned:
            if candidate_id in used_candidates:
                raise RuntimeError(f"Candidate reused: {candidate_id}")
            used_candidates.add(candidate_id)
            source = candidates[candidate_id]
            repeat_key = (participant, scenario)
            repeat_counts[repeat_key] = repeat_counts.get(repeat_key, 0) + 1
            repeat_index = repeat_counts[repeat_key]
            slot_id = f"{participant}-{scenario}-{repeat_index:02d}"
            batch_dir = "day1_baseline" if role == "BASELINE" else "day2_evaluation"
            destination = package_root / participant / batch_dir / f"{slot_id}.mp4"
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
                    "record_role": role,
                    "scenario_id": scenario,
                    "repeat_index": repeat_index,
                    "ground_truth": "RISK_PRECURSOR" if scenario.startswith("POS_") else "NORMAL_CONTROL",
                    "candidate_id": candidate_id,
                    "capture_date": source["capture_date"],
                    "duration_ms": int(source["duration_ms"]),
                    "source_original_relpath": source["original_relpath"],
                    "package_relpath": destination.relative_to(package_root).as_posix(),
                    "sha256": copied_hash,
                    "label_status": "PROVISIONAL_VISUAL_INFERENCE",
                    "protocol_deviation": candidate_id == "P02-DAY2-022",
                }
            )

    if len(records) != 96 or len(used_candidates) != 96:
        raise RuntimeError("Package must contain 96 unique selected candidates")

    manifest = {
        "schema_version": "three-participant-adjusted-package/1.0",
        "status": "96_UNIQUE_CLIPS_WITH_DECLARED_PROTOCOL_DEVIATION",
        "created_from": str(audit),
        "video_count": len(records),
        "participant_counts": {participant: sum(r["participant_id"] == participant for r in records) for participant in ("P01", "P02", "P03")},
        "protocol_deviations": [
            "P02只有7段本人第一日基线候选。为保持每人32段且不复制同一视频，P02-DAY2-022被归入BASE_NORMAL_WALK_R2L-02。",
            "P02-DAY2-022拍摄于2026-08-25，晚于P02原第一日基线，且来自第二天批次；P02不再满足严格的完整基线先于评测要求。",
            "P02第二天正式边界场景采用DAY2-021、023、024、025；DAY2-022不再计入评测。",
            "场景标签依据拍摄顺序、时长和画面动作推断，尚需拍摄人员确认。",
        ],
        "records": records,
    }
    (package_root / "selection-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    hash_lines = [f'{record["sha256"]}  {record["package_relpath"]}' for record in records]
    (package_root / "SHA256SUMS.txt").write_text("\n".join(hash_lines) + "\n", encoding="utf-8")
    (package_root / "README-重要说明.md").write_text(
        """# 3人96段调整版

本包包含96个不同的原始视频片段：P01、P02、P03各8段基线和24段评测。原始压缩包未被修改。

## 必须声明的协议偏差

P02实际只有7段本人第一日基线。由于时间不足，本包将P02-DAY2-022作为P02的第二段右向左正常行走基线，并使用多拍的P02-DAY2-025补足第二天边界场景。因此文件数量达到96且没有重复使用视频，但P02不满足严格的完整基线先于评测要求。研究报告和测试报告必须如实声明，不能写成严格完成预定协议。

场景标签由拍摄顺序、视频时长和画面动作推断。完成拍摄人员确认前，标签状态为PROVISIONAL_VISUAL_INFERENCE。P03尚未运行风险识别算法。

`selection-manifest.json`记录正式槽位、原始路径、候选编号和SHA-256；`SHA256SUMS.txt`用于校验96段视频。
""",
        encoding="utf-8",
    )

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(path, Path(package_root.name) / path.relative_to(package_root))
    print(json.dumps({"package_dir": str(package_root), "zip": str(zip_path), "videos": 96, "zip_sha256": sha256(zip_path)}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
