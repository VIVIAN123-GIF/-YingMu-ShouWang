from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import three_participant_experiment as experiment


def _write_rows(path: Path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _completed_manifest(tmp_path: Path) -> tuple[Path, Path]:
    media_root = tmp_path / "media"
    media_root.mkdir()
    rows = experiment.planned_rows()
    for row in rows:
        participant = str(row["participant_id"])
        role = str(row["record_role"])
        day = 1 if role == "BASELINE" else 2
        row["capture_date"] = f"2026-08-{21 + day:02d}"
        row["event_start_ms"] = 1000
        row["event_end_ms"] = 5000
        row["lighting"] = "NORMAL"
        row["authorization_record_id"] = f"AUTH-{participant}"
        row["validity"] = "VALID"
        row["video_relpath"] = f"{row['clip_id']}.mp4"
        (media_root / str(row["video_relpath"])).write_bytes(str(row["clip_id"]).encode())
    manifest = tmp_path / "manifest.csv"
    experiment.write_csv(manifest, experiment.MANIFEST_FIELDS, rows)
    return manifest, media_root


def test_planned_manifest_has_96_participant_isolated_slots(tmp_path: Path):
    output = tmp_path / "manifest.csv"

    experiment.generate_manifest(output)
    rows = experiment.read_csv(output)
    report = experiment.validate_manifest(output, stage="template")

    assert report["status"] == "PASS"
    assert len(rows) == 96
    assert {row["dataset_split"] for row in rows if row["participant_id"] == "P01"} == {"CALIBRATION"}
    assert {row["dataset_split"] for row in rows if row["participant_id"] == "P02"} == {"VALIDATION"}
    assert {row["dataset_split"] for row in rows if row["participant_id"] == "P03"} == {"TEST"}
    assert sum(row["record_role"] == "BASELINE" for row in rows) == 24
    assert sum(row["record_role"] == "EVALUATION" for row in rows) == 72


def test_captured_manifest_requires_cross_date_and_all_valid_slots(tmp_path: Path):
    manifest, media_root = _completed_manifest(tmp_path)
    rows = experiment.read_csv(manifest)
    rows[0]["capture_date"] = "2026-08-23"
    _write_rows(manifest, experiment.MANIFEST_FIELDS, rows)

    report = experiment.validate_manifest(manifest, stage="captured", media_root=media_root)

    assert report["status"] == "FAIL"
    assert any("different dates" in error for error in report["errors"])


def test_lock_copies_only_p03_and_detects_tampering(tmp_path: Path):
    manifest, media_root = _completed_manifest(tmp_path)
    output = tmp_path / "TEST_LOCKED"

    payload = experiment.lock_test_set(manifest, media_root, output)

    assert payload["record_count"] == 32
    assert payload["baseline_count"] == 8
    assert payload["evaluation_count"] == 24
    assert experiment.verify_test_lock(output / "test-lock.json")["status"] == "PASS"
    first_media = output / payload["files"][0]["path"]
    first_media.write_bytes(b"changed")
    assert experiment.verify_test_lock(output / "test-lock.json")["status"] == "FAIL"


def test_metrics_include_confusion_window_recall_and_latency():
    records = [
        {"ground_truth": "RISK_PRECURSOR", "predicted_label": "RISK_PRECURSOR", "window_hit": True, "latency_ms": 100},
        {"ground_truth": "RISK_PRECURSOR", "predicted_label": "NORMAL_CONTROL", "window_hit": False, "latency_ms": None},
        {"ground_truth": "NORMAL_CONTROL", "predicted_label": "RISK_PRECURSOR", "window_hit": False, "latency_ms": 200},
        {"ground_truth": "NORMAL_CONTROL", "predicted_label": "NORMAL_CONTROL", "window_hit": False, "latency_ms": None},
    ]

    metrics = experiment.calculate_metrics(records)

    assert metrics["confusion_matrix"] == {"tp": 1, "tn": 1, "fp": 1, "fn": 1}
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["f1"] == 0.5
    assert metrics["high_risk_window_recall"] == 0.5
    assert metrics["latency_ms"]["p50"] == 150.0


def test_stability_requires_three_four_hour_non_mock_runs(tmp_path: Path):
    start = datetime(2026, 8, 26, 8, tzinfo=timezone(timedelta(hours=8)))
    rows = []
    for participant in experiment.PARTICIPANT_SPLITS:
        rows.append({
            "run_id": f"RUN-{participant}",
            "participant_id": participant,
            "started_at": start.isoformat(),
            "ended_at": (start + timedelta(hours=4)).isoformat(),
            "source_mode": "LIVE_DEVICE",
            "total_risk_events": 1,
            "false_alarms": 1,
            "system_exceptions": 0,
            "restarts": 0,
            "unhandled_exceptions": 0,
            "ruleset_version": "ruleset-final",
            "notes": "",
        })
    source = tmp_path / "stability.csv"
    output = tmp_path / "stability.json"
    experiment.write_csv(source, experiment.STABILITY_FIELDS, rows)

    payload = experiment.analyze_stability(source, output)

    assert payload["status"] == "COMPLETE"
    assert payload["totals"]["duration_hours"] == 12
    assert payload["totals"]["false_alarms_per_hour"] == 0.25
