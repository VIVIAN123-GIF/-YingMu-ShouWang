from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import three_participant_experiment as experiment


@pytest.fixture(autouse=True)
def stable_repository_state(monkeypatch):
    monkeypatch.setattr(experiment, "_repository_state_errors", lambda _commit: [])
    monkeypatch.setattr(
        experiment,
        "_tracked_repository_path",
        lambda path: f"scripts/{Path(path).name}",
    )


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


def test_frozen_evaluation_spec_has_two_tracks_and_fixed_denominators():
    spec = experiment.load_evaluation_spec(experiment.DEFAULT_EVALUATION_SPEC)

    assert spec["evaluation_config"] == "A"
    assert spec["effect_thresholds"] is None
    assert spec["reporting_policy"]["global_binary_accuracy_allowed"] is False
    assert spec["denominators"] == {
        "p03_locked_clips": 32,
        "p03_baseline_clips": 8,
        "p03_evaluation_clips": 24,
        "instant_positive_clips": 4,
        "transition_truth_clips": 12,
        "orange_forbidden_evaluation_clips": 20,
        "gait_trend_target_clips": 8,
        "normal_walk_reference_clips": 4,
    }
    assert spec["scenarios"]["POS_RAPID_RISE_SWAY"]["track"] == "INSTANT_POSITIVE"
    assert spec["scenarios"]["POS_ASYMMETRIC_STEP"]["track"] == "GAIT_TREND_TARGET"


def _frozen_test_inputs(tmp_path: Path):
    manifest, media_root = _completed_manifest(tmp_path)
    lock_dir = tmp_path / "TEST_LOCKED"
    experiment.lock_test_set(manifest, media_root, lock_dir)
    model = tmp_path / "model.task"
    executor = tmp_path / "executor.py"
    model.write_bytes(b"model")
    executor.write_text("# frozen executor\n", encoding="utf-8")
    rehearsal_report = tmp_path / "executor-rehearsal.json"
    experiment.write_json(rehearsal_report, {
        "schema_version": "p03-executor-rehearsal/1.0",
        "status": "PASS",
        "config_id": "A",
        "executor_sha256": experiment.sha256_file(executor),
        "evaluation_spec_sha256": experiment.sha256_file(experiment.DEFAULT_EVALUATION_SPEC),
        "deterministic_rerun": True,
        "non_overwrite_verified": True,
        "participants": {
            "P01": {"baseline_records": 8, "evaluation_records": 24},
            "P02": {"baseline_records": 8, "evaluation_records": 24},
        },
    })
    artifacts = {
        "ruleset": Path("contracts/v1/rulesets/ruleset-v1.2.json").resolve(),
        "forewarning_ruleset": Path("contracts/v1/rulesets/ruleset-v1.3-min.json").resolve(),
        "model": model,
        "evaluation_spec": experiment.DEFAULT_EVALUATION_SPEC,
        "evaluation_protocol": experiment.DEFAULT_EVALUATION_PROTOCOL,
        "inference_schema": experiment.DEFAULT_INFERENCE_SCHEMA,
        "rehearsal_schema": experiment.DEFAULT_REHEARSAL_SCHEMA,
        "executor": executor,
        "rehearsal_report": rehearsal_report,
    }
    lock_file = lock_dir / "test-lock.json"
    freeze = {
        "schema_version": "three-participant-rule-freeze/2.0",
        "status": "FROZEN",
        "git_commit": "a" * 40,
        "git_dirty": False,
        "executor_repository_path": f"scripts/{executor.name}",
        "test_lock_sha256": experiment.sha256_file(lock_file),
        "test_execution_allowed": True,
        **{
            name: {"path": str(path), "sha256": experiment.sha256_file(path)}
            for name, path in artifacts.items()
        },
    }
    freeze_file = tmp_path / "rule-freeze.json"
    experiment.write_json(freeze_file, freeze)
    return manifest, lock_file, freeze_file, freeze


def _machine_record(row: dict[str, str], freeze: dict) -> dict:
    evidence = {
        "evidence_id": f"evi-{row['clip_id']}-00",
        "ingestion_order": 0,
        "evidence_type": "relative_speed_change",
        "signal_family": None,
        "confidence": 0.9,
        "data_quality": 0.9,
        "severity": 0.5,
        "current_value": 1.0,
        "observation_ids": [f"obs-{row['clip_id']}-00"],
        "timestamp_ms": 1000,
        "first_detected_at_ms": 1000,
    }
    evaluation = row["record_role"] == "EVALUATION"
    return {
        "clip_id": row["clip_id"],
        "participant_id": "P03",
        "scenario_id": row["scenario_id"],
        "record_role": row["record_role"],
        "config_id": "A",
        "asset_sha256": row["sha256"],
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "ruleset_version": "ruleset-v1.2",
        "forewarning_ruleset_version": "ruleset-v1.3-min",
        "model_sha256": freeze["model"]["sha256"],
        "executor_sha256": freeze["executor"]["sha256"],
        "evaluation_spec_sha256": freeze["evaluation_spec"]["sha256"],
        "modules": {
            "GAIT": {"status": "NO_EVIDENCE", "error_code": None},
            "TRAJECTORY": {"status": "NO_EVIDENCE", "error_code": None},
        },
        "evidences": [evidence] if evaluation else [],
        "rule_traces": [{
            "trace_id": f"trace-{row['clip_id']}-00",
            "trigger_evidence_id": evidence["evidence_id"],
            "evaluated_at_ms": 1000,
            "previous_state": "GREEN",
            "next_state": "GREEN",
            "previous_status": None,
            "next_status": None,
            "matched_rule": "NO_MATCH",
            "event_created": False,
        }] if evaluation else [],
        "risk_event_count": 0,
        "forewarning": {
            "assessment_status": "INSUFFICIENT",
            "baseline_status": "INSUFFICIENT",
            "human_risk": 0.0,
            "personal_deviation": None,
            "instant_index": 0.0,
            "short_30s_index": 0.0,
            "trend_3min_index": 0.0,
            "degradation_reasons": ["HUMAN_EVIDENCE_INSUFFICIENT"],
        },
        "record_error_code": None,
        "attempts": [{
            "attempt_id": f"attempt-{row['clip_id']}-01",
            "started_at": "2026-08-26T08:00:00+08:00",
            "completed_at": "2026-08-26T08:00:01+08:00",
            "status": "SUCCESS",
            "error_code": None,
        }],
    }


def _inference_payload(lock_file: Path, freeze_file: Path, freeze: dict) -> dict:
    locked_rows = experiment.read_csv(lock_file.parent / "locked-manifest.csv")
    records = [_machine_record(row, freeze) for row in locked_rows]
    return {
        "schema_version": "p03-inference-results/1.0",
        "participant_id": "P03",
        "config_id": "A",
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "execution_id": "execution-p03-test-001",
        "generated_at": "2026-08-26T09:00:00+08:00",
        "database_isolation_id": "p03-isolated-test-db-001",
        "baseline_seed_sha256": "d" * 64,
        "test_lock_sha256": experiment.sha256_file(lock_file),
        "rule_freeze_sha256": experiment.sha256_file(freeze_file),
        "records_sha256": experiment.sha256_json(records),
        "records": records,
    }


def test_dual_track_analyzer_accepts_a_only_machine_results(tmp_path: Path):
    manifest, lock_file, freeze_file, freeze = _frozen_test_inputs(tmp_path)
    source = tmp_path / "inference.json"
    experiment.write_json(source, _inference_payload(lock_file, freeze_file, freeze))

    payload = experiment.analyze_inference_results(
        manifest, source, lock_file, freeze_file,
        experiment.DEFAULT_EVALUATION_SPEC, tmp_path / "final",
    )

    assert payload["status"] == "COMPLETE"
    assert payload["schema_version"] == "three-participant-results/2.0"
    assert payload["primary_result"]["result_record_count"] == 32
    assert set(payload["metrics"]) == {"instant_event", "gait_trend"}
    assert "accuracy" not in json.dumps(payload).lower()
    assert payload["metrics"]["instant_event"]["forbidden_orange_events"]["denominator_clips"] == 20
    comparisons = payload["metrics"]["gait_trend"]["predeclared_median_differences"]
    assert all(
        metric["status"] == "NOT_ESTIMABLE"
        for comparison in comparisons
        for metric in comparison["indices"].values()
    )


def test_module_failure_remains_in_denominator_and_reduces_coverage(tmp_path: Path):
    manifest, lock_file, freeze_file, freeze = _frozen_test_inputs(tmp_path)
    source_payload = _inference_payload(lock_file, freeze_file, freeze)
    failed = source_payload["records"][8]
    failed["modules"]["GAIT"] = {"status": "FAILED", "error_code": "POSE_INFERENCE_FAILED"}
    failed["evidences"] = []
    failed["rule_traces"] = []
    failed["risk_event_count"] = 0
    failed["forewarning"] = None
    failed["record_error_code"] = "PARTIAL_ALGORITHM_FAILURE"
    failed["attempts"] = [{
        "attempt_id": "attempt-failed-01",
        "started_at": "2026-08-26T08:00:00+08:00",
        "completed_at": "2026-08-26T08:00:01+08:00",
        "status": "FAILED",
        "error_code": "PARTIAL_ALGORITHM_FAILURE",
    }]
    source_payload["records_sha256"] = experiment.sha256_json(source_payload["records"])
    source = tmp_path / "inference.json"
    experiment.write_json(source, source_payload)

    payload = experiment.analyze_inference_results(
        manifest, source, lock_file, freeze_file,
        experiment.DEFAULT_EVALUATION_SPEC, tmp_path / "final",
    )

    assert payload["status"] == "COMPLETE"
    trend = payload["metrics"]["gait_trend"]
    assert trend["module_status_counts"]["GAIT"]["FAILED"] == 1
    assert trend["assessment_status_counts"]["MISSING"] == 1
    assert payload["metrics"]["instant_event"]["adjudication_coverage"]["numerator"] == 23


def test_no_transition_orange_is_reported_as_forbidden_and_nonconformant(tmp_path: Path):
    manifest, lock_file, freeze_file, freeze = _frozen_test_inputs(tmp_path)
    source_payload = _inference_payload(lock_file, freeze_file, freeze)
    target = next(
        item for item in source_payload["records"]
        if item["scenario_id"] == "POS_ASYMMETRIC_STEP"
    )
    target["rule_traces"][0].update({
        "next_state": "ORANGE",
        "next_status": "INTERVENING",
        "matched_rule": "R-FALL-02",
        "event_created": True,
    })
    target["risk_event_count"] = 1
    source_payload["records_sha256"] = experiment.sha256_json(source_payload["records"])
    source = tmp_path / "inference.json"
    experiment.write_json(source, source_payload)

    payload = experiment.analyze_inference_results(
        manifest, source, lock_file, freeze_file,
        experiment.DEFAULT_EVALUATION_SPEC, tmp_path / "final",
    )

    instant = payload["metrics"]["instant_event"]
    assert instant["forbidden_orange_events"]["event_count"] == 1
    assert instant["adjudication_conformance"]["numerator"] == 23
    assert instant["adjudication_conformance"]["denominator"] == 24


def test_missing_machine_result_stays_in_denominator_and_is_incomplete(tmp_path: Path):
    manifest, lock_file, freeze_file, freeze = _frozen_test_inputs(tmp_path)
    source_payload = _inference_payload(lock_file, freeze_file, freeze)
    source_payload["records"].pop()
    source_payload["records_sha256"] = experiment.sha256_json(source_payload["records"])
    source = tmp_path / "inference.json"
    experiment.write_json(source, source_payload)

    payload = experiment.analyze_inference_results(
        manifest, source, lock_file, freeze_file,
        experiment.DEFAULT_EVALUATION_SPEC, tmp_path / "final",
    )

    assert payload["status"] == "INCOMPLETE"
    assert any("missing inference result" in item for item in payload["errors"])
    modules = payload["metrics"]["gait_trend"]["module_status_counts"]
    assert modules["GAIT"]["MISSING_RESULT"] == 1
    assert (tmp_path / "final" / "experiment-results.json").is_file()


def test_manual_result_edit_without_integrity_update_is_rejected(tmp_path: Path):
    manifest, lock_file, freeze_file, freeze = _frozen_test_inputs(tmp_path)
    source_payload = _inference_payload(lock_file, freeze_file, freeze)
    source_payload["records"][0]["forewarning"]["instant_index"] = 0.99
    source = tmp_path / "inference.json"
    experiment.write_json(source, source_payload)

    payload = experiment.analyze_inference_results(
        manifest, source, lock_file, freeze_file,
        experiment.DEFAULT_EVALUATION_SPEC, tmp_path / "final",
    )

    assert payload["status"] == "INCOMPLETE"
    assert "records_sha256 does not match" in " ".join(payload["errors"])


def _evidence(
    evidence_id: str,
    evidence_type: str,
    order: int,
    timestamp_ms: int,
    observation_id: str = "obs-transition",
):
    spec = experiment.load_evaluation_spec(experiment.DEFAULT_EVALUATION_SPEC)
    family = next((
        family for family, types in spec["signal_families"].items()
        if evidence_type in types
    ), None)
    return {
        "evidence_id": evidence_id,
        "ingestion_order": order,
        "evidence_type": evidence_type,
        "signal_family": family,
        "confidence": 0.9,
        "data_quality": 0.9,
        "severity": 0.5,
        "current_value": 1.0,
        "observation_ids": [observation_id],
        "timestamp_ms": timestamp_ms,
        "first_detected_at_ms": timestamp_ms,
    }


def test_foot_evidences_count_as_one_independent_family():
    spec = experiment.load_evaluation_spec(experiment.DEFAULT_EVALUATION_SPEC)
    record = {
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "evidences": [
            _evidence("evi-transition", "sit_to_stand_transition", 0, 1000),
            _evidence("evi-support", "support_base_change", 1, 2000),
            _evidence("evi-step", "compensatory_step", 2, 3000),
        ]
    }

    families, _signals = experiment._transition_bound_signals(record, spec)
    traces = experiment._expected_rule_traces(
        record, Path("contracts/v1/rulesets/ruleset-v1.2.json")
    )

    assert families == {"feet"}
    assert traces[-1]["matched_rule"] == "R-FALL-11"
    assert traces[-1]["next_state"] == "YELLOW"
    assert traces[-1]["next_status"] is None


@pytest.mark.parametrize(
    ("evidences", "matched_rule", "next_state"),
    [
        ([_evidence("evi-review", "assessment_indeterminate", 0, 1000)], "R-FALL-09", "UNKNOWN"),
        ([
            _evidence("evi-transition", "sit_to_stand_transition", 0, 1000),
            _evidence("evi-trunk", "trunk_sway", 1, 2000),
        ], "R-FALL-11", "YELLOW"),
        ([
            _evidence("evi-rapid", "rapid_rise", 0, 1000),
            _evidence("evi-gait", "gait_instability", 1, 2000),
        ], "R-FALL-08", "YELLOW"),
        ([_evidence("evi-rapid", "rapid_rise", 0, 1000)], "R-FALL-12", "YELLOW"),
    ],
)
def test_review_rules_keep_next_status_null(evidences, matched_rule, next_state):
    record = {
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "evidences": evidences,
    }

    traces = experiment._expected_rule_traces(
        record, Path("contracts/v1/rulesets/ruleset-v1.2.json")
    )

    assert traces[-1]["matched_rule"] == matched_rule
    assert traces[-1]["next_state"] == next_state
    assert traces[-1]["next_status"] is None


@pytest.mark.parametrize(
    ("signal_offset_ms", "observation_id", "expected"),
    [
        (0, "obs-transition", True),
        (30_000, "obs-transition", True),
        (-1, "obs-transition", False),
        (30_001, "obs-transition", False),
        (1_000, "obs-other", False),
    ],
)
def test_transition_binding_uses_same_observation_and_closed_30s_window(
    signal_offset_ms, observation_id, expected
):
    spec = experiment.load_evaluation_spec(experiment.DEFAULT_EVALUATION_SPEC)
    record = {
        "evidences": [
            _evidence("evi-transition", "sit_to_stand_transition", 0, 10_000),
            _evidence(
                "evi-trunk", "trunk_sway", 1, 10_000 + signal_offset_ms,
                observation_id,
            ),
        ]
    }

    families, _signals = experiment._transition_bound_signals(record, spec)

    assert bool(families) is expected


def test_trace_replay_covers_event_creation_and_active_followup():
    record = {
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "evidences": [
            _evidence("evi-transition", "sit_to_stand_transition", 0, 1000),
            _evidence("evi-trunk", "trunk_sway", 1, 2000),
            _evidence("evi-drift", "post_rise_lateral_drift", 2, 3000),
            _evidence("evi-relative", "relative_speed_change", 3, 4000),
        ],
    }

    traces = experiment._expected_rule_traces(
        record, Path("contracts/v1/rulesets/ruleset-v1.2.json")
    )
    record["rule_traces"] = [
        {"trace_id": f"trace-{index}", **trace}
        for index, trace in enumerate(traces)
    ]

    assert [item["matched_rule"] for item in traces] == [
        "R-FALL-01", "R-FALL-11", "R-FALL-02", "NO_MATCH",
    ]
    assert traces[2]["event_created"] is True
    assert traces[3]["previous_status"] == "INTERVENING"
    assert experiment._trace_sequence_conforms(
        record, Path("contracts/v1/rulesets/ruleset-v1.2.json")
    ) is True


def test_null_evidence_quality_is_incomplete_without_crashing(tmp_path: Path):
    manifest, lock_file, freeze_file, freeze = _frozen_test_inputs(tmp_path)
    source_payload = _inference_payload(lock_file, freeze_file, freeze)
    source_payload["records"][8]["evidences"][0]["confidence"] = None
    source_payload["records_sha256"] = experiment.sha256_json(source_payload["records"])
    source = tmp_path / "inference.json"
    experiment.write_json(source, source_payload)

    payload = experiment.analyze_inference_results(
        manifest, source, lock_file, freeze_file,
        experiment.DEFAULT_EVALUATION_SPEC, tmp_path / "final",
    )

    assert payload["status"] == "INCOMPLETE"
    assert "confidence is required" in " ".join(payload["errors"])
    assert payload["metrics"]["gait_trend"]["module_status_counts"]["GAIT"]["MISSING_RESULT"] == 1


def test_missing_result_keeps_scene_index_raw_denominator(tmp_path: Path):
    manifest, lock_file, freeze_file, freeze = _frozen_test_inputs(tmp_path)
    source_payload = _inference_payload(lock_file, freeze_file, freeze)
    missing = source_payload["records"].pop()
    source_payload["records_sha256"] = experiment.sha256_json(source_payload["records"])
    source = tmp_path / "inference.json"
    experiment.write_json(source, source_payload)

    payload = experiment.analyze_inference_results(
        manifest, source, lock_file, freeze_file,
        experiment.DEFAULT_EVALUATION_SPEC, tmp_path / "final",
    )

    scenario = payload["metrics"]["gait_trend"]["engineering_indices_by_scenario"][missing["scenario_id"]]
    assert len(scenario["human_risk"]["raw"]) == 4
    assert any(item["assessment_status"] is None for item in scenario["human_risk"]["raw"])


def test_legacy_prediction_template_is_prohibited(tmp_path: Path):
    try:
        experiment.generate_predictions(tmp_path / "manifest.csv", tmp_path / "predictions.csv")
    except ValueError as exc:
        assert "LEGACY_PREDICTIONS_PROHIBITED" in str(exc)
    else:
        raise AssertionError("legacy predictions must be rejected")


def test_verify_freeze_detects_executor_tampering(tmp_path: Path):
    _, lock_file, freeze_file, freeze = _frozen_test_inputs(tmp_path)
    Path(freeze["executor"]["path"]).write_text("changed\n", encoding="utf-8")

    report = experiment.verify_freeze(freeze_file, lock_file)

    assert report["status"] == "FAIL"
    assert "frozen executor is missing or changed" in report["errors"]


def test_verify_freeze_rejects_changed_head(tmp_path: Path, monkeypatch):
    _, lock_file, freeze_file, _freeze = _frozen_test_inputs(tmp_path)
    monkeypatch.setattr(
        experiment,
        "_repository_state_errors",
        lambda _commit: ["current HEAD differs from the frozen commit"],
    )

    report = experiment.verify_freeze(freeze_file, lock_file)

    assert report["status"] == "FAIL"
    assert "current HEAD differs from the frozen commit" in report["errors"]


def test_freeze_rejects_executor_outside_tracked_repository(tmp_path: Path, monkeypatch):
    _, lock_file, _, _ = _frozen_test_inputs(tmp_path)
    model = tmp_path / "model.task"
    executor = tmp_path / "executor.py"
    rehearsal = tmp_path / "rehearsal.json"
    model.write_bytes(b"model")
    executor.write_text("# external\n", encoding="utf-8")
    experiment.write_json(rehearsal, {
        "schema_version": "p03-executor-rehearsal/1.0",
        "status": "PASS",
        "config_id": "A",
        "executor_sha256": experiment.sha256_file(executor),
        "evaluation_spec_sha256": experiment.sha256_file(experiment.DEFAULT_EVALUATION_SPEC),
        "deterministic_rerun": True,
        "non_overwrite_verified": True,
        "participants": {
            "P01": {"baseline_records": 8, "evaluation_records": 24},
            "P02": {"baseline_records": 8, "evaluation_records": 24},
        },
    })
    monkeypatch.setattr(experiment, "_tracked_repository_path", lambda _path: None)

    with pytest.raises(ValueError, match="P03_EXECUTOR_NOT_TRACKED"):
        experiment.freeze_rules(
            lock_file,
            Path("contracts/v1/rulesets/ruleset-v1.2.json"),
            Path("contracts/v1/rulesets/ruleset-v1.3-min.json"),
            model,
            experiment.DEFAULT_EVALUATION_SPEC,
            experiment.DEFAULT_EVALUATION_PROTOCOL,
            experiment.DEFAULT_INFERENCE_SCHEMA,
            experiment.DEFAULT_REHEARSAL_SCHEMA,
            executor,
            rehearsal,
            tmp_path / "freeze.json",
            allow_dirty=True,
        )


def test_freeze_rejects_wrong_ruleset_version(tmp_path: Path):
    _, lock_file, _, _ = _frozen_test_inputs(tmp_path)
    wrong_ruleset = tmp_path / "ruleset.json"
    wrong_ruleset.write_text('{"ruleset_version":"ruleset-v9"}', encoding="utf-8")

    with pytest.raises(ValueError, match="P03_RULESET_VERSION_INVALID"):
        experiment.freeze_rules(
            lock_file,
            wrong_ruleset,
            Path("contracts/v1/rulesets/ruleset-v1.3-min.json"),
            tmp_path / "missing-model.task",
            experiment.DEFAULT_EVALUATION_SPEC,
            experiment.DEFAULT_EVALUATION_PROTOCOL,
            experiment.DEFAULT_INFERENCE_SCHEMA,
            experiment.DEFAULT_REHEARSAL_SCHEMA,
            tmp_path / "missing-executor.py",
            tmp_path / "missing-rehearsal.json",
            tmp_path / "freeze.json",
            allow_dirty=True,
        )


def test_rehearsal_freeze_binds_both_rulesets_rubric_schema_and_executor(tmp_path: Path):
    _, lock_file, _, _ = _frozen_test_inputs(tmp_path)
    model = tmp_path / "freeze-model.task"
    executor = tmp_path / "freeze-executor.py"
    model.write_bytes(b"model")
    executor.write_text("# executor\n", encoding="utf-8")
    rehearsal_report = tmp_path / "rehearsal.json"
    experiment.write_json(rehearsal_report, {
        "schema_version": "p03-executor-rehearsal/1.0",
        "status": "PASS",
        "config_id": "A",
        "executor_sha256": experiment.sha256_file(executor),
        "evaluation_spec_sha256": experiment.sha256_file(experiment.DEFAULT_EVALUATION_SPEC),
        "deterministic_rerun": True,
        "non_overwrite_verified": True,
        "participants": {
            "P01": {"baseline_records": 8, "evaluation_records": 24},
            "P02": {"baseline_records": 8, "evaluation_records": 24},
        },
    })
    output = tmp_path / "rehearsal-freeze.json"

    payload = experiment.freeze_rules(
        lock_file,
        Path("contracts/v1/rulesets/ruleset-v1.2.json"),
        Path("contracts/v1/rulesets/ruleset-v1.3-min.json"),
        model,
        experiment.DEFAULT_EVALUATION_SPEC,
        experiment.DEFAULT_EVALUATION_PROTOCOL,
        experiment.DEFAULT_INFERENCE_SCHEMA,
        experiment.DEFAULT_REHEARSAL_SCHEMA,
        executor,
        rehearsal_report,
        output,
        allow_dirty=True,
    )

    assert payload["schema_version"] == "three-participant-rule-freeze/2.0"
    assert payload["status"] in {"FROZEN", "REHEARSAL_ONLY"}
    assert payload["test_execution_allowed"] is (payload["status"] == "FROZEN")
    assert all(
        payload[key]["sha256"]
        for key in (
            "ruleset", "forewarning_ruleset", "model", "evaluation_spec",
            "evaluation_protocol", "inference_schema", "rehearsal_schema",
            "executor", "rehearsal_report",
        )
    )


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
