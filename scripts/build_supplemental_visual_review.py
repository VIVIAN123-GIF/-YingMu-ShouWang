"""Build the independent visual review for supplemental-validation v1.4.

The scenario labels come from the predeclared capture folders/template.  The
review below records only what is visible in the media and never consumes model
or ruleset output.  Results are intentionally marked as AI-assisted until a
named team member completes the final sign-off.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "supplemental-validation-v1.4"
OUTPUT_JSON = EXPERIMENT_DIR / "ai-assisted-visual-review.json"
OUTPUT_CSV = EXPERIMENT_DIR / "ai-assisted-visual-review.csv"
OUTPUT_SUMS = EXPERIMENT_DIR / "ai-assisted-visual-review-SHA256SUMS.txt"


def item(
    clip_id: str,
    relpath: str,
    scenario_id: str,
    transition: tuple[float, float] | None,
    action: tuple[float, float],
    full_body: str,
    sit_stand: str,
    sway_direction: str,
    sway_count: str,
    gait_action: str,
    interference: str,
    notes: str,
) -> dict[str, object]:
    return {
        "clip_id": clip_id,
        "media_relpath": relpath,
        "scenario_id": scenario_id,
        "full_body_in_frame": full_body,
        "sit_stand_transition": sit_stand,
        "transition_start_s": transition[0] if transition else None,
        "transition_end_s": transition[1] if transition else None,
        "target_action_start_s": action[0],
        "target_action_end_s": action[1],
        "sway_direction": sway_direction,
        "sway_count": sway_count,
        "small_step_or_asymmetry": gait_action,
        "occlusion_multi_person_or_abort": interference,
        "safety_abort": "NO",
        "script_conformance": "YES",
        "review_status": "VALID",
        "review_notes": notes,
    }


RECORDS = [
    item("SV01-POS_RAPID_RISE_SWAY-01", "视频/新正负样本/正样本A/POS-RS-01.mp4", "POS_RAPID_RISE_SWAY", (6.0, 7.5), (7.75, 13.0), "YES", "COMPLETE", "LEFT_RIGHT", "APPROX_4_CYCLES", "NOT_APPLICABLE", "NONE", "快速可控起身后连续左右受控摇晃，随后恢复稳定站立。"),
    item("SV01-POS_RAPID_RISE_SWAY-02", "视频/新正负样本/正样本A/POS-RS-02.mp4", "POS_RAPID_RISE_SWAY", (6.0, 7.5), (7.75, 13.0), "YES", "COMPLETE", "LEFT_RIGHT", "APPROX_4_TO_5_CYCLES", "NOT_APPLICABLE", "NONE", "快速可控起身后连续左右受控摇晃，关键动作全程可见。"),
    item("SV01-POS_RAPID_RISE_SWAY-03", "视频/新正负样本/正样本A/POS-RS-03.mp4", "POS_RAPID_RISE_SWAY", (6.0, 7.5), (8.0, 13.0), "YES", "COMPLETE", "LEFT_RIGHT", "APPROX_4_CYCLES", "NOT_APPLICABLE", "NONE", "快速可控起身后左右受控摇晃，无跨步或安全中止。"),
    item("SV01-POS_RAPID_RISE_SWAY-04", "视频/新正负样本/正样本A/POS-RS-04.mp4", "POS_RAPID_RISE_SWAY", (6.0, 7.25), (7.5, 12.75), "YES", "COMPLETE", "LEFT_RIGHT", "APPROX_4_CYCLES", "NOT_APPLICABLE", "NONE", "快速可控起身后左右受控摇晃，随后稳定站立。"),
    item("SV01-POS_SLOW_SMALL_STEP_SWAY-01", "视频/新正负样本/正样本B/0dfe707659ac6ff78543153d9e8b8052.mp4", "POS_SLOW_SMALL_STEP_SWAY", (5.75, 7.5), (9.25, 15.0), "YES", "COMPLETE", "LEFT_RIGHT_DURING_WALK", "CONTINUOUS_NOT_DISCRETE", "SMALL_STEPS_COMPLETED_APPROX_6_TO_8", "NONE", "起身后向画面右侧慢速小步行走并伴随轻微躯干摆动。"),
    item("SV01-POS_SLOW_SMALL_STEP_SWAY-02", "视频/新正负样本/正样本B/77bf8363e918d3a0cec20be9909eb108.mp4", "POS_SLOW_SMALL_STEP_SWAY", (6.0, 7.75), (9.5, 15.5), "YES", "COMPLETE", "LEFT_RIGHT_DURING_WALK", "CONTINUOUS_NOT_DISCRETE", "SMALL_STEPS_COMPLETED_APPROX_6_TO_8", "NONE", "起身后向画面左侧慢速小步行走并伴随轻微躯干摆动。"),
    item("SV01-POS_SLOW_SMALL_STEP_SWAY-03", "视频/新正负样本/正样本B/c8ca857c626c0473514f5a26e41122fd.mp4", "POS_SLOW_SMALL_STEP_SWAY", (6.0, 7.75), (9.5, 15.0), "YES", "COMPLETE", "LEFT_RIGHT_DURING_WALK", "CONTINUOUS_NOT_DISCRETE", "SMALL_STEPS_COMPLETED_APPROX_6_TO_8", "NONE", "起身后向画面右侧慢速小步行走，动作连续且可自主停止。"),
    item("SV01-POS_SLOW_SMALL_STEP_SWAY-04", "视频/新正负样本/正样本B/fa03b1646fc1dd8ff50029e1e38be0f8.mp4", "POS_SLOW_SMALL_STEP_SWAY", (6.0, 7.75), (9.0, 15.5), "YES", "COMPLETE", "LEFT_RIGHT_DURING_WALK", "CONTINUOUS_NOT_DISCRETE", "SMALL_STEPS_COMPLETED_APPROX_6_TO_8", "NONE", "起身后向画面左侧慢速小步行走，关键步态窗口全身可见。"),
    item("SV01-POS_ASYMMETRIC_STEP-01", "视频/新正负样本/正样本C/89ad59600192e44e7655802d96e9013b.mp4", "POS_ASYMMETRIC_STEP", None, (5.5, 14.0), "YES", "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", "ASYMMETRIC_GAIT_COMPLETED_LEFT_TO_RIGHT", "NONE", "不对称步态肉眼可见；受影响脚侧无法仅凭宽角度画面可靠判定。"),
    item("SV01-POS_ASYMMETRIC_STEP-02", "视频/新正负样本/正样本C/b1f832ae85ae3e20c51048616ad7d844.mp4", "POS_ASYMMETRIC_STEP", None, (5.5, 14.5), "YES", "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", "ASYMMETRIC_GAIT_COMPLETED_RIGHT_TO_LEFT", "NONE", "不对称步态肉眼可见；受影响脚侧不作过度推断。"),
    item("SV01-POS_ASYMMETRIC_STEP-03", "视频/新正负样本/正样本C/c743ac4620fedf75ef03a662b598fa31.mp4", "POS_ASYMMETRIC_STEP", None, (5.5, 14.5), "YES", "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", "ASYMMETRIC_GAIT_COMPLETED_RIGHT_TO_LEFT", "NONE", "不对称步态动作完成，起点、行走和终点均在画面内。"),
    item("SV01-POS_ASYMMETRIC_STEP-04", "视频/新正负样本/正样本C/d928b44b0a49b993e5d1df8a84f75bae.mp4", "POS_ASYMMETRIC_STEP", None, (5.5, 14.0), "YES", "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", "ASYMMETRIC_GAIT_COMPLETED_LEFT_TO_RIGHT", "NONE", "不对称步态动作完成，无拖脚、跌倒或中止。"),
    item("SV01-NEG_NORMAL_RISE_WALK-01", "视频/新正负样本/负样本A/14dff77a673d666ecef21f054b29f749.mp4", "NEG_NORMAL_RISE_WALK", (6.5, 8.5), (10.0, 14.0), "YES", "COMPLETE", "NONE", "0", "NORMAL_WALK_COMPLETED", "NONE", "正常起身后自然行走并稳定停下。"),
    item("SV01-NEG_NORMAL_RISE_WALK-02", "视频/新正负样本/负样本A/3afbbf0dee32ef81cc9a2eae5aa26dec.mp4", "NEG_NORMAL_RISE_WALK", (6.5, 8.5), (10.0, 14.5), "YES", "COMPLETE", "NONE", "0", "NORMAL_WALK_COMPLETED", "NONE", "正常起身和自然行走完整，片尾靠近画面右侧但身体仍完整可见。"),
    item("SV01-NEG_NORMAL_RISE_WALK-03", "视频/新正负样本/负样本A/7ebc537d7c06eb8b2c35418e44137140.mp4", "NEG_NORMAL_RISE_WALK", (6.5, 8.0), (9.5, 13.5), "YES", "COMPLETE", "NONE", "0", "NORMAL_WALK_COMPLETED", "NONE", "正常起身后向画面右侧自然行走并站稳。"),
    item("SV01-NEG_NORMAL_RISE_WALK-04", "视频/新正负样本/负样本A/f4db8a407f044f8904af618db50643b8.mp4", "NEG_NORMAL_RISE_WALK", (6.5, 8.0), (10.0, 13.5), "YES", "COMPLETE", "NONE", "0", "NORMAL_WALK_COMPLETED", "NONE", "正常起身后向画面左侧自然行走并站稳。"),
    item("SV01-NEG_FAST_RISE_STABLE-01", "视频/新正负样本/负样本B/0c46d23cd833f7ca9a769f72ce4f6b59.mp4", "NEG_FAST_RISE_STABLE", (6.5, 8.5), (8.5, 22.0), "YES", "COMPLETE", "NONE", "0", "STABLE_STANDING_COMPLETED", "NONE", "快速起身后持续稳定站立，无可见摇晃或走动。"),
    item("SV01-NEG_FAST_RISE_STABLE-02", "视频/新正负样本/负样本B/2ecd9702372cc9a4ce99aa8a92d96c78.mp4", "NEG_FAST_RISE_STABLE", (5.5, 7.0), (7.0, 19.5), "YES", "COMPLETE", "NONE", "0", "STABLE_STANDING_COMPLETED", "NONE", "快速起身后稳定站立至片尾。"),
    item("SV01-NEG_FAST_RISE_STABLE-03", "视频/新正负样本/负样本B/548f5275f40e4a0bbd9f14592c3e3a63.mp4", "NEG_FAST_RISE_STABLE", (6.5, 8.0), (8.0, 23.0), "YES", "COMPLETE", "NONE", "0", "STABLE_STANDING_COMPLETED", "NONE", "快速起身后约15秒稳定站立。"),
    item("SV01-NEG_FAST_RISE_STABLE-04", "视频/新正负样本/负样本B/8a71de7479226b4af7e3f57ca6683024.mp4", "NEG_FAST_RISE_STABLE", (5.5, 7.0), (7.0, 18.75), "YES", "COMPLETE", "NONE", "0", "STABLE_STANDING_COMPLETED", "NONE", "快速起身后稳定站立约12秒，无额外危险动作。"),
    item("SV01-NEG_NEAR_THRESHOLD_NORMAL-01", "视频/新正负样本/负样本C/009c2ffd7457f6a2ab1a1faf52dba745.mp4", "NEG_NEAR_THRESHOLD_NORMAL", (6.5, 8.0), (8.0, 11.0), "YES", "COMPLETE", "MILD_LATERAL_SHIFT", "1_CONTROLLED_SHIFT", "NEAR_THRESHOLD_NORMAL_COMPLETED", "NONE", "轻微可控横向重心调整后立即站稳，未形成连续摇晃。"),
    item("SV01-NEG_NEAR_THRESHOLD_NORMAL-02", "视频/新正负样本/负样本C/0d867015822be6f229881a17337b8121.mp4", "NEG_NEAR_THRESHOLD_NORMAL", (6.5, 8.5), (9.0, 12.0), "YES", "COMPLETE", "MILD_LATERAL_SHIFT", "1_CONTROLLED_SHIFT", "NEAR_THRESHOLD_NORMAL_COMPLETED", "NONE", "一次轻微可控侧移/倾斜，随后持续稳定。"),
    item("SV01-NEG_NEAR_THRESHOLD_NORMAL-03", "视频/新正负样本/负样本C/48a56792c0187fb8c267dc73531dee2e.mp4", "NEG_NEAR_THRESHOLD_NORMAL", (5.5, 7.0), (7.5, 10.5), "YES", "COMPLETE", "MILD_LATERAL_SHIFT", "1_CONTROLLED_SHIFT", "NEAR_THRESHOLD_NORMAL_COMPLETED", "NONE", "轻微可控横向调整，幅度接近边界但动作保持正常。"),
    item("SV01-NEG_NEAR_THRESHOLD_NORMAL-04", "视频/新正负样本/负样本C/d76e8379916b73ef03e99f72e2e85670.mp4", "NEG_NEAR_THRESHOLD_NORMAL", (6.5, 8.0), (9.0, 12.0), "YES", "COMPLETE", "MILD_LATERAL_SHIFT", "1_CONTROLLED_SHIFT", "NEAR_THRESHOLD_NORMAL_COMPLETED", "NONE", "一次轻微可控侧移后稳定站立，无连续摆动。"),
    item("SV01-QUALITY_OCCLUSION-01", "视频/质量降级/QG-01.mp4", "QUALITY_OCCLUSION", None, (7.5, 20.0), "NO_DURING_INTENDED_OCCLUSION", "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", "INTENDED_FURNITURE_OCCLUSION", "椅子被移到主体前方，躯干下部和腿部持续被遮挡；这是目标质量缺陷。"),
    item("SV01-QUALITY_FEET_OUT-01", "视频/质量降级/QG-02.mp4", "QUALITY_FEET_OUT", None, (9.25, 17.75), "NO_DURING_INTENDED_FEET_OUT", "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", "INTENDED_FEET_OUT_OF_FRAME", "主体靠近镜头后双脚离开画面，随后退回并恢复完整入镜。"),
    item("SV01-QUALITY_LOW_LIGHT-01", "视频/质量降级/QG-03.mp4", "QUALITY_LOW_LIGHT", None, (5.75, 24.5), "UNASSESSABLE_DURING_DARK_INTERVAL", "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", "INTENDED_LOW_LIGHT_AND_NIGHT_MODE", "约5.75秒关灯，7.0至13.0秒为明显暗场；约13.25秒摄像机自动切入黑白夜视，约24.5秒恢复彩色。"),
    item("SV01-QUALITY_MULTI_PERSON-01", "视频/质量降级/QG-04.mp4", "QUALITY_MULTI_PERSON", None, (6.5, 21.0), "YES_PRIMARY_PERSON", "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", "NOT_APPLICABLE", "INTENDED_SECOND_PERSON", "第二人从画面右侧进入并与主体同框约14.5秒，之后离开。"),
    item("SV01-GOLDEN_CONTINUOUS_LOOP-01", "视频/质量降级/QG-05.mp4", "GOLDEN_CONTINUOUS_LOOP", (7.5, 9.5), (7.5, 72.0), "YES", "COMPLETE", "LEFT_RIGHT", "APPROX_4_CYCLES", "NOT_APPLICABLE", "NONE", "连续原片：约10至18.5秒受控摇晃，约19至68.5秒恢复稳定站立，约68.5至72秒坐下，之后稳定坐姿至片尾。仅凭画面不确认系统状态或音频语义。"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def duration_seconds(path: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return round(float(result.stdout.strip()), 3)


def build() -> dict[str, object]:
    outputs = (OUTPUT_JSON, OUTPUT_CSV, OUTPUT_SUMS)
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise ValueError(f"refusing to overwrite existing visual review: {existing}")

    enriched: list[dict[str, object]] = []
    for record in RECORDS:
        media = ROOT / str(record["media_relpath"])
        if not media.is_file():
            raise FileNotFoundError(media)
        row = dict(record)
        row["duration_s"] = duration_seconds(media)
        row["byte_size"] = media.stat().st_size
        row["sha256"] = sha256(media)
        row["capture_date_from_visible_watermark"] = "2026-08-28"
        row["reviewer_type"] = "AI_ASSISTED_VISUAL_REVIEW"
        row["human_signoff_status"] = "PENDING"
        row["label_source"] = "PREDECLARED_FOLDER_AND_MANIFEST"
        row["algorithm_output_consulted"] = False
        enriched.append(row)

    payload = {
        "schema_version": "supplemental-visual-review/1.0",
        "experiment_id": "supplemental-validation-v1.4",
        "review_date": "2026-08-28",
        "reviewer_type": "AI_ASSISTED_VISUAL_REVIEW",
        "human_signoff_status": "PENDING",
        "independence_statement": "Scenario labels were predeclared. No model, ruleset, Evidence, state, or risk output was viewed or used during this review.",
        "sampling_method": {
            "all_clips": "full-duration 1 fps contact sheet",
            "positive_and_quality_clips": "additional 4 fps contact sheet; golden loop 2 fps",
            "negative_clips": "additional 2 fps contact sheet",
            "time_precision": "visual bounds are approximate to 0.25-0.5 seconds",
        },
        "status_definitions": {
            "VALID": "The predeclared action or intentional quality defect is visible and assessable without a safety abort.",
            "ABORTED": "The participant or safety observer stopped the take before completion.",
            "REJECTED": "The take completed but the required action/defect is absent or not assessable.",
        },
        "record_count": len(enriched),
        "status_counts": {
            "VALID": sum(row["review_status"] == "VALID" for row in enriched),
            "ABORTED": sum(row["review_status"] == "ABORTED" for row in enriched),
            "REJECTED": sum(row["review_status"] == "REJECTED" for row in enriched),
        },
        "records": enriched,
    }

    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = list(enriched[0].keys())
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(enriched)
    sums = [
        f"{sha256(OUTPUT_JSON)}  {OUTPUT_JSON.name}",
        f"{sha256(OUTPUT_CSV)}  {OUTPUT_CSV.name}",
    ]
    OUTPUT_SUMS.write_text("\n".join(sums) + "\n", encoding="ascii")
    return {
        "status": "PASS",
        "records": len(enriched),
        "status_counts": payload["status_counts"],
        "outputs": [str(path.relative_to(ROOT)) for path in outputs],
        "human_signoff_status": "PENDING",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the v1.4 independent visual review artifacts.")
    parser.parse_args()
    print(json.dumps(build(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
