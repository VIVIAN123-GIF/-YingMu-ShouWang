from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from build_personal_baseline_package import SELECTIONS as BASELINE_SELECTIONS


EVALUATION_GROUPS = (
    "POS_RAPID_RISE_SWAY",
    "POS_SLOW_SMALL_STEP_SWAY",
    "POS_ASYMMETRIC_STEP",
    "NEG_NORMAL_RISE_WALK",
    "NEG_RAPID_RISE_STABLE",
    "NEG_BOUNDARY_NORMAL",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluation_selections(participant: str) -> list[tuple[str, str]]:
    if participant != "P02":
        candidate_ids = [f"{participant}-DAY2-{index:03d}" for index in range(1, 25)]
        return [
            (EVALUATION_GROUPS[index // 4], candidate_id)
            for index, candidate_id in enumerate(candidate_ids)
        ]

    selections: list[tuple[str, str]] = []
    for group_index, scenario in enumerate(EVALUATION_GROUPS[:5]):
        for index in range(group_index * 4 + 1, group_index * 4 + 5):
            selections.append((scenario, f"P02-DAY2-{index:03d}"))
    # Confirmed by the capture team: 021=occlusion, 022=exit frame,
    # 024=turn, 025=stop. 023 is an extra asymmetric-step take.
    selections.extend(
        ("NEG_BOUNDARY_NORMAL", candidate_id)
        for candidate_id in ("P02-DAY2-021", "P02-DAY2-022", "P02-DAY2-024", "P02-DAY2-025")
    )
    return selections


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    audit = repo / "outputs" / "three-participant-review-20260826-final"
    desktop = Path(r"D:\OneDrive\Desktop")
    package_root = desktop / "3人96段-最终可用版"
    zip_path = desktop / "3人96段-最终可用版.zip"
    if package_root.exists() or zip_path.exists():
        raise SystemExit("Output already exists; refusing to overwrite it.")

    with (audit / "video-confirmation.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        candidates = {row["candidate_id"]: row for row in csv.DictReader(handle)}

    records: list[dict[str, object]] = []
    used: set[str] = set()
    split_by_participant = {"P01": "CALIBRATION", "P02": "VALIDATION", "P03": "TEST"}
    for participant in ("P01", "P02", "P03"):
        selected = [("BASELINE", scenario, candidate) for scenario, candidate in BASELINE_SELECTIONS[participant]]
        selected.extend(("EVALUATION", scenario, candidate) for scenario, candidate in evaluation_selections(participant))
        if len(selected) != 32:
            raise RuntimeError(f"{participant} has {len(selected)} selections")
        repeat_counts: dict[str, int] = {}
        for role, scenario, candidate_id in selected:
            if candidate_id in used:
                raise RuntimeError(f"Candidate reused: {candidate_id}")
            used.add(candidate_id)
            source = candidates[candidate_id]
            repeat_counts[scenario] = repeat_counts.get(scenario, 0) + 1
            repeat_index = repeat_counts[scenario]
            slot_id = f"{participant}-{scenario}-{repeat_index:02d}"
            day_dir = "day1_baseline" if role == "BASELINE" else "day2_evaluation"
            destination = package_root / participant / day_dir / f"{slot_id}.mp4"
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_path = audit / source["normalized_relpath"]
            shutil.copy2(source_path, destination)
            copied_hash = sha256(destination)
            if copied_hash.lower() != source["sha256"].lower():
                raise RuntimeError(f"Hash mismatch: {candidate_id}")
            records.append(
                {
                    "slot_id": slot_id,
                    "participant_id": participant,
                    "record_role": role,
                    "scenario_id": scenario,
                    "repeat_index": repeat_index,
                    "protocol_variant": "GOLDEN_115S" if scenario == "POS_RAPID_RISE_SWAY" and repeat_index == 1 else "STANDARD",
                    "ground_truth": "RISK_PRECURSOR" if scenario.startswith("POS_") else "NORMAL_CONTROL",
                    "dataset_split": split_by_participant[participant],
                    "candidate_id": candidate_id,
                    "capture_date": source["capture_date"],
                    "duration_ms": int(source["duration_ms"]),
                    "source_original_relpath": source["original_relpath"],
                    "package_relpath": destination.relative_to(package_root).as_posix(),
                    "sha256": copied_hash,
                    "label_status": "CONFIRMED_ORDER_AND_VISUAL_REVIEW",
                }
            )

    if len(records) != 96 or len(used) != 96:
        raise RuntimeError("Final package must contain 96 unique videos")

    manifest = {
        "schema_version": "three-participant-final-package/1.0",
        "status": "READY_FOR_SPLIT_PROCESSING",
        "video_count": 96,
        "participant_counts": {p: sum(r["participant_id"] == p for r in records) for p in ("P01", "P02", "P03")},
        "role_counts": {
            "BASELINE": sum(r["record_role"] == "BASELINE" for r in records),
            "EVALUATION": sum(r["record_role"] == "EVALUATION" for r in records),
        },
        "excluded_candidates": [
            {
                "candidate_id": "P02-DAY2-023",
                "original_filename": "776ce73e5104d9782bc0f7bf1f0096e8.mp4",
                "reason": "EXTRA_POS_ASYMMETRIC_STEP; P02 already has four planned asymmetric-step clips",
            }
        ],
        "capture_confirmations": [
            "80aedc9b0c487f5b18133f714c597634.mp4 is planned short occlusion",
            "1aa5f8b341c9af65b35957f478e8cd29.mp4 is normal turn",
            "4f1e0dcc8bea2b014e72b38ae784969d.mp4 is normal stop and a repeat take; retained as the fourth boundary clip",
            "8341b01bf5b474e3fa093ee5a0c0932d.mp4 was confirmed as walk-stop-turn in the earlier source package; the updated P02 baseline directory replaces that package",
        ],
        "records": records,
    }
    (package_root / "capture-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (package_root / "SHA256SUMS.txt").write_text(
        "\n".join(f'{record["sha256"]}  {record["package_relpath"]}' for record in records) + "\n",
        encoding="utf-8",
    )
    (package_root / "README-使用说明.md").write_text(
        """# 三参与者96段最终可用包

本包包含P01、P02、P03各8段个人基线和24段第二天评测，共96段且无视频复用。

- P01：CALIBRATION，用于校准。
- P02：VALIDATION，用于验证。
- P03：TEST，用于最终独立测试。

运行顺序必须是P01、P02、冻结规则、最后一次性运行P03。P03不是与P01/P02混合计算的普通评测集；最终Precision、Recall、F1和混淆矩阵只以P03的24段评测为准。

P02第二天多出的`776ce73e5104d9782bc0f7bf1f0096e8.mp4`经拍摄人员确认是额外的单侧步幅缩短片段，本包未选用。`4f1e0dcc8bea2b014e72b38ae784969d.mp4`虽然是重复补拍，但其动作是正常停步，本包将它作为第四段边界场景；每个正式文件仍对应不同的原始录像。

`capture-manifest.json`保存正式场景、数据集分组、原始路径和SHA-256；`SHA256SUMS.txt`用于完整性校验。原始压缩包未被修改。
""",
        encoding="utf-8",
    )

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(path, Path(package_root.name) / path.relative_to(package_root))
    print(json.dumps({"zip": str(zip_path), "videos": 96, "zip_sha256": sha256(zip_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
