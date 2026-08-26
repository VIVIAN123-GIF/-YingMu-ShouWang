"""Assemble a draft or final delivery package with evidence-based release gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

import fitz

from scripts.build_final_documents import load_profile, official_stem
from scripts.release_integrity import manifest_lines, scan_files, scan_zip, sha256_file


EVIDENCE_FILES = {
    "experiment": Path("experiments/three-participant/results/final/experiment-results.json"),
    "stability": Path("experiments/three-participant/results/stability-summary.json"),
    "urfd": Path("experiments/three-participant/results/urfd-results.json"),
    "golden_loops": Path("experiments/three-participant/results/golden-loop-results.json"),
    "authorization": Path("experiments/three-participant/results/authorization-summary.json"),
    "video_verification": Path("final-delivery/private-input/video-verification.json"),
    "external_windows": Path("final-delivery/private-input/external-windows-acceptance.json"),
}
PROFILE = Path("final-delivery/private-input/submission-profile.json")
FINAL_VIDEO = Path("final-delivery/private-input/demonstration-video.mp4")
REGISTRATION_FORM = Path("final-delivery/private-input/registration-form.pdf")
PLATFORM_EVIDENCE = Path("final-delivery/private-input/platform-evidence.pdf")
ONLINE_VERIFICATION = Path("final-delivery/private-input/online-entry-verification.json")
SIGNED_CONSENT_DIR = Path("experiments/three-participant/signed-consent")
WINDOWS_ZIP = Path("output/windows/萤目守望-Windows.zip")
SOURCE_ZIP = Path("output/source/萤目守望-Source.zip")
OFFICIAL_LABELS = {
    "01": "研究报告",
    "02": "演示视频",
    "03": "源码与程序",
    "04": "部署与技术文档",
    "05": "测试报告",
    "06": "报名表",
    "07": "验证设计",
    "08": "平台调用证据",
}


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def validate_experiment(payload: dict) -> list[str]:
    from scripts.three_participant_experiment import validate_final_experiment_result

    return validate_final_experiment_result(payload)


def validate_stability(payload: dict) -> list[str]:
    errors = []
    if payload.get("status") != "COMPLETE":
        errors.append("stability status is not COMPLETE")
    runs = payload.get("runs", [])
    if not isinstance(runs, list) or {run.get("participant_id") for run in runs} != {"P01", "P02", "P03"}:
        errors.append("stability result must contain P01, P02, and P03 runs")
    else:
        for run in runs:
            if float(run.get("duration_hours", 0)) < 4:
                errors.append(f"{run.get('participant_id')} stability run is shorter than 4 hours")
    if float(payload.get("totals", {}).get("duration_hours", 0)) < 12:
        errors.append("total stability duration is shorter than 12 hours")
    return errors


def validate_urfd(payload: dict) -> list[str]:
    errors = []
    if payload.get("status") != "COMPLETE":
        errors.append("URFD review status is not COMPLETE")
    if payload.get("source_mode") != "PUBLIC_DATASET":
        errors.append("URFD source_mode must be PUBLIC_DATASET")
    if "URFD" not in str(payload.get("dataset_id", "")).upper():
        errors.append("dataset_id must identify URFD")
    if payload.get("mixed_with_self_collected") is not False:
        errors.append("URFD metrics must explicitly remain separate from self-collected metrics")
    if int(payload.get("sample_count", 0) or 0) < 1:
        errors.append("URFD review must report a positive sample_count")
    return errors


def validate_golden_loops(payload: dict) -> list[str]:
    errors = []
    if payload.get("status") != "COMPLETE":
        errors.append("golden-loop status is not COMPLETE")
    reproductions = payload.get("reproductions", [])
    if not isinstance(reproductions, list) or len(reproductions) != 3:
        return errors + ["exactly three golden-loop reproductions are required"]
    if {item.get("participant_id") for item in reproductions} != {"P01", "P02", "P03"}:
        errors.append("golden loops must cover P01, P02, and P03")
    for item in reproductions:
        if item.get("status") != "PASS":
            errors.append(f"{item.get('participant_id')} golden loop did not pass")
        if item.get("source_mode") != "RECORDED_REPLAY" or item.get("simulated") is not True:
            errors.append(f"{item.get('participant_id')} golden loop has invalid provenance")
        if item.get("final_state") != "RESOLVED":
            errors.append(f"{item.get('participant_id')} golden loop did not reach RESOLVED")
    return errors


def validate_authorization(payload: dict) -> list[str]:
    errors = []
    if payload.get("status") != "COMPLETE":
        errors.append("authorization summary status is not COMPLETE")
    participants = payload.get("participants", [])
    if not isinstance(participants, list) or {item.get("participant_id") for item in participants} != {"P01", "P02", "P03"}:
        errors.append("authorization summary must cover P01, P02, and P03")
    else:
        for item in participants:
            if item.get("adult_confirmed") is not True or item.get("signed") is not True:
                errors.append(f"{item.get('participant_id')} authorization is incomplete")
    if payload.get("contains_names_or_signatures") is not False:
        errors.append("public authorization summary must not contain names or signatures")
    return errors


def validate_video_verification(payload: dict) -> list[str]:
    errors = []
    if payload.get("status") != "COMPLETE":
        errors.append("video verification status is not COMPLETE")
    duration = float(payload.get("duration_seconds", 0) or 0)
    if not 300 <= duration <= 420:
        errors.append("video verification duration must be between 300 and 420 seconds")
    if payload.get("privacy_review") != "PASS":
        errors.append("video privacy review did not pass")
    if payload.get("source_labels_verified") is not True:
        errors.append("video source labels are not verified")
    if payload.get("live_replay_chain_separated") is not True:
        errors.append("LIVE_DEVICE and RECORDED_REPLAY chain separation is not verified")
    if payload.get("p03_metrics_match") is not True:
        errors.append("video P03 metrics are not verified against the report")
    return errors


def validate_external_windows(payload: dict, windows_zip: Path) -> list[str]:
    errors = []
    if payload.get("status") != "COMPLETE":
        errors.append("external Windows acceptance status is not COMPLETE")
    for field in ("clean_machine", "launch_passed", "shutdown_clean", "privacy_scan_passed"):
        if payload.get(field) is not True:
            errors.append(f"external Windows acceptance field {field} is not true")
    expected_hash = sha256_file(windows_zip) if windows_zip.is_file() else None
    if not expected_hash or payload.get("package_sha256") != expected_hash:
        errors.append("external Windows acceptance hash does not match the current package")
    return errors


VALIDATORS: dict[str, Callable[[dict], list[str]]] = {
    "experiment": validate_experiment,
    "stability": validate_stability,
    "urfd": validate_urfd,
    "golden_loops": validate_golden_loops,
    "authorization": validate_authorization,
    "video_verification": validate_video_verification,
}


def _document_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as archive:
            return archive.read("word/document.xml").decode("utf-8", errors="replace")
    if path.suffix.lower() == ".pdf":
        try:
            import fitz
        except ImportError as exc:
            raise ValueError("PyMuPDF is required to verify final PDF text") from exc
        with fitz.open(path) as document:
            return "\n".join(page.get_text() for page in document)
    return path.read_text(encoding="utf-8")


def _ffprobe_duration(path: Path) -> float:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return float(completed.stdout.strip())


def _zip_has_suffix(path: Path, suffix: str) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return any(name.lower().endswith(suffix.lower()) for name in archive.namelist())
    except zipfile.BadZipFile:
        return False


def _gate(name: str, errors: list[str]) -> dict[str, object]:
    return {"gate": name, "status": "PASS" if not errors else "INCOMPLETE", "errors": errors}


def _find_work_pdf(root: Path, mode: str, document_id: str, label: str, profile: dict[str, str]) -> Path:
    return root / "output" / "submission-work" / mode / "pdf" / (
        official_stem(document_id, label, profile, mode) + ".pdf"
    )


def _validate_pdf(path: Path, *, reject_markers: bool) -> list[str]:
    errors: list[str] = []
    if not path.is_file() or path.stat().st_size < 1024:
        return [f"missing or empty PDF: {path.as_posix()}"]
    try:
        document = fitz.open(path)
        if document.page_count < 1:
            errors.append(f"PDF has no pages: {path.as_posix()}")
        text = "\n".join(page.get_text() for page in document)
        if reject_markers and any(marker in text for marker in ("PENDING_REAL_DATA", "[[REQUIRED:", "DRAFT /")):
            errors.append(f"PDF still contains draft or required markers: {path.name}")
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"invalid PDF {path.as_posix()}: {exc}")
    return errors


def _consent_scan_paths(root: Path) -> tuple[list[Path], list[str]]:
    paths = [root / SIGNED_CONSENT_DIR / f"{participant}.pdf" for participant in ("P01", "P02", "P03")]
    errors: list[str] = []
    for path in paths:
        errors.extend(_validate_pdf(path, reject_markers=False))
    return paths, errors


def _validate_online_verification(path: Path, profile: dict[str, str]) -> list[str]:
    if not path.is_file():
        return [f"missing {ONLINE_VERIFICATION.as_posix()}"]
    try:
        payload = _load_json(path)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    errors = []
    if payload.get("status") != "COMPLETE":
        errors.append("online entry verification status is not COMPLETE")
    if payload.get("url") != profile["online_url"]:
        errors.append("online entry verification URL does not match submission profile")
    for field in ("correct_login_passed", "wrong_login_rejected", "routes_passed", "mobile_passed", "mock_only", "privacy_scan_passed"):
        if payload.get(field) is not True:
            errors.append(f"online entry verification field {field} is not true")
    return errors


def evaluate_gates(root: Path, mode: str, profile: dict[str, str]) -> tuple[list[dict[str, object]], dict[str, Path]]:
    gates: list[dict[str, object]] = []
    artifacts: dict[str, Path] = {}

    document_errors: list[str] = []
    for document_id in ("01", "04", "05", "07"):
        path = _find_work_pdf(root, mode, document_id, OFFICIAL_LABELS[document_id], profile)
        errors = _validate_pdf(path, reject_markers=mode == "final")
        document_errors.extend(errors)
        if not errors:
            artifacts[document_id] = path
    if mode == "draft":
        path = _find_work_pdf(root, mode, "08", OFFICIAL_LABELS["08"], profile)
        errors = _validate_pdf(path, reject_markers=False)
        document_errors.extend(errors)
        if not errors:
            artifacts["08"] = path
    gates.append(_gate("formal_documents", document_errors))

    evidence_payloads: dict[str, dict] = {}
    for key, relative in EVIDENCE_FILES.items():
        path = root / relative
        errors = []
        if not path.is_file():
            errors.append(f"missing {relative.as_posix()}")
        else:
            try:
                payload = _load_json(path)
                evidence_payloads[key] = payload
                if key == "external_windows":
                    errors.extend(validate_external_windows(payload, root / WINDOWS_ZIP))
                else:
                    errors.extend(VALIDATORS[key](payload))
            except (OSError, ValueError, TypeError) as exc:
                errors.append(str(exc))
        gates.append(_gate(key, errors))

    consent_paths, consent_errors = _consent_scan_paths(root)
    if not consent_errors:
        artifacts["consent_p01"] = consent_paths[0]
        artifacts["consent_p02"] = consent_paths[1]
        artifacts["consent_p03"] = consent_paths[2]
    gates.append(_gate("signed_consent_scans", consent_errors))

    video_path = root / FINAL_VIDEO
    video_errors = []
    if not video_path.is_file() or video_path.stat().st_size < 1024:
        video_errors.append(f"missing or empty {FINAL_VIDEO.as_posix()}")
    else:
        try:
            duration = _ffprobe_duration(video_path)
            if not 300 <= duration <= 420:
                video_errors.append(f"video duration is {duration:.2f}s; required range is 300-420s")
            declared = evidence_payloads.get("video_verification", {}).get("duration_seconds")
            if declared is not None and abs(float(declared) - duration) > 1:
                video_errors.append("video verification duration differs from ffprobe by more than one second")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            video_errors.append(f"cannot verify video duration: {exc}")
        if not video_errors:
            artifacts["02"] = video_path
    gates.append(_gate("final_video", video_errors))

    for gate_name, relative, suffix in (
        ("windows_release", WINDOWS_ZIP, ".exe"),
        ("source_release", SOURCE_ZIP, "source-release.json"),
    ):
        path = root / relative
        errors = []
        if not path.is_file():
            errors.append(f"missing {relative.as_posix()}")
        elif not _zip_has_suffix(path, suffix):
            errors.append(f"{path.name} does not contain required {suffix} entry")
        else:
            errors.extend(f"{item.path}: {item.kind}" for item in scan_zip(path))
            if not errors:
                artifacts[gate_name] = path
        gates.append(_gate(gate_name, errors))

    registration = root / REGISTRATION_FORM
    registration_errors = _validate_pdf(registration, reject_markers=True)
    if not registration_errors:
        artifacts["06"] = registration
    gates.append(_gate("registration_form", registration_errors))

    platform = root / PLATFORM_EVIDENCE
    platform_errors = _validate_pdf(platform, reject_markers=True)
    if not platform_errors:
        artifacts["08"] = platform
    gates.append(_gate("platform_evidence", platform_errors))

    gates.append(_gate("online_entry", _validate_online_verification(root / ONLINE_VERIFICATION, profile)))
    return gates, artifacts


def _copy_zip_tree(source_zip: Path, target: zipfile.ZipFile, prefix: str) -> list[str]:
    manifest: list[str] = []
    with zipfile.ZipFile(source_zip) as source:
        for info in sorted(source.infolist(), key=lambda item: item.filename):
            if info.is_dir():
                continue
            destination = f"{prefix}/{info.filename}"
            digest = hashlib.sha256()
            with source.open(info) as input_stream, target.open(destination, "w") as output_stream:
                while block := input_stream.read(1024 * 1024):
                    digest.update(block)
                    output_stream.write(block)
            manifest.append(f"{digest.hexdigest()}  {destination}")
    return manifest


def build_code_program_package(source_zip: Path, windows_zip: Path, output: Path, profile: dict[str, str]) -> None:
    temporary = output.with_name(output.name + ".tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    if temporary.exists():
        temporary.unlink()
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            manifest = _copy_zip_tree(source_zip, archive, "01_源码")
            manifest.extend(_copy_zip_tree(windows_zip, archive, "02_Windows程序"))
            readme = (
                "萤目守望源码与Windows程序\n\n"
                f"参赛学校：{profile['school']}\n联系人：{profile['contact_name']}\n\n"
                "01_源码：完整评审源码，不包含凭证、原始视频或签字授权。\n"
                "02_Windows程序：解压后双击 start-demo.cmd 运行脱敏演示。\n"
                "真实设备模式需要在本地私有配置中填写凭证，提交包不包含任何密钥。\n"
            )
            archive.writestr("README-先读.txt", readme)
            archive.writestr("MANIFEST-SHA256.txt", "\n".join(sorted(manifest)) + "\n")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def append_consent_scans(base_pdf: Path, scans: list[Path], output: Path) -> None:
    merged = fitz.open()
    with fitz.open(base_pdf) as base:
        merged.insert_pdf(base)
    for participant, scan_path in zip(("P01", "P02", "P03"), scans):
        page = merged.new_page(width=595, height=842)
        page.insert_textbox(
            fitz.Rect(54, 70, 541, 150),
            f"{participant} 签署授权扫描件 - 仅赛事评审使用",
            fontsize=13,
            align=1,
        )
        with fitz.open(scan_path) as scan:
            merged.insert_pdf(scan)
    output.parent.mkdir(parents=True, exist_ok=True)
    merged.save(output)
    merged.close()


def _replace_directory(source: Path, destination: Path, allowed_root: Path) -> None:
    destination = destination.resolve()
    allowed_root = allowed_root.resolve()
    try:
        destination.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(f"refusing to replace directory outside output root: {destination}") from exc
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    shutil.rmtree(source)


def assemble(root: Path, output_root: Path, mode: str) -> dict[str, object]:
    root = root.resolve()
    output_root = output_root.resolve()
    profile = load_profile(root / PROFILE)
    gates, artifacts = evaluate_gates(root, mode, profile)
    status = "READY" if mode == "final" and all(item["status"] == "PASS" for item in gates) else "INCOMPLETE"
    package_name = "萤目守望-正式提交材料" if mode == "final" else "萤目守望-提交材料-draft"
    staging = output_root / f".{package_name}.staging"
    package_dir = output_root / package_name
    zip_path = output_root / f"{package_name}.zip"
    report = {
        "schema_version": "yingmu-submission-status/1.0",
        "mode": mode,
        "status": status,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "gates": gates,
        "claim_boundary": "Three healthy adult participants; engineering feasibility only, not clinical validation.",
        "online_url": profile["online_url"],
    }
    if mode == "final" and status != "READY":
        output_root.mkdir(parents=True, exist_ok=True)
        refusal = output_root / "SUBMISSION_STATUS-final.json"
        refusal.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["refusal_report"] = str(refusal)
        return report
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    for document_id in ("01", "04", "05"):
        source = artifacts.get(document_id)
        if source:
            destination = staging / f"{official_stem(document_id, OFFICIAL_LABELS[document_id], profile, mode)}.pdf"
            shutil.copy2(source, destination)

    base_validation = artifacts.get("07")
    if base_validation:
        destination = staging / f"{official_stem('07', OFFICIAL_LABELS['07'], profile, mode)}.pdf"
        scans = [artifacts.get(f"consent_{participant.lower()}") for participant in ("P01", "P02", "P03")]
        if mode == "final" and all(isinstance(path, Path) for path in scans):
            append_consent_scans(base_validation, scans, destination)
        else:
            shutil.copy2(base_validation, destination)

    source_release = artifacts.get("source_release")
    windows_release = artifacts.get("windows_release")
    if source_release and windows_release:
        destination = staging / f"{official_stem('03', OFFICIAL_LABELS['03'], profile, mode)}.zip"
        build_code_program_package(source_release, windows_release, destination, profile)

    for document_id, artifact_key, suffix in (
        ("02", "02", ".mp4"),
        ("06", "06", ".pdf"),
        ("08", "08", ".pdf"),
    ):
        source = artifacts.get(artifact_key)
        if source:
            destination = staging / f"{official_stem(document_id, OFFICIAL_LABELS[document_id], profile, mode)}{suffix}"
            shutil.copy2(source, destination)

    findings = scan_files(
        [(path, path.relative_to(staging).as_posix()) for path in staging.rglob("*") if path.is_file()],
        allow_final_video=True,
    )
    if findings:
        shutil.rmtree(staging)
        details = "\n".join(f"- {item.path}: {item.kind} ({item.detail})" for item in findings)
        raise ValueError(f"submission privacy scan failed:\n{details}")
    output_root.mkdir(parents=True, exist_ok=True)
    _replace_directory(staging, package_dir, output_root)
    temporary_zip = zip_path.with_name(zip_path.name + ".tmp")
    if temporary_zip.exists():
        temporary_zip.unlink()
    try:
        with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(item for item in package_dir.rglob("*") if item.is_file()):
                archive.write(path, f"{package_name}/{path.relative_to(package_dir).as_posix()}")
        os.replace(temporary_zip, zip_path)
    finally:
        if temporary_zip.exists():
            temporary_zip.unlink()
    status_path = output_root / f"SUBMISSION_STATUS-{mode}.json"
    status_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report.update({"package_dir": str(package_dir), "zip": str(zip_path), "zip_sha256": sha256_file(zip_path)})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("draft", "final"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=Path("output/submission"))
    args = parser.parse_args()
    try:
        report = assemble(args.root, args.output_root, args.mode)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if args.mode == "draft" or report["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
