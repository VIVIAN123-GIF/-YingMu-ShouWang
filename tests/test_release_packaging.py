from __future__ import annotations

import json
import zipfile
from pathlib import Path

import fitz
import pytest

from scripts import assemble_submission, build_source_release
from scripts.release_integrity import scan_text, scan_zip


PROFILE = {
    "school": "吉林大学",
    "contact_name": "张薇",
    "mobile": "".join(("139", "0000", "0000")),
    "submission_deadline": "2026-09-04",
    "retention_until": "2027-03-31",
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
