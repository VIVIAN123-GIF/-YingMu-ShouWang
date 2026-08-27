from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Iterable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_public_manifest(rows: list[dict[str, str]], output: Path) -> None:
    fields = (
        "dataset",
        "relative_path",
        "file_name",
        "label",
        "modality",
        "source_url",
        "size_bytes",
        "sha256",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def finite_float(row: dict[str, str], field: str) -> float:
    value = float(row[field])
    if not math.isfinite(value):
        raise ValueError(f"non-finite {field} in sequence {row.get('sequence_id')}")
    return value


def rounded_median(values: Iterable[float]) -> float | None:
    values = list(values)
    return round(median(values), 6) if values else None


def expected_sequence_ids(fall_count: int, adl_count: int, camera: str) -> set[str]:
    return {
        *(f"fall-{index:02d}-{camera}-rgb" for index in range(1, fall_count + 1)),
        *(f"adl-{index:02d}-{camera}-rgb" for index in range(1, adl_count + 1)),
    }


def has_rapid_rise(rows: list[dict[str, str]]) -> bool:
    for start_index, start in enumerate(rows):
        start_time = int(start["timestamp_ms"])
        start_y = finite_float(start, "pelvis_y_smooth")
        for end in rows[start_index + 1 :]:
            duration_s = (int(end["timestamp_ms"]) - start_time) / 1000.0
            if duration_s < 0.4:
                continue
            if duration_s > 1.5:
                break
            if start_y - finite_float(end, "pelvis_y_smooth") >= 0.05:
                return True
    return False


def label_summary(rows: list[dict[str, str]], quality_threshold: float) -> dict[str, object]:
    success = [row for row in rows if finite_float(row, "valid_frame_ratio") >= quality_threshold]
    low_quality = [
        row
        for row in rows
        if 0 < finite_float(row, "valid_frame_ratio") < quality_threshold
    ]
    failed = [row for row in rows if int(row["detected_frames"]) == 0]
    return {
        "sample_count": len(rows),
        "processing_success_count": len(success),
        "low_quality_count": len(low_quality),
        "failure_count": len(failed),
        "median_valid_frame_ratio": rounded_median(
            finite_float(row, "valid_frame_ratio") for row in rows
        ),
        "median_mean_core_visibility": rounded_median(
            finite_float(row, "mean_core_visibility") for row in rows
        ),
        "feature_medians": {
            field: rounded_median(finite_float(row, field) for row in rows)
            for field in (
                "step_speed",
                "sway_frequency_hz",
                "step_length_asymmetry_ratio",
            )
        },
    }


def git_commit(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def git_worktree_dirty(root: Path) -> bool | None:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(completed.stdout.strip())


def validate_manifest(
    rows: list[dict[str, str]],
    *,
    expected_fall_count: int,
    expected_adl_count: int,
    camera: str,
) -> None:
    expected_files = {
        *(f"fall-{index:02d}-{camera}-rgb.zip" for index in range(1, expected_fall_count + 1)),
        *(f"fall-{index:02d}-data.csv" for index in range(1, expected_fall_count + 1)),
        *(f"adl-{index:02d}-{camera}-rgb.zip" for index in range(1, expected_adl_count + 1)),
        *(f"adl-{index:02d}-data.csv" for index in range(1, expected_adl_count + 1)),
    }
    actual_files = {row.get("file_name", "") for row in rows}
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        raise ValueError(f"URFD manifest mismatch; missing={missing}, extra={extra}")
    for row in rows:
        if row.get("dataset") != "urfd":
            raise ValueError("manifest contains a non-URFD row")
        if int(row.get("size_bytes", 0)) <= 0:
            raise ValueError(f"manifest has empty source file: {row.get('file_name')}")
        digest = row.get("sha256", "")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
            raise ValueError(f"manifest has invalid SHA-256: {row.get('file_name')}")


def build_review(args: argparse.Namespace) -> dict:
    manifest_rows = read_csv(args.manifest) if args.manifest else []
    feature_rows = read_csv(args.features)
    frame_rows = read_csv(args.frames)
    build_summary = read_json(args.build_summary)
    baseline = read_json(args.baseline_profile)

    if not args.archived_processed:
        if not args.manifest:
            raise ValueError("--manifest is required unless --archived-processed is used")
        validate_manifest(
            manifest_rows,
            expected_fall_count=args.expected_fall_count,
            expected_adl_count=args.expected_adl_count,
            camera=args.camera_filter,
        )
    expected_ids = expected_sequence_ids(
        args.expected_fall_count,
        args.expected_adl_count,
        args.camera_filter,
    )
    actual_ids = {row.get("sequence_id", "") for row in feature_rows}
    if len(feature_rows) != len(actual_ids):
        raise ValueError("feature dataset contains duplicate sequence IDs")
    if actual_ids != expected_ids:
        raise ValueError(
            f"processed sequence mismatch; missing={sorted(expected_ids - actual_ids)}, "
            f"extra={sorted(actual_ids - expected_ids)}"
        )
    expected_labels = {"fall": args.expected_fall_count, "adl": args.expected_adl_count}
    label_counts = Counter(row.get("label") for row in feature_rows)
    if dict(label_counts) != expected_labels:
        raise ValueError(f"processed label counts mismatch: {dict(label_counts)}")
    if int(build_summary.get("sequence_count", -1)) != len(feature_rows):
        raise ValueError("build summary sequence count does not match feature dataset")
    if int(build_summary.get("frame_row_count", -1)) != len(frame_rows):
        raise ValueError("build summary frame count does not match frame dataset")

    params = baseline.get("rule_parameters")
    if not isinstance(params, dict):
        raise ValueError("baseline profile is missing rule_parameters")
    quality_threshold = float(params["tracking_lost_valid_frame_ratio"])
    baseline_speed = float(params["baseline_speed"])
    speed_alert_ratio = float(params["relative_speed_deviation_alert_ratio"])
    baseline_asymmetry = float(params["baseline_asymmetry"])
    asymmetry_alert_ratio = float(params["gait_instability_alert_ratio"])
    trunk_sway_threshold = float(params["baseline_sway_deg"])

    frames_by_sequence: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in frame_rows:
        sequence_id = row.get("sequence_id", "")
        if sequence_id not in expected_ids:
            raise ValueError(f"frame dataset contains unknown sequence: {sequence_id}")
        frames_by_sequence[sequence_id].append(row)
    for rows in frames_by_sequence.values():
        rows.sort(key=lambda row: int(row["timestamp_ms"]))

    indicators: dict[str, set[str]] = {
        "rapid_rise": set(),
        "trunk_sway": set(),
        "gait_instability": set(),
        "relative_speed_change": set(),
        "tracking_lost": set(),
    }
    for row in feature_rows:
        sequence_id = row["sequence_id"]
        sequence_frames = frames_by_sequence.get(sequence_id, [])
        if sequence_frames and has_rapid_rise(sequence_frames):
            indicators["rapid_rise"].add(sequence_id)
        if sequence_frames and max(
            abs(finite_float(frame, "trunk_angle_deg_smooth")) for frame in sequence_frames
        ) >= trunk_sway_threshold:
            indicators["trunk_sway"].add(sequence_id)
        asymmetry_deviation = (
            finite_float(row, "step_length_asymmetry_ratio") - baseline_asymmetry
        ) / max(baseline_asymmetry, 1e-9)
        if asymmetry_deviation >= asymmetry_alert_ratio:
            indicators["gait_instability"].add(sequence_id)
        speed_deviation = (
            finite_float(row, "step_speed") - baseline_speed
        ) / max(baseline_speed, 1e-9)
        if abs(speed_deviation) >= speed_alert_ratio:
            indicators["relative_speed_change"].add(sequence_id)
        if finite_float(row, "valid_frame_ratio") < quality_threshold:
            indicators["tracking_lost"].add(sequence_id)

    by_label_rows = {
        label: [row for row in feature_rows if row["label"] == label]
        for label in ("fall", "adl")
    }
    evidence_counts = {}
    for evidence_type, sequence_ids in indicators.items():
        evidence_counts[evidence_type] = {
            "total": len(sequence_ids),
            "fall_label": sum(sequence_id.startswith("fall-") for sequence_id in sequence_ids),
            "adl_label": sum(sequence_id.startswith("adl-") for sequence_id in sequence_ids),
        }

    if args.public_manifest_output and manifest_rows:
        copy_public_manifest(manifest_rows, args.public_manifest_output)

    processing_success = sum(
        finite_float(row, "valid_frame_ratio") >= quality_threshold for row in feature_rows
    )
    low_quality = sum(
        0 < finite_float(row, "valid_frame_ratio") < quality_threshold for row in feature_rows
    )
    failures = sum(int(row["detected_frames"]) == 0 for row in feature_rows)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    root = Path.cwd().resolve()
    source_bytes = sum(int(row["size_bytes"]) for row in manifest_rows)

    return {
        "schema_version": "urfd-review/1.0",
        "status": "COMPLETE",
        "generated_at": generated_at,
        "source_mode": "PUBLIC_DATASET",
        "dataset_id": (
            f"URFD official {args.camera_filter} archived processed snapshot {args.download_date}"
            if args.archived_processed
            else f"URFD official {args.camera_filter} snapshot {args.download_date}"
        ),
        "dataset_source": "https://fenix.ur.edu.pl/~mkepski/ds/uf.html",
        "download_date": args.download_date,
        "camera_filter": args.camera_filter,
        "sample_count": len(feature_rows),
        "label_counts": expected_labels,
        "mixed_with_self_collected": False,
        "source_artifacts": {
            "file_count": len(manifest_rows),
            "rgb_archive_count": sum(row["modality"] == "rgb" for row in manifest_rows),
            "metadata_file_count": sum(row["modality"] == "metadata" for row in manifest_rows),
            "total_size_bytes": source_bytes,
            "private_download_manifest_sha256": sha256_file(args.manifest) if args.manifest else None,
            "public_manifest_sha256": (
                sha256_file(args.public_manifest_output) if args.public_manifest_output else None
            ),
        },
        "processing": {
            "pipeline": "MediaPipe PoseLandmarker heavy -> cleaned frame features -> sequence summary",
            "git_commit": git_commit(root),
            "git_worktree_dirty_at_run": git_worktree_dirty(root),
            "camera_filter": args.camera_filter,
            "frame_stride": args.frame_stride,
            "visibility_threshold": args.visibility_threshold,
            "quality_threshold": quality_threshold,
            "input_sampled_frame_count": sum(int(row["total_frames"]) for row in feature_rows),
            "valid_pose_frame_count": len(frame_rows),
            "processing_success_count": processing_success,
            "low_quality_count": low_quality,
            "failure_count": failures,
            "artifact_sha256": {
                "sequence_features": sha256_file(args.features),
                "cleaned_frames": sha256_file(args.frames),
                "build_summary": sha256_file(args.build_summary),
                "baseline_profile": sha256_file(args.baseline_profile),
                "pose_model": sha256_file(args.model),
                "feature_builder": sha256_file(args.feature_builder),
                "review_builder": sha256_file(Path(__file__).resolve()),
            },
        },
        "metrics": {
            "by_label": {
                label: label_summary(rows, quality_threshold)
                for label, rows in by_label_rows.items()
            },
            "engineering_indicator_counts": evidence_counts,
            "indicator_parameters": {
                "rapid_rise": "pelvis upward displacement >= 0.05 within 0.4-1.5 s",
                "trunk_sway_abs_angle_deg": trunk_sway_threshold,
                "gait_instability_deviation_ratio": asymmetry_alert_ratio,
                "relative_speed_abs_deviation_ratio": speed_alert_ratio,
                "tracking_lost_valid_frame_ratio": quality_threshold,
            },
            "classification_metrics": {
                "status": "NOT_APPLICABLE",
                "reason": (
                    "URFD fall/ADL labels are not equivalent to the frozen sit-to-stand ORANGE "
                    "event definition; no Accuracy, Precision, Recall or F1 is reported."
                ),
            },
        },
        "claim_boundary": (
            "Independent public-dataset pipeline review only; not mixed with P01/P02/P03, "
            "not ORANGE accuracy, fall probability, clinical validation, or elderly-population performance. "
            + (
                "This run reviews archived processed outputs; it is not a fresh raw-download rerun."
                if args.archived_processed
                else "Raw source files were downloaded and hash-verified for this run."
            )
        ),
        "notes": [
            (
                "The archived processed outputs contain all 30 URFD fall and 40 URFD ADL cam0 sequences; "
                "raw download manifest was not retained with the archived outputs."
                if args.archived_processed
                else "All 30 URFD fall and 40 URFD ADL cam0 sequences were processed once in this review."
            ),
            "Engineering indicator counts are descriptive threshold exceedances, not fall predictions.",
            "Low-quality sequences remain in the denominator and are not silently removed.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a reproducible formal URFD review summary.")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--build-summary", type=Path, required=True)
    parser.add_argument("--baseline-profile", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--feature-builder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-manifest-output", type=Path)
    parser.add_argument("--download-date", required=True)
    parser.add_argument(
        "--archived-processed",
        action="store_true",
        help="Review an existing complete processed output when the raw download manifest is unavailable.",
    )
    parser.add_argument("--camera-filter", default="cam0")
    parser.add_argument("--frame-stride", type=int, default=2)
    parser.add_argument("--visibility-threshold", type=float, default=0.5)
    parser.add_argument("--expected-fall-count", type=int, default=30)
    parser.add_argument("--expected-adl-count", type=int, default=40)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        review = build_review(args)
        write_json(args.output, review)
    except (OSError, ValueError, KeyError, csv.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(review, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
