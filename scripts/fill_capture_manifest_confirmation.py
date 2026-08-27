"""Fill human-confirmed fields for the private 96-clip capture manifest.

Authorization IDs and validity are supplied by the capture team. Event bounds
are derived from the frozen recording protocol timelines and are explicitly
marked as protocol-derived so they can be spot-checked before formal claims.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


AUTHORIZATION = {
    "P01": "P01-AUTH-20260824",
    "P02": "P02-AUTH-20260824",
    "P03": "P03-AUTH-20260824",
}


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError("manifest has no header")
        return list(reader.fieldnames), list(reader)


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def protocol_bounds(row: dict[str, str]) -> tuple[int, int, str]:
    scenario = row["scenario_id"]
    repeat = int(row.get("repeat_index") or 1)
    duration = max(1000, int(float(row.get("planned_duration_seconds") or 1) * 1000))
    if row["record_role"] == "BASELINE":
        return 0, duration, "BASELINE_FULL_CLIP"
    if scenario == "POS_RAPID_RISE_SWAY":
        return (10000, 22000, "GOLDEN_115S") if repeat == 1 else (5000, 20000, "RAPID_RISE_SWAY")
    if scenario in {"POS_SLOW_SMALL_STEP_SWAY", "POS_ASYMMETRIC_STEP"}:
        return 3000, 15000, "GAIT_ACTION_WINDOW"
    if scenario == "NEG_NORMAL_RISE_WALK":
        return 4000, 17000, "NORMAL_RISE_WALK"
    if scenario == "NEG_RAPID_RISE_STABLE":
        return 4000, 21000, "RAPID_RISE_STABLE"
    if scenario == "NEG_BOUNDARY_NORMAL":
        return {
            1: (3000, 11000, "BOUNDARY_TURN"),
            2: (3000, 12000, "BOUNDARY_STOP"),
            3: (6000, 9000, "BOUNDARY_OCCLUSION"),
            4: (3000, 12000, "BOUNDARY_EXIT"),
        }.get(repeat, (3000, 12000, "BOUNDARY"))
    raise ValueError(f"unknown scenario: {scenario}")


def fill(input_path: Path, output_path: Path) -> dict[str, object]:
    if output_path.exists():
        raise ValueError(f"refusing to overwrite existing output: {output_path}")
    fields, rows = read_rows(input_path)
    required = {"participant_id", "record_role", "scenario_id", "repeat_index", "planned_duration_seconds", "notes"}
    missing = required - set(fields)
    if missing:
        raise ValueError(f"manifest missing columns: {', '.join(sorted(missing))}")
    for row in rows:
        participant = row["participant_id"]
        if participant not in AUTHORIZATION:
            raise ValueError(f"unknown participant: {participant}")
        start, end, label = protocol_bounds(row)
        duration = max(1000, int(float(row.get("planned_duration_seconds") or 1) * 1000))
        start = min(start, max(0, duration - 1000))
        end = min(max(end, start + 1000), duration)
        row["event_start_ms"] = str(start)
        row["event_end_ms"] = str(end)
        row["authorization_record_id"] = AUTHORIZATION[participant]
        row["validity"] = "VALID"
        row["exclusion_reason"] = ""
        note = row.get("notes", "")
        marker = f"event_bounds_source=PROTOCOL_TIMELINE_AUTO_20260826:{label}"
        if marker not in note:
            row["notes"] = f"{note}; {marker}; human_spot_check_pending".strip("; ")
    write_rows(output_path, fields, rows)
    return {
        "status": "PASS",
        "input": str(input_path),
        "output": str(output_path),
        "row_count": len(rows),
        "valid_count": sum(row["validity"] == "VALID" for row in rows),
        "authorization_ids": AUTHORIZATION,
        "event_bounds_source": "PROTOCOL_TIMELINE_AUTO_20260826",
        "human_spot_check_pending": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill authorized validity and protocol-derived event bounds.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    import json

    print(json.dumps(fill(args.input, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
