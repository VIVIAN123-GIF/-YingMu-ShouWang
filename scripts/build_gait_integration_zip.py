"""Package authorized MP4 samples + manifest for the 2026-08-24 GAIT integration.

Contents:
  normal/                D1/D2/D3 三天基线（正常动作）18 段
  controlled_risk/       新视频/4-8.mp4 5 段受控风险
  manifest.csv           每段视频：真实录制时间（从 docx 抽取）+ 期望算法状态/Observation/Evidence
  README.md              使用说明

Actual capture times are read from the docx sidecars where available; the
five 新视频/*.mp4 files carry the recorded-file mtime (no docx sidecar).
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Sample definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Sample:
    group: str                    # "normal" | "controlled_risk"
    file_relpath: str             # path inside zip
    source_path: Path             # local absolute source
    docx_path: Path | None        # optional docx sidecar
    scene: str                    # WALK / RISE / STABLE / RAPID_RISE / TRUNK_SWAY / GOLDEN / UNDER15
    expected_status: str          # SUCCESS | NO_EVIDENCE | LOW_QUALITY
    expected_evidence: str        # comma-separated evidence types
    expected_risk: str            # risk engine result summary


NORMAL_SAMPLES: list[Sample] = []
for day in ("D1", "D2", "D3"):
    for scene, fn_prefix, expected_evi in (
        ("WALK", f"{day}_WALK_01_left_to_right", ""),
        ("WALK", f"{day}_WALK_02_right_to_left", ""),
        ("WALK", f"{day}_WALK_03_left_to_right", ""),
        ("RISE", f"{day}_RISE_01_chair_C", ""),
        ("RISE", f"{day}_RISE_02_chair_C", ""),
        ("STABLE", f"{day}_STABLE_01_stable_S", ""),
    ):
        # D3_RISE_02 has (1) suffix in filename
        mp4 = ROOT / "修改后视频" / "视频" / f"{fn_prefix}.mp4"
        docx = ROOT / "修改后视频" / "视频" / f"{fn_prefix}.docx"
        if not mp4.exists():
            alt = ROOT / "修改后视频" / "视频" / f"{fn_prefix}(1).mp4"
            if alt.exists():
                mp4 = alt
        NORMAL_SAMPLES.append(Sample(
            group="normal",
            file_relpath=f"normal/{day}/{mp4.name}",
            source_path=mp4,
            docx_path=docx if docx.exists() else None,
            scene=scene,
            expected_status="",  # filled from preflight report
            expected_evidence="",
            expected_risk="",
        ))

RISK_SAMPLES: list[Sample] = [
    Sample(
        group="controlled_risk",
        file_relpath="controlled_risk/4_golden.mp4",
        source_path=ROOT / "新视频" / "4.mp4",
        docx_path=None,
        scene="GOLDEN",
        expected_status="SUCCESS",
        expected_evidence="",
        expected_risk="",
    ),
    Sample(
        group="controlled_risk",
        file_relpath="controlled_risk/5_rapid_rise.mp4",
        source_path=ROOT / "新视频" / "5.mp4",
        docx_path=None,
        scene="RAPID_RISE",
        expected_status="SUCCESS",
        expected_evidence="",
        expected_risk="",
    ),
    Sample(
        group="controlled_risk",
        file_relpath="controlled_risk/6_under15.mp4",
        source_path=ROOT / "新视频" / "6.mp4",
        docx_path=None,
        scene="UNDER15",
        expected_status="SUCCESS",
        expected_evidence="",
        expected_risk="",
    ),
    Sample(
        group="controlled_risk",
        file_relpath="controlled_risk/7_rapid_rise.mp4",
        source_path=ROOT / "新视频" / "7.mp4",
        docx_path=None,
        scene="RAPID_RISE",
        expected_status="SUCCESS",
        expected_evidence="",
        expected_risk="",
    ),
    Sample(
        group="controlled_risk",
        file_relpath="controlled_risk/8_trunk_sway.mp4",
        source_path=ROOT / "新视频" / "8.mp4",
        docx_path=None,
        scene="TRUNK_SWAY",
        expected_status="SUCCESS",
        expected_evidence="",
        expected_risk="",
    ),
]

ALL_SAMPLES: list[Sample] = NORMAL_SAMPLES + RISK_SAMPLES


# ---------------------------------------------------------------------------
# Extract captured_at from docx
# ---------------------------------------------------------------------------

def extract_captured_at(docx: Path) -> str | None:
    """Return the ISO-8601 captured_at with +08:00 offset, or None.

    Word 有时会在字符间插入空格（`2026-08-1 8T 15 :0 8 : 48`），先删掉
    整个 fragment 的空格再按 `YYYY-MM-DDTHH:MM:SS` 正则匹配。
    """
    with ZipFile(docx) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    text = re.sub(r"<[^>]+>", " ", xml)
    text = re.sub(r"\s+", " ", text).strip()
    idx = text.find("captured_at")
    if idx < 0:
        return None
    fragment = text[idx : idx + 200]
    # Strip spaces once so `2026-08-1 8T 15 :0 8 : 48` becomes
    # `captured_at2026-08-18T15:08:48+15:09:03location...`
    compact = fragment.replace(" ", "")
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", compact)
    if not match:
        return None
    year, month, day, hh, mm, ss = match.groups()
    return f"{year}-{month}-{day}T{hh}:{mm}:{ss}+08:00"


def fallback_mtime(path: Path) -> str:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=TZ)
    return mtime.isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Manifest & README
# ---------------------------------------------------------------------------

MANIFEST_FIELDS = [
    "group",
    "file_relpath",
    "scene",
    "captured_at",
    "captured_at_source",     # docx | file_mtime
    "resident_id",
    "device_model",
    "device_ref",
    "camera_position_id",
    "authorization_status",
    "authorization_record_id",
    "source_mode",
    "simulated",
    "expected_status",
    "expected_evidence",
    "expected_features_rise_duration_s",
    "expected_features_trunk_sway_angle_deg",
    "expected_features_step_asymmetry_ratio",
    "expected_features_step_speed_norm_s",
    "expected_features_valid_frame_ratio",
    "note",
]

def resident_id_for(sample: Sample) -> str:
    return (
        "resident-modified-video-001"
        if sample.group == "normal"
        else "resident-new-video-001"
    )

def device_ref_for(sample: Sample) -> str:
    return (
        "device-ref-c6c-modified-video-001"
        if sample.group == "normal"
        else "device-ref-c6c-new-video-001"
    )

def camera_position_for(sample: Sample) -> str:
    return (
        "camera-position-modified-video-001"
        if sample.group == "normal"
        else "camera-position-new-video-001"
    )

def auth_record_for(sample: Sample) -> str:
    return (
        "auth-modified-video-local-20260822"
        if sample.group == "normal"
        else "auth-new-video-local-20260816"
    )


def load_preflight() -> dict[str, dict]:
    path = ROOT / "artifacts" / "gait_preflight" / "preflight_report.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {entry["file_relpath"]: entry for entry in data}


def build_manifest_rows() -> list[dict[str, str]]:
    preflight = load_preflight()
    rows: list[dict[str, str]] = []
    for sample in ALL_SAMPLES:
        captured_at = None
        source = "file_mtime"
        if sample.docx_path and sample.docx_path.exists():
            captured_at = extract_captured_at(sample.docx_path)
            if captured_at:
                source = "docx"
        if not captured_at:
            captured_at = fallback_mtime(sample.source_path)

        expected = preflight.get(sample.file_relpath, {})
        exp_status = expected.get("status", sample.expected_status or "SUCCESS")
        exp_evi = "; ".join(expected.get("evidence", []))
        feats = expected.get("features", {})

        note = ""
        if sample.group == "normal" and exp_evi:
            note = (
                "adapter 阈值未做个人基线校准，正常动作会命中 rapid_rise/trunk_sway/"
                "relative_speed_change 等 Evidence。判定应结合个人基线，或以组合规则决定"
                "最终风险等级，而非单条 Evidence 是否出现。"
            )

        rows.append({
            "group": sample.group,
            "file_relpath": sample.file_relpath,
            "scene": sample.scene,
            "captured_at": captured_at,
            "captured_at_source": source,
            "resident_id": resident_id_for(sample),
            "device_model": "EZVIZ_C6C",
            "device_ref": device_ref_for(sample),
            "camera_position_id": camera_position_for(sample),
            "authorization_status": "AUTHORIZED",
            "authorization_record_id": auth_record_for(sample),
            "source_mode": "RECORDED_REPLAY",
            "simulated": "true",
            "expected_status": exp_status,
            "expected_evidence": exp_evi,
            "expected_features_rise_duration_s": "" if feats.get("rise_duration_s") is None else f"{feats['rise_duration_s']}",
            "expected_features_trunk_sway_angle_deg": f"{feats.get('trunk_sway_angle_deg', '')}",
            "expected_features_step_asymmetry_ratio": f"{feats.get('step_asymmetry_ratio', '')}",
            "expected_features_step_speed_norm_s": f"{feats.get('step_speed_norm_s', '')}",
            "expected_features_valid_frame_ratio": f"{feats.get('valid_frame_ratio', '')}",
            "note": note,
        })
    return rows


README = """# GAIT 联调素材包（2026-08-24 · v2）

## 版本说明

v2（2026-08-24）根据 常易铭同学预跑 gait_adapter 的实际结果，修正了 manifest 中
`expected_status` 与 `expected_evidence` 的口径。原 v1 把所有 normal 样本标为
`NO_EVIDENCE`，但当前 `contracts/v1/gait_adapter.run` 的阈值**未做个人基线校准**，
正常动作也会命中 `rapid_rise` / `trunk_sway` / `relative_speed_change` 等 Evidence，
这是"规则输出"而非"风险等级"。真实风险等级由后端风险引擎依据组合规则和状态机决定。

## 目录结构

```
normal/                # 正常动作授权 MP4（三天基线 18 段）
  D1/  D2/  D3/        # 每天 3 段行走 + 2 段起身 + 1 段站稳
controlled_risk/       # 受控风险授权 MP4（5 段）
  4_golden.mp4         # rapid_rise + trunk_sway 组合
  5_rapid_rise.mp4     # 快速起身
  6_under15.mp4        # 恢复不足 15 秒边界
  7_rapid_rise.mp4     # 快速起身
  8_trunk_sway.mp4     # 躯干摇晃
manifest.csv           # 每段视频真实录制时间 + gait_adapter 实际输出（不是"风险等级"）
```

## 使用方式

1. 解压到冷同学联调机器的固定目录，例如 `data/authorized_media/`；
2. 从 `manifest.csv` 读取每段视频的真实 `captured_at`（已带 `+08:00` 时区）；
3. 构造 `AlgorithmJob`，`media_locator` 填相对路径，
   `source_mode="RECORDED_REPLAY"`, `simulated=true`；
4. 调用 `contracts/v1/gait_adapter.run(job)` 获取 `AdapterBatch`；
5. 用 `manifest.csv` 的 `expected_status` / `expected_evidence` 核对**适配器层**输出；
6. 用后端风险引擎（组合规则 + 状态机）判定最终风险等级，**不要以单条 Evidence 判定**。

## 关于 expected_status / expected_evidence 的读法

`expected_status` 与 `expected_evidence` 只反映 `gait_adapter._build_evidences` 的
当前阈值触发情况，包含以下已知偏差：

- `rapid_rise`：`rise_duration_s <= 1.5s` 就触发，正常起身 0.4-0.9s 会命中；
- `trunk_sway`：`|max_trunk_angle| >= 12°` 就触发，正常行走转身可达 30°+；
- `relative_speed_change`：`step_speed <= 0.45` 或 `>= 1.55` 就触发，正常
  行走 1.4-1.9、正常起身 0.2-0.3 全落在两侧区间外；
- `gait_instability`：`step_asymmetry >= 0.35` 就触发，起身过程中步幅采样
  不稳会命中；
- `posture_recovered`：因 gait_adapter 恒把 `stable_posture_duration=0.0`，
  **该 Evidence 目前永远不触发**（这是本次预跑发现的已知问题）。

真实是否风险应结合个人基线、组合规则、observation 窗口后由后端风险引擎决定，
不由 adapter 直接输出的单条 Evidence 决定。

## 时间口径

- `normal/` 全部 18 段有 docx 授权记录，`captured_at_source=docx`；
- `controlled_risk/` 5 段无 docx，`captured_at_source=file_mtime`（文件修改时间
  近似真实录制时间）；
- 所有时间均带 `+08:00` 时区，符合组长要求。

## 授权与隐私口径

- 所有资产 `source_mode=RECORDED_REPLAY`, `simulated=true`；
- **不得**标记为 `LIVE_DEVICE` 实时闭环；
- 联调完成后请从冷同学机器上删除本目录副本，避免授权素材扩散；
- 归档时 diagnostics 需脱敏本地路径与 Token。

## 已知问题与后续修复项

以下由 常易铭同学 08-24 预跑发现，本次联调**先按现状核对适配器输出**，
不作为验收通过依据。修复项已列入后续 PR：

1. `posture_recovered` 恒不触发（`stable_posture_duration=0.0`）
2. adapter 阈值未做个人基线校准，正常动作会命中危险 Evidence
3. `no_pose_detected` 应返回 `LOW_QUALITY` 而不是 `FAILED`（待与冷同学确认）

## 详细契约与规格

- `docs/2026-08-24_GAIT算法联调准备清单.md` §四（GAIT 最低时长/FPS/有效姿态帧要求）
- `docs/2026-08-24_GAIT算法联调准备清单.md` §五（AlgorithmJob 入参 + AdapterBatch 示例）
- `docs/2026-08-24_GAIT算法联调准备清单.md` §七（现场分工，赵同学全程在场）
"""


# ---------------------------------------------------------------------------
# Build zip
# ---------------------------------------------------------------------------

def main() -> None:
    out_dir = ROOT / "deliverables" / "zy"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "GAIT_联调素材_2026-08-24_v2.zip"

    missing = [str(s.source_path) for s in ALL_SAMPLES if not s.source_path.exists()]
    if missing:
        print("MISSING SOURCES:")
        for m in missing:
            print(f"  {m}")
        sys.exit(1)

    rows = build_manifest_rows()

    # manifest.csv in-memory
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=MANIFEST_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    csv_bytes = csv_buffer.getvalue().encode("utf-8-sig")  # BOM for Excel

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("README.md", README.encode("utf-8"))
        zf.writestr("manifest.csv", csv_bytes)
        for sample in ALL_SAMPLES:
            zf.write(sample.source_path, sample.file_relpath)

    total_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"wrote {out_path}")
    print(f"  files: {len(ALL_SAMPLES)} MP4 + manifest.csv + README.md")
    print(f"  size: {total_mb:.2f} MB")

    # Summary
    normal_count = sum(1 for s in ALL_SAMPLES if s.group == "normal")
    risk_count = sum(1 for s in ALL_SAMPLES if s.group == "controlled_risk")
    docx_count = sum(1 for r in rows if r["captured_at_source"] == "docx")
    mtime_count = sum(1 for r in rows if r["captured_at_source"] == "file_mtime")
    print(f"  normal: {normal_count}   controlled_risk: {risk_count}")
    print(f"  captured_at from docx: {docx_count}, from file_mtime: {mtime_count}")


if __name__ == "__main__":
    main()
