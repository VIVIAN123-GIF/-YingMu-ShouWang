"""Worker adapter for the existing OpenCV behavior pipeline.

Accepted ``media_locator`` values are local JSON summaries, CSV trajectory
tables, and video files (MP4/AVI/MOV/MKV). Images are deliberately rejected:
one image cannot provide a behavior time series. Video execution is delegated
to the unchanged ``behavior_demo.py`` in a temporary summary file.
"""

import asyncio
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from behavior_adapter import ADAPTER_VERSION, build_behavior_batch
from pacing import (
    MIN_ALTERNATING_PATTERNS,
    MIN_SEQUENCE_LENGTH,
    MIN_TRANSITIONS,
    TRACKING_QUALITY_THRESHOLD,
)

from .contract import (
    AdapterBatch,
    AlgorithmModule,
    AlgorithmJob,
    ContractValidationError,
    build_batch,
    error,
    job_payload,
    now_timestamp,
    validate_job,
)


VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif"}
CSV_SUFFIX = ".csv"
def _tracking_quality(summary: dict) -> float:
    """Prefer verified short-track coverage; fall back to legacy HOG coverage."""
    frames = int(summary.get("frames_processed", 0))
    tracked = summary.get("tracked_frames")
    if tracked is not None:
        return float(tracked) / frames if frames else 0.0
    return float(summary.get("detected_frames", 0)) / frames if frames else 0.0


class SceneConfigMissingError(ValueError):
    """Raised when a video job cannot resolve its fixed-camera calibration."""


class SceneConfigMismatchError(ValueError):
    """Raised when calibration provenance does not match the video job."""


def _resolve_scene_config(job: AlgorithmJob) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", job.scene_config_id):
        raise SceneConfigMissingError("scene_config_id contains unsupported characters")
    configured_dir = os.getenv("YINGMU_SCENE_CONFIG_DIR")
    scene_dir = (
        Path(configured_dir).expanduser()
        if configured_dir
        else Path(__file__).resolve().parents[2] / "scene_configs"
    )
    candidate = scene_dir / f"{job.scene_config_id}.json"
    if not candidate.is_file():
        raise SceneConfigMissingError(
            f"scene config is not available for {job.scene_config_id}"
        )
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SceneConfigMismatchError("scene config is not valid JSON") from exc
    if payload.get("scene_config_id") != job.scene_config_id:
        raise SceneConfigMismatchError("scene config ID does not match AlgorithmJob")
    configured_camera = payload.get("camera_position_id")
    if configured_camera and configured_camera != job.camera_position_id:
        raise SceneConfigMismatchError(
            "scene config camera_position_id does not match AlgorithmJob"
        )
    return candidate


def _path_from_locator(locator: str) -> Path:
    if locator.startswith("file://"):
        locator = locator[7:]
    if "://" in locator:
        raise ValueError("only local file or file:// media_locator is supported")
    path = Path(locator).expanduser()
    if not path.is_absolute():
        # Samples and Worker-local relative locators are resolved from this
        # demo package, independent of the process working directory.
        package_root = Path(__file__).resolve().parents[2]
        candidate = package_root / path
        if candidate.exists():
            return candidate
    return path


def _csv_summary(path: Path, job: AlgorithmJob) -> dict:
    """Convert a simple trajectory CSV into the summary expected by core code."""
    rows = list(csv.DictReader(path.open("r", encoding="utf-8-sig", newline="")))
    activities = Counter()
    detected = 0
    max_people = 0
    max_motion = 0.0
    points = 0
    distance = 0.0
    previous = None
    for row in rows:
        count = int(float(row.get("person_count") or row.get("people") or 0))
        detected += count > 0
        max_people = max(max_people, count)
        motion = float(row.get("motion_area") or row.get("activity_value") or 0)
        max_motion = max(max_motion, motion)
        activity = (row.get("activity_level") or "LOW").upper()
        activities[activity] += 1
        try:
            point = (float(row["x"]), float(row["y"]))
        except (KeyError, TypeError, ValueError):
            point = None
        if point is not None:
            points += 1
            if previous is not None:
                distance += ((point[0] - previous[0]) ** 2 + (point[1] - previous[1]) ** 2) ** 0.5
            previous = point
    return {
        "schema_version": "1.0",
        "input_type": "CSV",
        "source_mode": job.source_mode.value,
        "simulated": job.simulated,
        "frames_processed": len(rows),
        "detected_frames": detected,
        "max_person_count": max_people,
        "max_motion_area": int(max_motion),
        "activity_counts": dict(activities),
        "track_points": points,
        "travel_distance_px": round(distance, 3),
        "threshold_status": "DEMO_UNCALIBRATED",
    }


def _load_json_input(path: Path, job: AlgorithmJob) -> tuple[dict, dict | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("summary", payload) if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        raise ValueError("trajectory JSON must contain an object or a summary object")
    summary = dict(summary)
    summary["source_mode"] = job.source_mode.value
    summary["simulated"] = job.simulated
    summary["captured_at"] = job.captured_at.isoformat()
    trend = payload.get("trend") if isinstance(payload, dict) and "summary" in payload else None
    if trend is not None:
        if not isinstance(trend, dict) or not isinstance(trend.get("days"), list):
            raise ValueError("trajectory trend must contain a days array")
        trend = {
            **trend,
            "run_id": job.job_id,
            "resident_id": job.resident_id,
            "location": job.location,
            "source_mode": job.source_mode.value,
            "simulated": job.simulated,
            "asset_id": job.asset_id,
        }
    return summary, trend


def _run_video(path: Path, job: AlgorithmJob) -> dict:
    """Run the existing demo and read only its sanitized summary."""
    with tempfile.TemporaryDirectory(prefix="yingmu-trajectory-") as temp_dir:
        summary_path = Path(temp_dir) / "summary.json"
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "behavior_demo.py"),
            "--input", str(path), "--headless", "--summary-output", str(summary_path),
            "--scene-config-id", job.scene_config_id,
        ]
        scene_config = _resolve_scene_config(job)
        command.extend(["--region-config", str(scene_config)])
        if job.simulated:
            command.append("--simulated")
        timeout = max(30.0, job.deadline_ms / 1000 + 5) if job.deadline_ms else 120.0
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("behavior_demo timed out") from exc
        if completed.returncode != 0 or not summary_path.is_file():
            raise RuntimeError("behavior_demo could not process the video")
        summary, _ = _load_json_input(summary_path, job)
        return summary


def _load_summary(job: AlgorithmJob) -> tuple[dict, str, dict | None]:
    path = _path_from_locator(job.media_locator)
    if not path.is_file():
        raise FileNotFoundError("trajectory input file does not exist")
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        raise ValueError("image input is unsupported; provide a video or trajectory JSON/CSV")
    if suffix == ".json":
        summary, trend = _load_json_input(path, job)
        return summary, "JSON_SUMMARY", trend
    if suffix == CSV_SUFFIX:
        return _csv_summary(path, job), "CSV_TRAJECTORY", None
    if suffix in VIDEO_SUFFIXES:
        summary = awaitable_video(path, job)
        return summary, "VIDEO", None
    raise ValueError("unsupported trajectory input format")


def awaitable_video(path: Path, job: AlgorithmJob) -> dict:
    return _run_video(path, job)


async def run(job: AlgorithmJob) -> AdapterBatch:
    """Execute the trajectory adapter using the repository's frozen contract."""
    started_at = now_timestamp()
    try:
        checked_job = validate_job(job)
        if checked_job.requested_modules and AlgorithmModule.TRAJECTORY not in checked_job.requested_modules:
            raise ValueError("TRAJECTORY is not listed in requested_modules")
        summary, input_format, trend_payload = await asyncio.to_thread(
            _load_summary, checked_job
        )
        summary["source_mode"] = checked_job.source_mode.value
        summary["simulated"] = checked_job.simulated
        summary["captured_at"] = checked_job.captured_at.isoformat()
        summary["scene_config_id"] = checked_job.scene_config_id
        frames = int(summary.get("frames_processed", 0))
        detected = int(summary.get("detected_frames", 0))
        tracked = int(summary.get("tracked_frames", detected))
        quality = _tracking_quality(summary)
        inner = build_behavior_batch(
            job_payload(checked_job), summary,
            resident_id=checked_job.resident_id,
            location=checked_job.location,
            trend_payload=(
                trend_payload if quality >= TRACKING_QUALITY_THRESHOLD else None
            ),
            started_at=started_at,
            completed_at=now_timestamp(),
        )
        observations = inner["observations"]
        evidences = inner["evidences"]
        status = "LOW_QUALITY" if quality < TRACKING_QUALITY_THRESHOLD else ("SUCCESS" if evidences else "NO_EVIDENCE")
        return build_batch(
            checked_job, module="TRAJECTORY", status=status,
            adapter_version=ADAPTER_VERSION, started_at=started_at, completed_at=now_timestamp(),
            observations=observations, evidences=evidences,
            diagnostics={
                "input_format": input_format,
                "frames_processed": frames,
                "detected_frames": detected,
                "tracked_frames": tracked,
                "detection_quality": round(
                    detected / frames, 4
                ) if frames else 0.0,
                "tracking_quality": round(quality, 4),
                "tracking_quality_threshold": TRACKING_QUALITY_THRESHOLD,
                "pacing_min_sequence_length": MIN_SEQUENCE_LENGTH,
                "pacing_min_transitions": MIN_TRANSITIONS,
                "pacing_min_alternating_patterns": MIN_ALTERNATING_PATTERNS,
                "sensitivity_profile": "SENSITIVE_DEMO_UNCALIBRATED",
                "threshold_status": summary.get("threshold_status", "DEMO_UNCALIBRATED"),
                "scene_config_id": checked_job.scene_config_id,
                "scene_config_status": (
                    "RESOLVED" if input_format == "VIDEO" else "UPSTREAM_SUMMARY"
                ),
                "core_algorithm": "behavior_demo.py",
            },
        )
    except SceneConfigMissingError as exc:
        return build_batch(
            job, module="TRAJECTORY", status="FAILED", adapter_version=ADAPTER_VERSION,
            started_at=started_at, completed_at=now_timestamp(), observations=[], evidences=[],
            diagnostics={"input_format": "VIDEO", "scene_config_id": job.scene_config_id},
            batch_error=error("SCENE_CONFIG_MISSING", str(exc), retryable=False),
        )
    except SceneConfigMismatchError as exc:
        return build_batch(
            job, module="TRAJECTORY", status="FAILED", adapter_version=ADAPTER_VERSION,
            started_at=started_at, completed_at=now_timestamp(), observations=[], evidences=[],
            diagnostics={"input_format": "VIDEO", "scene_config_id": job.scene_config_id},
            batch_error=error("SCENE_CONFIG_MISMATCH", str(exc), retryable=False),
        )
    except (ContractValidationError, FileNotFoundError, ValueError, json.JSONDecodeError, OSError, RuntimeError) as exc:
        return build_batch(
            job, module="TRAJECTORY", status="FAILED", adapter_version=ADAPTER_VERSION,
            started_at=started_at, completed_at=now_timestamp(), observations=[], evidences=[],
            diagnostics={"input_format": "UNKNOWN"},
            batch_error=error("TRAJECTORY_INPUT_ERROR", str(exc), retryable=isinstance(exc, OSError)),
        )
