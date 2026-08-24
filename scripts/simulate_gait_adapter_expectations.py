"""Simulate contracts/v1/gait_adapter._build_evidences against pose analyses.

Reads existing per-video analyses (modified_video + new_video) and emits the
Evidence types the current adapter WOULD produce, without re-running MediaPipe.

Written for the 08-24 联调 predflight after 常易铭同学 flagged the
manifest.csv expected_status mismatch.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# gait_adapter rules — mirrors _build_evidences
VIDEO_STEP_SPEED_SCALE = 25.0
RISE_RAPID_MAX_S = 1.5
RISE_SLOW_MIN_S = 3.5
TRUNK_SWAY_MIN_DEG = 12.0
ASYMMETRY_MIN = 0.35
SPEED_LOW = 0.45
SPEED_HIGH = 1.55
VALID_RATIO_MIN = 0.65

RISK_SAMPLES = {"4.mp4", "5.mp4", "6.mp4", "7.mp4", "8.mp4"}
LABEL_BY_FILE = {
    "4.mp4": ("controlled_risk/4_golden.mp4", "GOLDEN"),
    "5.mp4": ("controlled_risk/5_rapid_rise.mp4", "RAPID_RISE"),
    "6.mp4": ("controlled_risk/6_under15.mp4", "UNDER15"),
    "7.mp4": ("controlled_risk/7_rapid_rise.mp4", "RAPID_RISE"),
    "8.mp4": ("controlled_risk/8_trunk_sway.mp4", "TRUNK_SWAY"),
}


def evaluate(row: dict) -> dict:
    fn = row["video"]["file"]
    candidates = row["candidates"]
    rise_dur = (
        float(candidates["rapid_rise"].get("duration_s"))
        if candidates["rapid_rise"]["detected"]
        else None
    )
    trunk_sway_deg = float(candidates["trunk_sway"].get("amplitude_deg", 0.0))
    step_asym = float(row["gait"]["step_length_asymmetry_ratio"])
    step_speed_norm = float(row["gait"]["relative_speed"]) * VIDEO_STEP_SPEED_SCALE
    valid_ratio = float(row["video"]["valid_frame_ratio"])

    evidences: list[str] = []
    if rise_dur is not None and rise_dur <= RISE_RAPID_MAX_S:
        evidences.append("rapid_rise")
    if rise_dur is not None and rise_dur >= RISE_SLOW_MIN_S:
        evidences.append("slow_rise")
    if trunk_sway_deg >= TRUNK_SWAY_MIN_DEG:
        evidences.append("trunk_sway")
    if step_asym >= ASYMMETRY_MIN:
        evidences.append("gait_instability")
    if step_speed_norm <= SPEED_LOW or step_speed_norm >= SPEED_HIGH:
        evidences.append("relative_speed_change")
    if valid_ratio < VALID_RATIO_MIN:
        evidences.append("tracking_lost")

    if valid_ratio < VALID_RATIO_MIN:
        status = "LOW_QUALITY"
    elif evidences:
        status = "SUCCESS"
    else:
        status = "NO_EVIDENCE"

    return {
        "status": status,
        "evidence": evidences,
        "features": {
            "rise_duration_s": rise_dur,
            "trunk_sway_angle_deg": round(trunk_sway_deg, 2),
            "step_asymmetry_ratio": round(step_asym, 3),
            "step_speed_norm_s": round(step_speed_norm, 3),
            "valid_frame_ratio": round(valid_ratio, 3),
        },
    }


def main() -> None:
    mod = json.loads((ROOT / "artifacts" / "modified_video_review" / "modified_video_analysis.json").read_text(encoding="utf-8"))
    new = json.loads((ROOT / "artifacts" / "new_video_review" / "new_video_analysis.json").read_text(encoding="utf-8"))

    results: list[dict] = []

    # normal group (all 18)
    for row in mod:
        fn = row["video"]["file"]
        stem = fn.replace(".mp4", "")
        day = stem.split("_")[0]
        result = evaluate(row)
        result.update({
            "file_relpath": f"normal/{day}/{fn}",
            "group": "normal",
            "scene": stem.split("_")[1],
        })
        results.append(result)

    # controlled_risk group (5)
    for row in new:
        fn = row["video"]["file"]
        if fn not in RISK_SAMPLES:
            continue
        rel, scene = LABEL_BY_FILE[fn]
        result = evaluate(row)
        result.update({
            "file_relpath": rel,
            "group": "controlled_risk",
            "scene": scene,
        })
        results.append(result)

    out = ROOT / "artifacts" / "gait_preflight" / "preflight_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # Summary
    normal = [r for r in results if r["group"] == "normal"]
    risk = [r for r in results if r["group"] == "controlled_risk"]
    print(f"wrote {out}, {len(results)} entries")
    print(f"normal: SUCCESS={sum(1 for r in normal if r['status']=='SUCCESS')}, "
          f"NO_EVIDENCE={sum(1 for r in normal if r['status']=='NO_EVIDENCE')}, "
          f"LOW_QUALITY={sum(1 for r in normal if r['status']=='LOW_QUALITY')}")
    print(f"controlled_risk: SUCCESS={sum(1 for r in risk if r['status']=='SUCCESS')}")


if __name__ == "__main__":
    main()
