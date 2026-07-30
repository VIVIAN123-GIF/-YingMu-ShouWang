from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median


PROFILE_VERSION = "gait-baseline-v1"


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * ratio
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def mad(values: list[float], center: float) -> float:
    deviations = [abs(value - center) for value in values]
    return median(deviations) if deviations else 0.0


def read_feature_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def metric_summary(values: list[float]) -> dict[str, object]:
    center = median(values) if values else 0.0
    p25 = percentile(values, 0.25)
    p75 = percentile(values, 0.75)
    return {
        "count": len(values),
        "median": round(center, 6),
        "mad": round(mad(values, center), 6),
        "p10": round(percentile(values, 0.10), 6),
        "p25": round(p25, 6),
        "p75": round(p75, 6),
        "p90": round(percentile(values, 0.90), 6),
        "iqr": round(p75 - p25, 6),
    }


def build_profile(rows: list[dict[str, str]], min_valid_frame_ratio: float) -> dict[str, object]:
    adl_rows = [
        row
        for row in rows
        if row["label"] == "adl" and float(row["valid_frame_ratio"]) >= min_valid_frame_ratio
    ]
    if len(adl_rows) < 8:
        raise SystemExit("Not enough high-quality ADL rows to build a baseline profile.")

    speed_values = [float(row["step_speed"]) for row in adl_rows]
    sway_values = [float(row["sway_frequency_hz"]) for row in adl_rows]
    asymmetry_values = [float(row["step_length_asymmetry_ratio"]) for row in adl_rows]
    visibility_values = [float(row["mean_core_visibility"]) for row in adl_rows]
    valid_ratio_values = [float(row["valid_frame_ratio"]) for row in adl_rows]

    speed_summary = metric_summary(speed_values)
    sway_summary = metric_summary(sway_values)
    asymmetry_summary = metric_summary(asymmetry_values)
    visibility_summary = metric_summary(visibility_values)
    valid_ratio_summary = metric_summary(valid_ratio_values)

    return {
        "schema_version": "1.0",
        "profile_version": PROFILE_VERSION,
        "built_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "resident_id": "resident-demo-001",
        "source_mode": "PUBLIC_DATASET",
        "source_dataset": "URFD cam0 ADL",
        "sample_policy": {
            "label": "adl",
            "min_valid_frame_ratio": min_valid_frame_ratio,
            "sequence_count": len(adl_rows),
        },
        "metrics": {
            "step_speed": speed_summary,
            "sway_frequency_hz": sway_summary,
            "step_length_asymmetry_ratio": asymmetry_summary,
            "mean_core_visibility": visibility_summary,
            "valid_frame_ratio": valid_ratio_summary,
        },
        "rule_parameters": {
            "baseline_rise_duration_s": 2.5,
            "slow_rise_duration_s": 3.5,
            "baseline_speed": speed_summary["median"],
            "baseline_sway_deg": 8.0,
            "baseline_sway_frequency_hz": sway_summary["median"],
            "baseline_asymmetry": asymmetry_summary["median"],
            "tracking_lost_valid_frame_ratio": max(0.50, min_valid_frame_ratio),
            "posture_recovered_stable_angle_deg": 8.0,
            "relative_speed_deviation_alert_ratio": 1.5,
            "gait_instability_alert_ratio": 2.0,
        },
        "stability": {
            "status": "RULE_BASELINE_STABLE_FOR_DEMO",
            "reason": "基线来自高质量 ADL 序列中位数和分位数，避免单个公开数据片段直接决定阈值。",
            "requires_real_device_recalibration": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a gait rule baseline profile from cleaned feature rows.")
    parser.add_argument("--features-csv", default="deliverables/zy/pose-demo/processed/urfd_gait_features.csv")
    parser.add_argument("--output", default="deliverables/zy/pose-demo/baseline/baseline_profile.json")
    parser.add_argument("--min-valid-frame-ratio", type=float, default=0.65)
    args = parser.parse_args()

    profile = build_profile(read_feature_rows(Path(args.features_csv)), args.min_valid_frame_ratio)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(profile, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"baseline_profile: {output}")
    print(f"sequence_count: {profile['sample_policy']['sequence_count']}")
    print(f"baseline_speed: {profile['rule_parameters']['baseline_speed']}")
    print(f"baseline_asymmetry: {profile['rule_parameters']['baseline_asymmetry']}")


if __name__ == "__main__":
    main()
