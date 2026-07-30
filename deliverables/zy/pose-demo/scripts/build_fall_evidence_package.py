from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Iterable, Optional


ADAPTER_VERSION = "fall-evidence-rule-v1"
REQUIRED_EVIDENCE_TYPES = [
    "rapid_rise",
    "slow_rise",
    "trunk_sway",
    "gait_instability",
    "relative_speed_change",
    "posture_recovered",
    "tracking_lost",
]


@dataclass
class MotionWindow:
    sequence_id: str
    start_frame: int
    end_frame: int
    start_timestamp_ms: int
    end_timestamp_ms: int
    duration_s: float
    upward_displacement: float
    upward_speed: float
    data_quality: float


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def timestamp_at(base: datetime, seconds: int) -> str:
    return (base + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def group_rows(rows: Iterable[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["sequence_id"], []).append(row)
    for sequence_rows in grouped.values():
        sequence_rows.sort(key=lambda item: int(item["timestamp_ms"]))
    return grouped


def base_evidence(
    evidence_type: str,
    observation_id: str,
    resident_id: str,
    timestamp: str,
    severity: float,
    confidence: float,
    data_quality: float,
    baseline_value: Optional[float],
    current_value: Optional[float],
    baseline_deviation: Optional[float],
    explanation: str,
    source_mode: str,
    simulated: bool,
    location: Optional[str],
) -> dict[str, object]:
    evidence_slug = evidence_type.replace("_", "-")
    observation_slug = observation_id.removeprefix("obs-")
    if observation_slug.startswith(evidence_slug):
        evidence_suffix = observation_slug
    else:
        evidence_suffix = f"{evidence_slug}-{observation_slug}"
    return {
        "schema_version": "1.0",
        "evidence_id": f"evi-fall-{evidence_suffix}",
        "observation_ids": [observation_id],
        "resident_id": resident_id,
        "timestamp": timestamp,
        "risk_domain": "FALL",
        "evidence_type": evidence_type,
        "severity": round(clamp(severity), 3),
        "confidence": round(clamp(confidence), 3),
        "data_quality": round(clamp(data_quality), 3),
        "baseline_value": None if baseline_value is None else round(baseline_value, 3),
        "current_value": None if current_value is None else round(current_value, 3),
        "baseline_deviation": None if baseline_deviation is None else round(baseline_deviation, 3),
        "time_scale": "SHORT",
        "location": location,
        "explanation": explanation,
        "adapter_version": ADAPTER_VERSION,
        "source_mode": source_mode,
        "simulated": simulated,
    }


def find_upward_window(
    sequence_id: str,
    rows: list[dict[str, str]],
    min_duration_s: float,
    max_duration_s: float,
    min_upward_displacement: float,
) -> Optional[MotionWindow]:
    best: Optional[MotionWindow] = None
    for start_index in range(len(rows)):
        for end_index in range(start_index + 1, len(rows)):
            start = rows[start_index]
            end = rows[end_index]
            duration_s = (int(end["timestamp_ms"]) - int(start["timestamp_ms"])) / 1000.0
            if duration_s < min_duration_s:
                continue
            if duration_s > max_duration_s:
                break
            upward_displacement = float(start["pelvis_y_smooth"]) - float(end["pelvis_y_smooth"])
            if upward_displacement < min_upward_displacement:
                continue
            upward_speed = upward_displacement / max(duration_s, 1e-6)
            data_quality = min(float(row["core_visibility_mean"]) for row in rows[start_index : end_index + 1])
            candidate = MotionWindow(
                sequence_id=sequence_id,
                start_frame=int(start["frame_number"]),
                end_frame=int(end["frame_number"]),
                start_timestamp_ms=int(start["timestamp_ms"]),
                end_timestamp_ms=int(end["timestamp_ms"]),
                duration_s=duration_s,
                upward_displacement=upward_displacement,
                upward_speed=upward_speed,
                data_quality=data_quality,
            )
            if best is None or candidate.upward_speed > best.upward_speed:
                best = candidate
    return best


def build_rise_evidence(
    evidence_type: str,
    window: MotionWindow,
    timestamp: str,
    baseline_duration_s: float,
    resident_id: str,
    source_mode: str,
    simulated: bool,
    location: Optional[str],
) -> dict[str, object]:
    duration = window.duration_s
    deviation = (duration - baseline_duration_s) / max(baseline_duration_s, 1e-6)
    if evidence_type == "rapid_rise":
        severity = 0.55 * clamp((baseline_duration_s - duration) / baseline_duration_s) + 0.45 * clamp(window.upward_speed / 0.35)
        explanation = (
            f"髋部中心在{duration:.3f}s内上移{window.upward_displacement:.3f}个画面高度，"
            f"快于{baseline_duration_s:.1f}s起身基线。"
        )
    else:
        severity = clamp((duration - baseline_duration_s) / baseline_duration_s)
        explanation = f"起身窗口持续{duration:.3f}s，慢于{baseline_duration_s:.1f}s起身基线。"
    return base_evidence(
        evidence_type=evidence_type,
        observation_id=f"obs-{evidence_type}-{window.sequence_id}-{window.start_frame}-{window.end_frame}",
        resident_id=resident_id,
        timestamp=timestamp,
        severity=severity,
        confidence=window.data_quality * (0.75 + 0.25 * clamp(severity)),
        data_quality=window.data_quality,
        baseline_value=baseline_duration_s,
        current_value=duration,
        baseline_deviation=deviation,
        explanation=explanation,
        source_mode=source_mode,
        simulated=simulated,
        location=location,
    )


def build_trunk_sway_evidence(
    rows: list[dict[str, str]],
    sequence_id: str,
    timestamp: str,
    resident_id: str,
    source_mode: str,
    simulated: bool,
    location: Optional[str],
    baseline_sway_deg: float,
) -> dict[str, object]:
    angles = [float(row["trunk_angle_deg_smooth"]) for row in rows]
    current = max((abs(value) for value in angles), default=0.0)
    data_quality = mean(float(row["core_visibility_mean"]) for row in rows) if rows else 0.0
    deviation = (current - baseline_sway_deg) / max(baseline_sway_deg, 1e-6)
    severity = clamp(deviation / 2.0)
    direction = "高于" if deviation > 0 else "未超过"
    return base_evidence(
        evidence_type="trunk_sway",
        observation_id=f"obs-trunk-sway-{sequence_id}",
        resident_id=resident_id,
        timestamp=timestamp,
        severity=severity,
        confidence=data_quality * (0.70 + 0.30 * severity),
        data_quality=data_quality,
        baseline_value=baseline_sway_deg,
        current_value=current,
        baseline_deviation=deviation,
        explanation=f"躯干角度最大摆动为{current:.2f}度，{direction}{baseline_sway_deg:.1f}度基线阈值。",
        source_mode=source_mode,
        simulated=simulated,
        location=location,
    )


def build_gait_instability_evidence(
    feature_row: dict[str, str],
    timestamp: str,
    resident_id: str,
    source_mode: str,
    simulated: bool,
    location: Optional[str],
    baseline_asymmetry: float,
) -> dict[str, object]:
    current = float(feature_row["step_length_asymmetry_ratio"])
    data_quality = float(feature_row["mean_core_visibility"])
    deviation = (current - baseline_asymmetry) / max(baseline_asymmetry, 1e-6)
    severity = clamp(deviation / 2.0)
    return base_evidence(
        evidence_type="gait_instability",
        observation_id=f"obs-gait-instability-{feature_row['sequence_id']}",
        resident_id=resident_id,
        timestamp=timestamp,
        severity=severity,
        confidence=data_quality * (0.70 + 0.30 * severity),
        data_quality=data_quality,
        baseline_value=baseline_asymmetry,
        current_value=current,
        baseline_deviation=deviation,
        explanation=f"步长差异比为{current:.3f}，高于{baseline_asymmetry:.3f}个人基线。",
        source_mode=source_mode,
        simulated=simulated,
        location=location,
    )


def build_relative_speed_evidence(
    feature_row: dict[str, str],
    timestamp: str,
    resident_id: str,
    source_mode: str,
    simulated: bool,
    location: Optional[str],
    baseline_speed: float,
) -> dict[str, object]:
    current = float(feature_row["step_speed"])
    deviation = (current - baseline_speed) / max(baseline_speed, 1e-6)
    severity = clamp(abs(deviation) / 1.5)
    direction = "高于" if deviation > 0 else "低于"
    return base_evidence(
        evidence_type="relative_speed_change",
        observation_id=f"obs-relative-speed-{feature_row['sequence_id']}",
        resident_id=resident_id,
        timestamp=timestamp,
        severity=severity,
        confidence=float(feature_row["mean_core_visibility"]) * (0.70 + 0.30 * severity),
        data_quality=float(feature_row["mean_core_visibility"]),
        baseline_value=baseline_speed,
        current_value=current,
        baseline_deviation=deviation,
        explanation=f"相对步速为{current:.3f}画面单位/秒，{direction}{baseline_speed:.3f}个人基线。",
        source_mode=source_mode,
        simulated=simulated,
        location=location,
    )


def build_tracking_lost_evidence(
    feature_row: dict[str, str],
    timestamp: str,
    resident_id: str,
    source_mode: str,
    simulated: bool,
    location: Optional[str],
    min_valid_ratio: float,
) -> dict[str, object]:
    valid_ratio = float(feature_row["valid_frame_ratio"])
    data_quality = float(feature_row["mean_core_visibility"])
    severity = clamp((min_valid_ratio - valid_ratio) / max(min_valid_ratio, 1e-6))
    return base_evidence(
        evidence_type="tracking_lost",
        observation_id=f"obs-tracking-lost-{feature_row['sequence_id']}",
        resident_id=resident_id,
        timestamp=timestamp,
        severity=severity,
        confidence=clamp(0.65 + 0.35 * severity),
        data_quality=data_quality,
        baseline_value=min_valid_ratio,
        current_value=valid_ratio,
        baseline_deviation=valid_ratio - min_valid_ratio,
        explanation=f"有效姿态帧比例为{valid_ratio:.3f}，低于{min_valid_ratio:.2f}数据质量阈值。",
        source_mode=source_mode,
        simulated=simulated,
        location=location,
    )


def build_posture_recovered_evidence(
    rows: list[dict[str, str]],
    sequence_id: str,
    timestamp: str,
    resident_id: str,
    source_mode: str,
    simulated: bool,
    location: Optional[str],
    stable_angle_deg: float,
) -> dict[str, object]:
    tail = rows[-min(8, len(rows)) :]
    tail_angles = [abs(float(row["trunk_angle_deg_smooth"])) for row in tail]
    current = max(tail_angles) if tail_angles else 0.0
    data_quality = mean(float(row["core_visibility_mean"]) for row in tail) if tail else 0.0
    severity = clamp(1.0 - current / max(stable_angle_deg, 1e-6))
    return base_evidence(
        evidence_type="posture_recovered",
        observation_id=f"obs-posture-recovered-{sequence_id}",
        resident_id=resident_id,
        timestamp=timestamp,
        severity=severity,
        confidence=data_quality * (0.80 + 0.20 * severity),
        data_quality=data_quality,
        baseline_value=stable_angle_deg,
        current_value=current,
        baseline_deviation=(current - stable_angle_deg) / max(stable_angle_deg, 1e-6),
        explanation=f"干预后观察窗内躯干最大偏角{current:.2f}度，姿态回到稳定范围。",
        source_mode=source_mode,
        simulated=simulated,
        location=location,
    )


def choose_rows(
    grouped_frames: dict[str, list[dict[str, str]]],
    feature_rows: list[dict[str, str]],
    sequence_id: str,
) -> tuple[str, list[dict[str, str]], dict[str, str]]:
    feature_by_id = {row["sequence_id"]: row for row in feature_rows}
    if sequence_id:
        if sequence_id not in grouped_frames or sequence_id not in feature_by_id:
            raise SystemExit(f"Unknown sequence_id: {sequence_id}")
        return sequence_id, grouped_frames[sequence_id], feature_by_id[sequence_id]

    baseline_speed = median(float(row["step_speed"]) for row in feature_rows if row["label"] == "adl")
    ranked: list[tuple[float, dict[str, str]]] = []
    for row in feature_rows:
        row_sequence_id = row["sequence_id"]
        rows = grouped_frames.get(row_sequence_id)
        if not rows:
            continue
        rapid_window = find_upward_window(row_sequence_id, rows, 0.4, 1.5, 0.05)
        if rapid_window is None:
            continue
        max_sway = max(abs(float(frame["trunk_angle_deg_smooth"])) for frame in rows)
        speed_deviation = abs((float(row["step_speed"]) - baseline_speed) / max(baseline_speed, 1e-6))
        score = (
            2.0 * clamp(rapid_window.upward_speed / 0.35)
            + clamp((max_sway - 8.0) / 16.0)
            + clamp((float(row["step_length_asymmetry_ratio"]) - 0.18) / 0.36)
            + clamp(speed_deviation / 1.5)
        )
        ranked.append((score, row))
    if ranked:
        best_row = max(ranked, key=lambda item: item[0])[1]
        return best_row["sequence_id"], grouped_frames[best_row["sequence_id"]], best_row
    raise SystemExit("No sequence with both frame rows and feature summary was found.")


def write_individual_evidence(output_dir: Path, evidence_items: list[dict[str, object]]) -> None:
    for evidence in evidence_items:
        write_json(output_dir / f"{evidence['evidence_type']}.json", evidence)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Fall Evidence package for agent integration.")
    parser.add_argument("--frames-csv", default="deliverables/zy/pose-demo/processed/urfd_pose_cleaned_frames.csv")
    parser.add_argument("--features-csv", default="deliverables/zy/pose-demo/processed/urfd_gait_features.csv")
    parser.add_argument("--evidence-dir", default="deliverables/zy/pose-demo/evidence")
    parser.add_argument("--integration-dir", default="deliverables/zy/pose-demo/integration")
    parser.add_argument("--sequence-id", default="", help="Optional sequence id for the golden 30s package.")
    parser.add_argument("--resident-id", default="resident-demo-001")
    parser.add_argument("--source-mode", default="PUBLIC_DATASET")
    parser.add_argument("--simulated", action="store_true", default=True)
    parser.add_argument("--location", default="bedroom")
    parser.add_argument("--baseline-rise-duration-s", type=float, default=2.5)
    parser.add_argument("--baseline-sway-deg", type=float, default=8.0)
    parser.add_argument("--baseline-asymmetry", type=float, default=0.18)
    parser.add_argument("--min-valid-frame-ratio", type=float, default=0.65)
    args = parser.parse_args()

    frame_rows = read_csv(Path(args.frames_csv))
    feature_rows = read_csv(Path(args.features_csv))
    grouped_frames = group_rows(frame_rows)
    sequence_id, rows, feature_row = choose_rows(grouped_frames, feature_rows, args.sequence_id)
    base_time = datetime(2026, 8, 7, 3, 7, 0, tzinfo=timezone(timedelta(hours=8)))

    rapid_window = find_upward_window(sequence_id, rows, 0.4, 1.5, 0.05)
    if rapid_window is None:
        raise SystemExit(f"No rapid rise window found for {sequence_id}.")
    slow_window = find_upward_window(sequence_id, rows, 1.5, 3.5, 0.04) or rapid_window

    baseline_speed = median(float(row["step_speed"]) for row in feature_rows if row["label"] == "adl")
    all_valid_ratios = sorted(feature_rows, key=lambda row: float(row["valid_frame_ratio"]))
    tracking_row = all_valid_ratios[0]
    tracking_sequence = tracking_row["sequence_id"]

    evidence_items = [
        build_rise_evidence("rapid_rise", rapid_window, timestamp_at(base_time, 1), args.baseline_rise_duration_s, args.resident_id, args.source_mode, args.simulated, args.location),
        build_trunk_sway_evidence(rows, sequence_id, timestamp_at(base_time, 6), args.resident_id, args.source_mode, args.simulated, args.location, args.baseline_sway_deg),
        build_gait_instability_evidence(feature_row, timestamp_at(base_time, 8), args.resident_id, args.source_mode, args.simulated, args.location, args.baseline_asymmetry),
        build_relative_speed_evidence(feature_row, timestamp_at(base_time, 10), args.resident_id, args.source_mode, args.simulated, args.location, baseline_speed),
        build_rise_evidence("slow_rise", slow_window, timestamp_at(base_time, 14), args.baseline_rise_duration_s, args.resident_id, args.source_mode, args.simulated, args.location),
        build_tracking_lost_evidence(tracking_row, timestamp_at(base_time, 18), args.resident_id, args.source_mode, args.simulated, args.location, args.min_valid_frame_ratio),
        build_posture_recovered_evidence(rows, sequence_id, timestamp_at(base_time, 28), args.resident_id, args.source_mode, args.simulated, args.location, args.baseline_sway_deg),
    ]

    output_dir = Path(args.evidence_dir)
    integration_dir = Path(args.integration_dir)
    write_individual_evidence(output_dir, evidence_items)
    write_json(output_dir / "fall_evidence_batch.json", {"schema_version": "1.0", "adapter_version": ADAPTER_VERSION, "evidence": evidence_items})

    golden_package = {
        "schema_version": "1.0",
        "scenario_id": "golden-30s-fall-demo-001",
        "scenario_name": "第100天黄金半分钟跌倒前兆联调包",
        "resident_id": args.resident_id,
        "source_mode": args.source_mode,
        "simulated": args.simulated,
        "asset_id": sequence_id,
        "post_endpoint": "/api/v1/evidence",
        "expected_agent_behavior": {
            "risk_domain": "FALL",
            "expected_risk_level": "ORANGE",
            "expected_time_horizon": "IMMINENT",
            "recovery_signal": "posture_recovered",
        },
        "timeline": [
            {"second": 1, "evidence_type": "rapid_rise", "action": "POST /api/v1/evidence"},
            {"second": 6, "evidence_type": "trunk_sway", "action": "POST /api/v1/evidence"},
            {"second": 8, "evidence_type": "gait_instability", "action": "POST /api/v1/evidence"},
            {"second": 10, "evidence_type": "relative_speed_change", "action": "POST /api/v1/evidence"},
            {"second": 28, "evidence_type": "posture_recovered", "action": "POST /api/v1/evidence"},
        ],
        "evidence": [
            item for item in evidence_items if item["evidence_type"] in {"rapid_rise", "trunk_sway", "gait_instability", "relative_speed_change", "posture_recovered"}
        ],
    }
    write_json(integration_dir / "golden_30s_fall_evidence.json", golden_package)

    print(f"sequence: {sequence_id}")
    print(f"baseline_speed: {baseline_speed:.3f}")
    print(f"tracking_lost_source: {tracking_sequence}")
    print(f"evidence_types: {', '.join(item['evidence_type'] for item in evidence_items)}")
    print(f"batch: {output_dir / 'fall_evidence_batch.json'}")
    print(f"golden_30s: {integration_dir / 'golden_30s_fall_evidence.json'}")


if __name__ == "__main__":
    main()
