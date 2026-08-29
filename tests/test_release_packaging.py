from __future__ import annotations

import json
import zipfile
from pathlib import Path

import fitz
import pytest

from scripts import assemble_submission, build_source_release, validate_fresh_release
from scripts.release_integrity import scan_text, scan_zip


PROFILE = {
    "school": "吉林大学",
    "contact_name": "张薇",
    "mobile": "".join(("139", "0000", "0000")),
    "submission_deadline": "2026-09-04",
    "retention_until": "2027-03-31",
    "online_entry_required": False,
    "online_url": "https://example.github.io/demo/",
    "online_username": "judge",
}


def write_submission_profile(root: Path) -> None:
    path = root / assemble_submission.PROFILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")


def write_pdf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for _ in range(3):
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_sensitive_scan_allows_blank_template_and_rejects_real_secret():
    assert scan_text(".env.example", "EZVIZ_APP_SECRET=\nEZVIZ_DEVICE_SERIAL=\n") == []

    findings = scan_text(".env", "EZVIZ_APP_SECRET=real-production-secret\n")

    assert [item.kind for item in findings] == ["credential_assignment"]


def test_sensitive_scan_rejects_personal_absolute_path():
    findings = scan_text("guide.md", "Run C:\\Users\\Alice\\private\\tool.exe")

    assert [item.kind for item in findings] == ["absolute_local_path"]


def test_sensitive_scan_rejects_unmasked_mobile_number():
    mobile = "".join(("139", "0000", "0000"))

    findings = scan_text("profile.json", json.dumps({"mobile": mobile}))

    assert [item.kind for item in findings] == ["mainland_mobile"]


def test_source_release_uses_allowlist_and_excludes_dot_env(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src/app.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "src/.env").write_text("EZVIZ_APP_SECRET=must-not-ship\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "outside.txt").write_text("not selected\n", encoding="utf-8")
    monkeypatch.setattr(build_source_release, "RECURSIVE_ROOTS", ("src",))
    monkeypatch.setattr(build_source_release, "EXACT_FILES", ("README.md",))
    monkeypatch.setattr(build_source_release, "REQUIRED_RELEASE_PATHS", ())
    output = tmp_path / "source.zip"

    result = build_source_release.build_source_release(root, output)

    assert result["privacy_scan"] == "PASS"
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "src/app.py" in names
    assert "src/.env" not in names
    assert "outside.txt" not in names
    assert "MANIFEST-SHA256.txt" in names


def test_source_release_fails_when_raw_media_enters_allowlisted_tree(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src/raw.mp4").write_bytes(b"private video")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setattr(build_source_release, "RECURSIVE_ROOTS", ("src",))
    monkeypatch.setattr(build_source_release, "EXACT_FILES", ("README.md",))
    monkeypatch.setattr(build_source_release, "REQUIRED_RELEASE_PATHS", ())

    with pytest.raises(ValueError, match="raw media"):
        build_source_release.build_source_release(root, tmp_path / "source.zip")


def test_source_release_fails_when_required_runtime_file_is_missing(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src/app.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setattr(build_source_release, "RECURSIVE_ROOTS", ("src",))
    monkeypatch.setattr(build_source_release, "EXACT_FILES", ("README.md",))
    monkeypatch.setattr(build_source_release, "REQUIRED_RELEASE_PATHS", ("src/required.py",))

    with pytest.raises(ValueError, match="required source release file is missing"):
        build_source_release.collect_source_files(root)


def test_source_release_excludes_untracked_files_when_git_index_is_available(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src/app.py").write_text("print('tracked')\n", encoding="utf-8")
    (root / "src/local-only.py").write_text("print('local')\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setattr(build_source_release, "RECURSIVE_ROOTS", ("src",))
    monkeypatch.setattr(build_source_release, "EXACT_FILES", ("README.md",))
    monkeypatch.setattr(build_source_release, "REQUIRED_RELEASE_PATHS", ())
    monkeypatch.setattr(
        build_source_release,
        "_tracked_paths",
        lambda _root: {"README.md", "src/app.py"},
    )

    selected = {
        name for _, name in build_source_release.collect_source_files(root)
    }

    assert selected == {"README.md", "src/app.py"}


def test_source_release_allows_only_checksum_pinned_external_file(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    model = root / "model.task"
    model.write_bytes(b"trusted runtime")
    monkeypatch.setattr(build_source_release, "RECURSIVE_ROOTS", ())
    monkeypatch.setattr(build_source_release, "EXACT_FILES", ("model.task",))
    monkeypatch.setattr(build_source_release, "REQUIRED_RELEASE_PATHS", ())
    monkeypatch.setattr(
        build_source_release,
        "PINNED_EXTERNAL_FILES",
        {"model.task": build_source_release.sha256_file(model)},
    )
    monkeypatch.setattr(build_source_release, "_tracked_paths", lambda _root: set())

    assert build_source_release.collect_source_files(root) == [(model, "model.task")]

    model.write_bytes(b"changed runtime")
    with pytest.raises(ValueError, match="checksum mismatch"):
        build_source_release.collect_source_files(root)


def test_source_release_default_roots_include_trajectory_and_scenes():
    assert "adapters" in build_source_release.RECURSIVE_ROOTS
    assert "scene-calibrations" in build_source_release.RECURSIVE_ROOTS
    assert "frontend/contracts" in build_source_release.RECURSIVE_ROOTS
    assert "deliverables/zy/pose-demo/scripts" in build_source_release.RECURSIVE_ROOTS
    assert (
        "deliverables/zhang-d2-snapshot-2026-08-15/batch-1"
        in build_source_release.RECURSIVE_ROOTS
    )
    assert "experiments/structured_scenarios" in build_source_release.RECURSIVE_ROOTS
    assert "backend/service/stream_buffer_service.py" in build_source_release.REQUIRED_RELEASE_PATHS
    assert (
        "deliverables/zy/pose-demo/scripts/recorded_replay_adapter.py"
        in build_source_release.REQUIRED_RELEASE_PATHS
    )
    assert "models/pose_landmarker_heavy.task" in build_source_release.PINNED_EXTERNAL_FILES


def test_fresh_release_resolves_windows_npm_cmd(monkeypatch):
    monkeypatch.setattr(validate_fresh_release.sys, "platform", "win32")
    monkeypatch.setattr(
        validate_fresh_release.shutil,
        "which",
        lambda name: "D:/node.js/npm.cmd" if name == "npm.cmd" else None,
    )

    assert validate_fresh_release._resolve_npm("npm") == "D:/node.js/npm.cmd"


def test_fresh_release_negative_runtime_is_outside_extracted_source(tmp_path):
    extracted_source = tmp_path / "source"
    replay_runtime = validate_fresh_release._negative_runtime_root(extracted_source)

    assert replay_runtime.parent == tmp_path
    assert replay_runtime != extracted_source


def test_packaged_environment_template_covers_live_v13_runtime():
    template = (Path(__file__).parents[1] / "packaging" / ".env.example").read_text(
        encoding="utf-8"
    )
    required = (
        "YINGMU_CAPTURE_MEDIA_MODE=VIDEO",
        "YINGMU_RULESET_VERSION=ruleset-v1.4",
        "YINGMU_FOREWARNING_RULESET_VERSION=ruleset-v1.4",
        "YINGMU_GAIT_ADAPTER=contracts.v1.gait_adapter_v14:run",
        "YINGMU_TRAJECTORY_ADAPTER=adapters.trajectory_adapter:run",
        "YINGMU_SCENE_CONFIG_DIR=scene-calibrations",
        "YINGMU_STREAM_BUFFER_ENABLED=false",
        "EZVIZ_LIVE_PLAYBACK_VERIFIED=false",
        "EZVIZ_VOICE_VERIFIED=false",
    )
    assert all(item in template for item in required)


def test_zip_scan_rejects_runtime_env(tmp_path):
    path = tmp_path / "release.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("app/.env", "EZVIZ_APP_SECRET=real-production-secret\n")
        archive.writestr("app/__init__.py", "")

    findings = scan_zip(path)

    assert any(item.kind == "forbidden_path" for item in findings)
    assert not any(item.kind == "invalid_text_encoding" for item in findings)


def test_experiment_gate_rejects_handcrafted_empty_dual_track_result():
    payload = {
        "schema_version": "three-participant-results/2.0",
        "status": "COMPLETE",
        "test_lock_sha256": "a",
        "rule_freeze_sha256": "b",
        "evaluation_spec_sha256": "c",
        "primary_result": {
            "participant_id": "P03", "config_id": "A", "sample_count": 24,
            "baseline_reference_count": 8, "result_record_count": 32,
            "effect_thresholds": None,
        },
        "metrics": {"instant_event": {}, "gait_trend": {}},
    }

    errors = assemble_submission.validate_experiment(payload)

    assert "analysis errors" in " ".join(errors)
    assert "metrics are incomplete" in " ".join(errors)


def test_stability_gate_requires_auditable_runs():
    payload = {
        "status": "COMPLETE",
        "generated_at": "2026-08-28T18:10:00+08:00",
        "study_scope": {
            "household_scope": "SAME_HOUSEHOLD",
            "camera_count": 1,
            "schedule": "SEQUENTIAL_NON_OVERLAPPING",
            "single_person_per_segment": False,
            "co_presence_limitation": "same household and shared camera",
        },
        "runs": [
            {
                "participant_id": participant,
                "duration_hours": 4,
                "started_at": f"2026-08-28T{start}:00:00+08:00",
                "ended_at": f"2026-08-28T{end}:00:00+08:00",
                "source_mode": "LIVE_DEVICE",
                "ruleset_version": "ruleset-v1.2",
                "forewarning_ruleset_version": "ruleset-v1.3-min",
                "total_risk_events": 0,
                "false_alarms": 0,
                "system_exceptions": 0,
                "restarts": 0,
                "unhandled_exceptions": 0,
            }
            for participant, start, end in (
                ("P01", "06", "10"),
                ("P02", "10", "14"),
                ("P03", "14", "18"),
            )
        ],
        "totals": {
            "duration_hours": 12,
            "risk_events": 0,
            "false_alarms": 0,
            "false_alarms_per_hour": 0,
            "system_exceptions": 0,
            "restarts": 0,
            "unhandled_exceptions": 0,
        },
        "errors": [],
    }

    assert assemble_submission.validate_stability(payload) == []


def test_stability_gate_rejects_inconsistent_provenance_and_totals():
    payload = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "experiments/three-participant/results/stability-summary.json"
        ).read_text(encoding="utf-8")
    )
    payload["generated_at"] = "2026-08-28T20:00:00+08:00"
    payload["runs"][0]["ruleset_version"] = "v2.1.0-frozen"
    payload["totals"]["risk_events"] = 99

    errors = assemble_submission.validate_stability(payload)

    assert any("generated_at" in error for error in errors)
    assert any("ruleset_version" in error for error in errors)
    assert any("risk_events" in error for error in errors)


def test_code_program_package_has_official_root_structure(tmp_path):
    source_zip = tmp_path / "source.zip"
    windows_zip = tmp_path / "windows.zip"
    output = tmp_path / "official.zip"
    with zipfile.ZipFile(source_zip, "w") as archive:
        archive.writestr("src/app.py", "print('ok')\n")
    with zipfile.ZipFile(windows_zip, "w") as archive:
        archive.writestr("YingMuShouWang.exe", b"MZ")

    assemble_submission.build_code_program_package(source_zip, windows_zip, output, PROFILE)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "01_源码/src/app.py" in names
    assert "02_Windows程序/YingMuShouWang.exe" in names
    assert "README-先读.txt" in names
    assert "MANIFEST-SHA256.txt" in names


def test_final_pdf_gate_rejects_pending_markers(tmp_path):
    path = tmp_path / "report.pdf"
    write_pdf(path, "PENDING_REAL_DATA " + "draft evidence " * 200)

    errors = assemble_submission._validate_pdf(path, reject_markers=True)

    assert any("draft or required markers" in error for error in errors)


def test_online_entry_gate_requires_all_acceptance_fields(tmp_path):
    path = tmp_path / "online-entry-verification.json"
    payload = {
        "status": "COMPLETE",
        "url": PROFILE["online_url"],
        "correct_login_passed": True,
        "wrong_login_rejected": True,
        "routes_passed": True,
        "mobile_passed": True,
        "mock_only": True,
        "privacy_scan_passed": True,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert assemble_submission._validate_online_verification(path, PROFILE) == []
    payload["mock_only"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert "mock_only" in " ".join(assemble_submission._validate_online_verification(path, PROFILE))


def test_online_entry_is_skipped_when_profile_marks_it_optional(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    profile = dict(PROFILE)
    profile.update({
        "online_entry_required": False,
        "online_url": "",
        "online_username": "",
    })
    path = root / assemble_submission.PROFILE
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(profile), encoding="utf-8")

    loaded = assemble_submission.load_profile(path)
    gates, _ = assemble_submission.evaluate_gates(root, "draft", loaded)
    online = next(item for item in gates if item["gate"] == "online_entry")

    assert online == {
        "gate": "online_entry",
        "status": "SKIPPED_OPTIONAL",
        "errors": [],
    }


def test_draft_assembly_is_explicitly_incomplete_when_real_evidence_is_missing(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    write_submission_profile(root)
    output = tmp_path / "output"

    report = assemble_submission.assemble(root, output, "draft")

    assert report["status"] == "INCOMPLETE"
    status_path = output / "SUBMISSION_STATUS-draft.json"
    persisted = json.loads(status_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "INCOMPLETE"
    assert any(gate["gate"] == "experiment" for gate in persisted["gates"])
    assert not (output / "萤目守望-提交材料-draft/SUBMISSION_STATUS.json").exists()


def test_final_assembly_refuses_to_create_package_when_gates_are_incomplete(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    write_submission_profile(root)
    output = tmp_path / "output"

    report = assemble_submission.assemble(root, output, "final")

    assert report["status"] == "INCOMPLETE"
    assert (output / "SUBMISSION_STATUS-final.json").is_file()
    assert not (output / "萤目守望-正式提交材料.zip").exists()
