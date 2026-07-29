from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


@dataclass
class RapidRiseCandidate:
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


def load_frame_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def group_by_sequence(rows: Iterable[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["sequence_id"], []).append(row)
    for sequence_rows in grouped.values():
        sequence_rows.sort(key=lambda item: int(item["timestamp_ms"]))
    return grouped


def find_best_candidate(
    sequence_id: str,
    rows: list[dict[str, str]],
    min_duration_s: float,
    max_duration_s: float,
    max_rapid_duration_s: float,
    min_upward_displacement: float,
    min_upward_speed: float,
    min_data_quality: float,
) -> Optional[RapidRiseCandidate]:
    best: Optional[RapidRiseCandidate] = None

    for start_index in range(len(rows)):
        for end_index in range(start_index + 1, len(rows)):
            start = rows[start_index]
            end = rows[end_index]
            duration_s = (int(end["timestamp_ms"]) - int(start["timestamp_ms"])) / 1000.0
            if duration_s < min_duration_s:
                continue
            if duration_s > max_duration_s:
                break

            start_y = float(start["pelvis_y_smooth"])
            end_y = float(end["pelvis_y_smooth"])
            upward_displacement = start_y - end_y
            upward_speed = upward_displacement / duration_s if duration_s > 0 else 0.0
            data_quality = min(float(row["core_visibility_mean"]) for row in rows[start_index : end_index + 1])

            if upward_displacement < min_upward_displacement:
                continue
            if upward_speed < min_upward_speed:
                continue
            if duration_s > max_rapid_duration_s:
                continue
            if data_quality < min_data_quality:
                continue

            candidate = RapidRiseCandidate(
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


def candidate_severity(candidate: RapidRiseCandidate, baseline_duration_s: float, min_upward_speed: float) -> float:
    duration_component = clamp((baseline_duration_s - candidate.duration_s) / max(baseline_duration_s, 1e-6))
    speed_component = clamp((candidate.upward_speed - min_upward_speed) / max(0.35 - min_upward_speed, 1e-6))
    displacement_component = clamp(candidate.upward_displacement / 0.18)
    return round(clamp(0.55 * duration_component + 0.30 * speed_component + 0.15 * displacement_component), 3)


def build_evidence(
    candidate: RapidRiseCandidate,
    baseline_duration_s: float,
    min_upward_speed: float,
    resident_id: str,
    source_mode: str,
    simulated: bool,
    location: Optional[str],
) -> dict[str, object]:
    duration_s = round(candidate.duration_s, 3)
    baseline_deviation = round((duration_s - baseline_duration_s) / max(baseline_duration_s, 1e-6), 3)
    severity = candidate_severity(candidate, baseline_duration_s, min_upward_speed)
    confidence = round(clamp(candidate.data_quality * (0.75 + 0.25 * severity)), 3)
    observation_id = f"obs-rapid-rise-{candidate.sequence_id}-{candidate.start_frame}-{candidate.end_frame}"
    evidence_id = f"evi-fall-rapid-rise-{candidate.sequence_id}-{candidate.start_frame}-{candidate.end_frame}"

    return {
        "schema_version": "1.0",
        "evidence_id": evidence_id,
        "observation_ids": [observation_id],
        "resident_id": resident_id,
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "risk_domain": "FALL",
        "evidence_type": "rapid_rise",
        "severity": severity,
        "confidence": confidence,
        "data_quality": round(candidate.data_quality, 3),
        "baseline_value": round(baseline_duration_s, 3),
        "current_value": duration_s,
        "baseline_deviation": baseline_deviation,
        "time_scale": "SHORT",
        "location": location,
        "explanation": (
            f"检测到髋部中心在{duration_s}s内快速上移"
            f"{candidate.upward_displacement:.3f}个画面高度，"
            f"起身时长短于{baseline_duration_s:.1f}s基线。"
        ),
        "adapter_version": "rapid-rise-rule-v1",
        "source_mode": source_mode,
        "simulated": simulated,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rapid_rise evidence from cleaned pose frames.")
    parser.add_argument("--frames-csv", default="deliverables/zy/pose-demo/processed/urfd_pose_cleaned_frames.csv")
    parser.add_argument("--output", default="deliverables/zy/pose-demo/evidence/rapid_rise.json")
    parser.add_argument("--sequence-id", default="", help="Sequence to evaluate. Empty means scan all and choose strongest.")
    parser.add_argument("--resident-id", default="resident-demo-001")
    parser.add_argument("--source-mode", default="PUBLIC_DATASET")
    parser.add_argument("--simulated", action="store_true", default=True)
    parser.add_argument("--location", default=None)
    parser.add_argument("--baseline-duration-s", type=float, default=2.5)
    parser.add_argument("--min-duration-s", type=float, default=0.4)
    parser.add_argument("--max-duration-s", type=float, default=2.0)
    parser.add_argument("--max-rapid-duration-s", type=float, default=1.5)
    parser.add_argument("--min-upward-displacement", type=float, default=0.05)
    parser.add_argument("--min-upward-speed", type=float, default=0.12)
    parser.add_argument("--min-data-quality", type=float, default=0.6)
    args = parser.parse_args()

    grouped = group_by_sequence(load_frame_rows(Path(args.frames_csv)))
    if args.sequence_id:
        grouped = {args.sequence_id: grouped.get(args.sequence_id, [])}

    candidates = [
        candidate
        for sequence_id, rows in grouped.items()
        if rows
        for candidate in [
            find_best_candidate(
                sequence_id=sequence_id,
                rows=rows,
                min_duration_s=args.min_duration_s,
                max_duration_s=args.max_duration_s,
                max_rapid_duration_s=args.max_rapid_duration_s,
                min_upward_displacement=args.min_upward_displacement,
                min_upward_speed=args.min_upward_speed,
                min_data_quality=args.min_data_quality,
            )
        ]
        if candidate is not None
    ]
    if not candidates:
        raise SystemExit("No rapid_rise candidate found with the configured rule thresholds.")

    best = max(candidates, key=lambda candidate: candidate.upward_speed)
    evidence = build_evidence(
        candidate=best,
        baseline_duration_s=args.baseline_duration_s,
        min_upward_speed=args.min_upward_speed,
        resident_id=args.resident_id,
        source_mode=args.source_mode,
        simulated=args.simulated,
        location=args.location,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(evidence, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"rapid_rise evidence: {output}")
    print(f"sequence: {best.sequence_id}")
    print(f"duration_s: {best.duration_s:.3f}")
    print(f"upward_speed: {best.upward_speed:.3f}")
    print(f"upward_displacement: {best.upward_displacement:.3f}")


if __name__ == "__main__":
    main()
