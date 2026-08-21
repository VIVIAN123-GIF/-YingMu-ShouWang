from __future__ import annotations

import json
import zipfile

import pytest

from scripts import assemble_submission, build_source_release
from scripts.release_integrity import scan_text, scan_zip


def test_sensitive_scan_allows_blank_template_and_rejects_real_secret():
    assert scan_text(".env.example", "EZVIZ_APP_SECRET=\nEZVIZ_DEVICE_SERIAL=\n") == []

    findings = scan_text(".env", "EZVIZ_APP_SECRET=real-production-secret\n")

    assert [item.kind for item in findings] == ["credential_assignment"]


def test_sensitive_scan_rejects_personal_absolute_path():
    findings = scan_text("guide.md", "Run C:\\Users\\Alice\\private\\tool.exe")

    assert [item.kind for item in findings] == ["absolute_local_path"]


def test_source_release_uses_allowlist_and_excludes_dot_env(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src/app.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "src/.env").write_text("EZVIZ_APP_SECRET=must-not-ship\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "outside.txt").write_text("not selected\n", encoding="utf-8")
    monkeypatch.setattr(build_source_release, "RECURSIVE_ROOTS", ("src",))
    monkeypatch.setattr(build_source_release, "EXACT_FILES", ("README.md",))
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

    with pytest.raises(ValueError, match="raw media"):
        build_source_release.build_source_release(root, tmp_path / "source.zip")


def test_zip_scan_rejects_runtime_env(tmp_path):
    path = tmp_path / "release.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("app/.env", "EZVIZ_APP_SECRET=real-production-secret\n")
        archive.writestr("app/__init__.py", "")

    findings = scan_zip(path)

    assert any(item.kind == "forbidden_path" for item in findings)
    assert not any(item.kind == "invalid_text_encoding" for item in findings)


def test_experiment_gate_requires_p03_and_all_ablations():
    payload = {
        "status": "COMPLETE",
        "test_lock_sha256": "a",
        "rule_freeze_sha256": "b",
        "primary_result": {"participant_id": "P03", "config_id": "A", "sample_count": 24},
        "participant_results": {key: {"sample_count": 24} for key in ("P01", "P02", "P03")},
        "ablation_results": {key: {"sample_count": 24} for key in ("A", "B", "C", "D")},
    }

    assert assemble_submission.validate_experiment(payload) == []
    payload["ablation_results"]["D"]["sample_count"] = 23
    assert "ablation D" in " ".join(assemble_submission.validate_experiment(payload))


def test_stability_gate_requires_three_four_hour_runs():
    payload = {
        "status": "COMPLETE",
        "runs": [
            {"participant_id": participant, "duration_hours": 4}
            for participant in ("P01", "P02", "P03")
        ],
        "totals": {"duration_hours": 12},
    }

    assert assemble_submission.validate_stability(payload) == []


def test_draft_assembly_is_explicitly_incomplete_when_real_evidence_is_missing(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "output"

    report = assemble_submission.assemble(root, output, "draft")

    assert report["status"] == "INCOMPLETE"
    status_path = output / "萤目守望-提交包-draft/SUBMISSION_STATUS.json"
    persisted = json.loads(status_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "INCOMPLETE"
    assert any(gate["gate"] == "experiment" for gate in persisted["gates"])


def test_final_assembly_refuses_to_create_package_when_gates_are_incomplete(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "output"

    report = assemble_submission.assemble(root, output, "final")

    assert report["status"] == "INCOMPLETE"
    assert (output / "SUBMISSION_STATUS-final.json").is_file()
    assert not (output / "萤目守望-提交包-final.zip").exists()
