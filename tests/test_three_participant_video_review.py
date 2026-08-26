from __future__ import annotations

import csv
import zipfile
from pathlib import Path

import pytest

from scripts import review_three_participant_videos as review
from scripts import three_participant_experiment as experiment


def _candidate(participant: str, scenario_id: str, index: int, *, golden: bool = False) -> dict[str, str]:
    scenario = next(item for item in experiment.SCENARIOS if item.scenario_id == scenario_id)
    duration = 115_000 if golden else scenario.planned_duration_seconds * 1000
    return {
        "candidate_id": f"{participant}-C-{scenario_id}-{index}",
        "folder_participant_id": participant,
        "proposed_participant_id": participant,
        "confirmed_participant_id": participant,
        "batch": "day1_baseline" if scenario.record_role == "BASELINE" else "day2_evaluation",
        "record_role_hint": scenario.record_role,
        "capture_date": "2026-08-22" if scenario.record_role == "BASELINE" else "2026-08-24",
        "original_relpath": f"{participant}/{scenario_id}-{index}.mp4",
        "sha256": f"{index:064x}"[-64:],
        "duration_ms": str(duration),
        "decode_status": "PASS",
        "normalized_relpath": f"normalized-media/{participant}/{scenario_id}-{index}.mp4",
        "confirmed_scenario_id": scenario_id,
        "confirmed_validity": "VALID",
        "confirmed_event_start_ms": "1000",
        "confirmed_event_end_ms": "5000",
        "protocol_variant": "GOLDEN_115S" if golden else "STANDARD",
        "lighting": "INDOOR",
        "camera_position_id": "C6c-pos01",
        "authorization_record_id": f"AUTH-{participant}",
        "selection_priority": str(index),
    }


def test_safe_extract_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("../escape.mp4", b"unsafe")

    with pytest.raises(ValueError, match="unsafe ZIP member"):
        review.prepare_input(archive, tmp_path / "output")


def test_selection_requires_human_confirmation():
    row = _candidate("P01", "NEG_BOUNDARY_NORMAL", 1)
    row["confirmed_scenario_id"] = ""
    row["confirmed_validity"] = "PENDING"

    selected, rejected, manifest = review.select_protocol_slots([row])

    assert sum(item["selection_status"] == "SELECTED" for item in selected) == 0
    assert any(item["selection_status"] == "AWAITING_CONFIRMATION" for item in rejected)
    assert len(manifest) == 96


def test_selection_populates_all_slots_and_requires_golden_115s():
    rows = []
    sequence = 0
    for participant in review.PARTICIPANTS:
        for scenario in experiment.SCENARIOS:
            for index in range(1, scenario.count + 1):
                sequence += 1
                rows.append(_candidate(
                    participant,
                    scenario.scenario_id,
                    sequence,
                    golden=scenario.golden_first and index == 1,
                ))

    selected, rejected, manifest = review.select_protocol_slots(rows)

    assert sum(item["selection_status"] == "SELECTED" for item in selected) == 96
    assert not [item for item in rejected if item["selection_status"] == "EXTRA_RETAKE"]
    golden = [row for row in manifest if row["protocol_variant"] == "GOLDEN_115S"]
    assert len(golden) == 3
    assert all(row["validity"] == "VALID" for row in manifest)


def test_summary_reports_minimum_missing_formal_clips():
    rows = []
    for index in range(9):
        rows.append({
            "proposed_participant_id": review.PARTICIPANTS[index % 3],
            "record_role_hint": "SMOKE",
            "decode_status": "PASS",
            "exact_duplicate_group": "",
            "duration_ms": 15_000,
            "protocol_variant": "STANDARD",
        })
    for index in range(37):
        rows.append({
            "proposed_participant_id": review.PARTICIPANTS[index % 3],
            "record_role_hint": "EVALUATION",
            "decode_status": "PASS",
            "exact_duplicate_group": "",
            "duration_ms": 20_000,
            "protocol_variant": "STANDARD",
        })
    selected = [{"selection_status": "MISSING_OR_UNCONFIRMED"} for _ in range(96)]

    summary = review.build_summary(rows, selected)

    assert summary["video_count"] == 46
    assert summary["smoke_count"] == 9
    assert summary["formal_candidate_count"] == 37
    assert summary["minimum_additional_formal_clips"] == 59
    assert summary["test_set_inference_run"] is False


def test_csv_round_trip_preserves_unicode(tmp_path: Path):
    output = tmp_path / "review.csv"
    rows = [{field: "" for field in review.INVENTORY_FIELDS}]
    rows[0].update({"candidate_id": "P01-DAY1-001", "reviewer_notes": "受控模拟动作"})

    review.write_csv(output, review.INVENTORY_FIELDS, rows)
    with output.open("r", encoding="utf-8-sig", newline="") as stream:
        restored = list(csv.DictReader(stream))

    assert restored[0]["reviewer_notes"] == "受控模拟动作"
