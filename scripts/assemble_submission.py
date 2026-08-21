"""Assemble a draft or final delivery package with evidence-based release gates."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from scripts.release_integrity import manifest_lines, scan_files, scan_zip, sha256_file


EXPECTED_DOCUMENTS = tuple(f"{index:02d}" for index in range(1, 9))
EVIDENCE_FILES = {
    "experiment": Path("experiments/three-participant/results/final/experiment-results.json"),
    "stability": Path("experiments/three-participant/results/stability-summary.json"),
    "urfd": Path("experiments/three-participant/results/urfd-results.json"),
    "golden_loops": Path("experiments/three-participant/results/golden-loop-results.json"),
    "authorization": Path("experiments/three-participant/results/authorization-summary.json"),
    "video_verification": Path("final-delivery/input/video-verification.json"),
    "external_windows": Path("final-delivery/input/external-windows-acceptance.json"),
}
FINAL_VIDEO = Path("final-delivery/input/萤目守望-演示视频.mp4")
WINDOWS_ZIP = Path("output/windows/萤目守望-Windows.zip")
SOURCE_ZIP = Path("output/source/萤目守望-Source.zip")


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def validate_experiment(payload: dict) -> list[str]:
    errors = []
    if payload.get("status") != "COMPLETE":
        errors.append("experiment status is not COMPLETE")
    primary = payload.get("primary_result", {})
    if primary.get("participant_id") != "P03" or primary.get("config_id") != "A":
        errors.append("primary result must be P03 configuration A")
    if primary.get("sample_count") != 24:
        errors.append("P03 primary result must contain exactly 24 evaluation clips")
    participant_results = payload.get("participant_results", {})
    for participant in ("P01", "P02", "P03"):
        if participant_results.get(participant, {}).get("sample_count") != 24:
            errors.append(f"{participant} result must contain exactly 24 evaluation clips")
    ablations = payload.get("ablation_results", {})
    for config_id in ("A", "B", "C", "D"):
        if ablations.get(config_id, {}).get("sample_count") != 24:
            errors.append(f"ablation {config_id} must use all 24 P03 clips")
    if not payload.get("test_lock_sha256") or not payload.get("rule_freeze_sha256"):
        errors.append("experiment result is missing test-lock or rule-freeze hashes")
    return errors


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


def evaluate_gates(root: Path) -> tuple[list[dict[str, object]], list[tuple[Path, str]]]:
    gates: list[dict[str, object]] = []
    artifacts: list[tuple[Path, str]] = []

    docx_dir = root / "final-delivery/output/docx"
    pdf_dir = root / "final-delivery/output/pdf"
    source_dir = root / "final-delivery/docs"
    docx = sorted(docx_dir.glob("*.docx"))
    pdf = sorted(pdf_dir.glob("*.pdf"))
    doc_errors = []
    if len(docx) != 8 or len(pdf) != 8:
        doc_errors.append(f"expected 8 DOCX and 8 PDF files, found {len(docx)} and {len(pdf)}")
    if {path.name[:2] for path in docx} != set(EXPECTED_DOCUMENTS) or {path.name[:2] for path in pdf} != set(EXPECTED_DOCUMENTS):
        doc_errors.append("formal document numbering must cover 01 through 08")
    for path in sorted(source_dir.glob("*.md")) + sorted((root / "final-delivery/video").glob("*")):
        if path.is_file() and ("PENDING_" in path.read_text(encoding="utf-8") or ",PENDING," in path.read_text(encoding="utf-8")):
            doc_errors.append(f"pending marker remains in {path.relative_to(root).as_posix()}")
    for path in docx + pdf:
        if "PENDING_" in _document_text(path):
            doc_errors.append(f"pending marker remains in {path.relative_to(root).as_posix()}")
        matching_sources = [item for item in source_dir.glob(f"{path.name[:2]}-*.md")]
        if matching_sources and path.stat().st_mtime < matching_sources[0].stat().st_mtime:
            doc_errors.append(f"generated document is older than source: {path.name}")
    gates.append({"gate": "formal_documents", "status": "PASS" if not doc_errors else "INCOMPLETE", "errors": doc_errors})
    artifacts.extend((path, f"01-文档/DOCX/{path.name}") for path in docx)
    artifacts.extend((path, f"01-文档/PDF/{path.name}") for path in pdf)

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
        gates.append({"gate": key, "status": "PASS" if not errors else "INCOMPLETE", "errors": errors})
        if path.is_file():
            artifacts.append((path, f"04-证据摘要/{path.name}"))

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
        artifacts.append((video_path, f"03-视频/{video_path.name}"))
    gates.append({"gate": "final_video", "status": "PASS" if not video_errors else "INCOMPLETE", "errors": video_errors})

    for gate_name, relative, destination, suffix in (
        ("windows_release", WINDOWS_ZIP, "02-程序/萤目守望-Windows.zip", ".exe"),
        ("source_release", SOURCE_ZIP, "02-程序/萤目守望-Source.zip", "source-release.json"),
    ):
        path = root / relative
        errors = []
        if not path.is_file():
            errors.append(f"missing {relative.as_posix()}")
        elif not _zip_has_suffix(path, suffix):
            errors.append(f"{path.name} does not contain required {suffix} entry")
        else:
            errors.extend(f"{item.path}: {item.kind}" for item in scan_zip(path))
            artifacts.append((path, destination))
        gates.append({"gate": gate_name, "status": "PASS" if not errors else "INCOMPLETE", "errors": errors})
    return gates, artifacts


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
    gates, artifacts = evaluate_gates(root)
    status = "READY" if all(item["status"] == "PASS" for item in gates) else "INCOMPLETE"
    package_name = f"萤目守望-提交包-{mode}"
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
    for source, destination in artifacts:
        target = staging / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (staging / "SUBMISSION_STATUS.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    findings = scan_files(
        [(path, path.relative_to(staging).as_posix()) for path in staging.rglob("*") if path.is_file()],
        allow_final_video=True,
    )
    if findings:
        shutil.rmtree(staging)
        details = "\n".join(f"- {item.path}: {item.kind} ({item.detail})" for item in findings)
        raise ValueError(f"submission privacy scan failed:\n{details}")
    manifest_path = staging / "MANIFEST-SHA256.txt"
    manifest_path.write_text(
        "\n".join(manifest_lines(staging, exclude_names={manifest_path.name})) + "\n", encoding="utf-8"
    )
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
