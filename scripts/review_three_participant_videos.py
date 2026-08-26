"""Inventory and review private three-participant capture videos.

The inventory stage is deliberately label-blind: it never runs pose or risk
inference and never turns an observed action into formal ground truth. A human
must confirm participant, scenario, validity, and event bounds before the
selection stage can populate protocol slots.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import shutil
import subprocess
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

try:
    from scripts import three_participant_experiment as experiment
except ModuleNotFoundError:  # Direct invocation: python scripts/review_three_participant_videos.py
    import three_participant_experiment as experiment


PARTICIPANTS = tuple(experiment.PARTICIPANT_SPLITS)
SCENARIO_IDS = tuple(scenario.scenario_id for scenario in experiment.SCENARIOS)
REVIEW_VALIDITIES = ("PENDING", "VALID", "ABORTED", "EXCLUDED")
LOCAL_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")

INVENTORY_FIELDS = (
    "candidate_id",
    "folder_participant_id",
    "proposed_participant_id",
    "confirmed_participant_id",
    "batch",
    "record_role_hint",
    "capture_date",
    "creation_time",
    "original_filename",
    "original_relpath",
    "byte_size",
    "sha256",
    "duration_ms",
    "width",
    "height",
    "fps",
    "video_codec",
    "audio_codec",
    "decode_status",
    "valid_frame_ratio",
    "mean_core_visibility",
    "quality_source",
    "exact_duplicate_group",
    "normalized_filename",
    "normalized_relpath",
    "preview_relpath",
    "observed_action_group",
    "proposed_scenario_id",
    "scenario_confidence",
    "confirmed_scenario_id",
    "confirmed_validity",
    "confirmed_event_start_ms",
    "confirmed_event_end_ms",
    "protocol_variant",
    "lighting",
    "camera_position_id",
    "authorization_record_id",
    "selection_priority",
    "reviewer_notes",
    "issues",
)

SELECTION_FIELDS = (
    "candidate_id",
    "selection_status",
    "planned_slot_id",
    "participant_id",
    "scenario_id",
    "capture_date",
    "duration_ms",
    "normalized_relpath",
    "sha256",
    "notes",
)

ISSUE_FIELDS = ("severity", "code", "candidate_id", "detail")


@dataclass(frozen=True)
class Probe:
    duration_ms: int
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str
    creation_time: str


def write_csv(path: Path, fields: Sequence[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def _parse_fraction(value: str) -> float:
    numerator, separator, denominator = value.partition("/")
    if not separator:
        return float(value)
    parsed_denominator = float(denominator)
    return float(numerator) / parsed_denominator if parsed_denominator else 0.0


def probe_video(path: Path, ffprobe: str = "ffprobe") -> Probe:
    result = _run([
        ffprobe,
        "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate",
        "-show_entries", "format=duration:format_tags=creation_time",
        "-of", "json",
        str(path),
    ])
    if result.returncode:
        raise ValueError(result.stderr.strip() or "ffprobe failed")
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("video stream missing")
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    creation = str(payload.get("format", {}).get("tags", {}).get("creation_time", ""))
    return Probe(
        duration_ms=round(float(payload["format"]["duration"]) * 1000),
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        fps=round(_parse_fraction(str(video.get("r_frame_rate", "0"))), 3),
        video_codec=str(video.get("codec_name", "")),
        audio_codec=str(audio.get("codec_name", "")),
        creation_time=creation,
    )


def decode_status(path: Path, ffmpeg: str = "ffmpeg") -> tuple[str, str]:
    result = _run([ffmpeg, "-hide_banner", "-v", "error", "-i", str(path), "-f", "null", "NUL"])
    if result.returncode == 0:
        return "PASS", ""
    detail = " ".join(result.stderr.strip().splitlines())[:500]
    return "FAIL", detail or "ffmpeg decode failed"


def create_preview(path: Path, output: Path, duration_ms: int, ffmpeg: str = "ffmpeg") -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    duration_seconds = max(duration_ms / 1000, 0.1)
    rate = 5.8 / duration_seconds
    result = _run([
        ffmpeg,
        "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(path),
        "-vf", f"fps={rate:.8f},scale=320:180,tile=3x2",
        "-frames:v", "1",
        str(output),
    ])
    if result.returncode:
        raise ValueError(result.stderr.strip() or "preview generation failed")


def _safe_extract(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            pure = PurePosixPath(item.filename.replace("\\", "/"))
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError(f"unsafe ZIP member: {item.filename}")
            target = (destination / Path(*pure.parts)).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"unsafe ZIP member: {item.filename}") from exc
        source.extractall(destination)
    return destination


def prepare_input(source: Path, output_dir: Path) -> Path:
    if source.is_dir():
        return source.resolve()
    if source.is_file() and source.suffix.lower() == ".zip":
        return _safe_extract(source, output_dir / "source-cache")
    raise ValueError(f"input must be a directory or ZIP archive: {source}")


def load_overrides(path: Path | None) -> dict[str, dict[str, object]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    files = payload.get("files", payload)
    if not isinstance(files, dict):
        raise ValueError("override file must contain an object named 'files'")
    return {str(key).replace("\\", "/"): dict(value) for key, value in files.items()}


def _folder_metadata(path: Path, root: Path) -> tuple[str, str]:
    relpath = path.relative_to(root)
    participant = next((part.upper() for part in relpath.parts if part.upper() in PARTICIPANTS), "UNKNOWN")
    batch = path.parent.name
    return participant, batch


def _local_creation_time(value: str) -> str:
    if not value:
        return ""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(LOCAL_TIMEZONE).isoformat(timespec="seconds")


def _ordered_sources(root: Path, overrides: dict[str, dict[str, object]], ffprobe: str) -> list[dict[str, object]]:
    sources: list[dict[str, object]] = []
    for path in sorted(root.rglob("*.mp4"), key=lambda item: item.as_posix().lower()):
        relpath = path.relative_to(root).as_posix()
        folder_participant, batch = _folder_metadata(path, root)
        override = overrides.get(relpath, {})
        try:
            probe = probe_video(path, ffprobe)
            probe_error = ""
        except (ValueError, json.JSONDecodeError) as exc:
            probe = Probe(0, 0, 0, 0.0, "", "", "")
            probe_error = str(exc)
        participant = str(override.get("proposed_participant_id", folder_participant)).upper()
        sources.append({
            "path": path,
            "relpath": relpath,
            "folder_participant_id": folder_participant,
            "proposed_participant_id": participant,
            "batch": batch,
            "probe": probe,
            "probe_error": probe_error,
            "override": override,
        })
    sources.sort(key=lambda item: (
        str(item["proposed_participant_id"]),
        str(item["batch"]),
        item["probe"].creation_time,
        str(item["relpath"]),
    ))
    return sources


def inventory_videos(
    root: Path,
    output_dir: Path,
    *,
    overrides: dict[str, dict[str, object]] | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    copy_normalized: bool = True,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    overrides = overrides or {}
    sources = _ordered_sources(root, overrides, ffprobe)
    counters: Counter[tuple[str, str]] = Counter()
    rows: list[dict[str, object]] = []
    issues: list[dict[str, str]] = []
    hashes: defaultdict[str, list[str]] = defaultdict(list)

    for source in sources:
        path = source["path"]
        probe: Probe = source["probe"]
        override = source["override"]
        participant = str(source["proposed_participant_id"])
        batch = str(source["batch"])
        batch_code = "DAY1" if "day1" in batch.lower() else "DAY2" if "day2" in batch.lower() else "OTHER"
        counters[(participant, batch_code)] += 1
        candidate_id = f"{participant}-{batch_code}-{counters[(participant, batch_code)]:03d}"
        digest = sha256_file(path)
        hashes[digest].append(candidate_id)
        normalized_filename = f"{candidate_id}-{digest[:8]}.mp4"
        normalized_relpath = Path("normalized-media") / participant / batch_code.lower() / normalized_filename
        preview_relpath = Path("previews") / f"{candidate_id}.jpg"
        creation_time = _local_creation_time(probe.creation_time)
        capture_date = creation_time[:10] if creation_time else ""
        status, decode_error = decode_status(path, ffmpeg) if not source["probe_error"] else ("FAIL", source["probe_error"])

        row_issues: list[str] = []
        if source["folder_participant_id"] != participant:
            row_issues.append("PARTICIPANT_FOLDER_MISMATCH")
        if not path.stem:
            row_issues.append("EMPTY_FILENAME")
        elif len(path.stem) >= 24 and all(character in "0123456789abcdefABCDEF" for character in path.stem.replace("_raw", "")):
            row_issues.append("NON_DESCRIPTIVE_FILENAME")
        if status != "PASS":
            row_issues.append("DECODE_FAILED")
        if probe.fps and probe.fps != 15.0:
            row_issues.append("INCONSISTENT_FPS")
        if probe.width and (probe.width, probe.height) != (1280, 720):
            row_issues.append("INCONSISTENT_RESOLUTION")

        record_role_hint = str(override.get("record_role_hint", ""))
        observed_action = str(override.get("observed_action_group", ""))
        proposed_scenario = str(override.get("proposed_scenario_id", ""))
        confirmed_validity = str(override.get("confirmed_validity", "PENDING"))
        row = {
            "candidate_id": candidate_id,
            "folder_participant_id": source["folder_participant_id"],
            "proposed_participant_id": participant,
            "confirmed_participant_id": str(override.get("confirmed_participant_id", "")),
            "batch": batch,
            "record_role_hint": record_role_hint,
            "capture_date": capture_date,
            "creation_time": creation_time,
            "original_filename": path.name,
            "original_relpath": source["relpath"],
            "byte_size": path.stat().st_size,
            "sha256": digest,
            "duration_ms": probe.duration_ms,
            "width": probe.width,
            "height": probe.height,
            "fps": probe.fps,
            "video_codec": probe.video_codec,
            "audio_codec": probe.audio_codec,
            "decode_status": status,
            "valid_frame_ratio": str(override.get("valid_frame_ratio", "")),
            "mean_core_visibility": str(override.get("mean_core_visibility", "")),
            "quality_source": str(override.get("quality_source", "")),
            "exact_duplicate_group": "",
            "normalized_filename": normalized_filename,
            "normalized_relpath": normalized_relpath.as_posix(),
            "preview_relpath": preview_relpath.as_posix(),
            "observed_action_group": observed_action,
            "proposed_scenario_id": proposed_scenario,
            "scenario_confidence": str(override.get("scenario_confidence", "")),
            "confirmed_scenario_id": str(override.get("confirmed_scenario_id", "")),
            "confirmed_validity": confirmed_validity,
            "confirmed_event_start_ms": str(override.get("confirmed_event_start_ms", "")),
            "confirmed_event_end_ms": str(override.get("confirmed_event_end_ms", "")),
            "protocol_variant": str(override.get("protocol_variant", "STANDARD")),
            "lighting": str(override.get("lighting", "INDOOR")),
            "camera_position_id": str(override.get("camera_position_id", "C6c-pos01")),
            "authorization_record_id": str(override.get("authorization_record_id", "")),
            "selection_priority": str(override.get("selection_priority", "")),
            "reviewer_notes": str(override.get("reviewer_notes", "")),
            "issues": "|".join(row_issues),
        }
        rows.append(row)

        if copy_normalized:
            destination = output_dir / normalized_relpath
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        try:
            create_preview(path, output_dir / preview_relpath, probe.duration_ms, ffmpeg)
        except ValueError as exc:
            row_issues.append("PREVIEW_FAILED")
            row["issues"] = "|".join(row_issues)
            issues.append({"severity": "ERROR", "code": "PREVIEW_FAILED", "candidate_id": candidate_id, "detail": str(exc)})
        if decode_error:
            issues.append({"severity": "ERROR", "code": "DECODE_FAILED", "candidate_id": candidate_id, "detail": decode_error})
        for code in row_issues:
            if code in {"DECODE_FAILED", "PREVIEW_FAILED"}:
                continue
            severity = "WARNING" if code.startswith("INCONSISTENT") else "INFO"
            issues.append({"severity": severity, "code": code, "candidate_id": candidate_id, "detail": source["relpath"]})

    for digest, candidate_ids in hashes.items():
        if len(candidate_ids) < 2:
            continue
        group = f"SHA256-{digest[:12]}"
        for row in rows:
            if row["candidate_id"] in candidate_ids:
                row["exact_duplicate_group"] = group
                row["issues"] = "|".join(filter(None, [str(row["issues"]), "EXACT_DUPLICATE"]))
        issues.append({
            "severity": "WARNING",
            "code": "EXACT_DUPLICATE",
            "candidate_id": ",".join(candidate_ids),
            "detail": f"identical SHA-256 {digest}",
        })
    return rows, issues


def _confirmed(row: dict[str, str], field: str, fallback: str) -> str:
    return row.get(field, "").strip() or row.get(fallback, "").strip()


def select_protocol_slots(rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    planned = experiment.planned_rows()
    candidates: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    rejected: list[dict[str, object]] = []
    scenario_lookup = {scenario.scenario_id: scenario for scenario in experiment.SCENARIOS}

    for row in rows:
        role_hint = row.get("record_role_hint", "").strip().upper()
        if role_hint == "SMOKE":
            rejected.append({
                "candidate_id": row["candidate_id"], "selection_status": "SMOKE_NOT_IN_96",
                "planned_slot_id": "", "participant_id": _confirmed(row, "confirmed_participant_id", "proposed_participant_id"),
                "scenario_id": "", "capture_date": row.get("capture_date", ""),
                "duration_ms": row.get("duration_ms", ""), "normalized_relpath": row.get("normalized_relpath", ""),
                "sha256": row.get("sha256", ""), "notes": "冒烟小样不计入96段",
            })
            continue
        participant = _confirmed(row, "confirmed_participant_id", "proposed_participant_id")
        scenario_id = row.get("confirmed_scenario_id", "").strip()
        validity = row.get("confirmed_validity", "").strip().upper()
        if not scenario_id or validity != "VALID" or participant not in PARTICIPANTS:
            rejected.append({
                "candidate_id": row["candidate_id"], "selection_status": "AWAITING_CONFIRMATION",
                "planned_slot_id": "", "participant_id": participant,
                "scenario_id": scenario_id, "capture_date": row.get("capture_date", ""),
                "duration_ms": row.get("duration_ms", ""), "normalized_relpath": row.get("normalized_relpath", ""),
                "sha256": row.get("sha256", ""), "notes": "需确认参与者、场景和VALID状态",
            })
            continue
        if scenario_id not in scenario_lookup:
            rejected.append({
                "candidate_id": row["candidate_id"], "selection_status": "INVALID_SCENARIO",
                "planned_slot_id": "", "participant_id": participant,
                "scenario_id": scenario_id, "capture_date": row.get("capture_date", ""),
                "duration_ms": row.get("duration_ms", ""), "normalized_relpath": row.get("normalized_relpath", ""),
                "sha256": row.get("sha256", ""), "notes": "未知scenario_id",
            })
            continue
        candidates[(participant, scenario_id)].append(row)

    def rank(row: dict[str, str], scenario_id: str) -> tuple[int, int, str]:
        priority = int(row["selection_priority"]) if row.get("selection_priority", "").isdigit() else 999
        planned_ms = scenario_lookup[scenario_id].planned_duration_seconds * 1000
        duration = int(row.get("duration_ms", "0") or 0)
        return priority, abs(duration - planned_ms), row["candidate_id"]

    selected_by_slot: dict[str, dict[str, str]] = {}
    for (participant, scenario_id), group in candidates.items():
        scenario = scenario_lookup[scenario_id]
        ordered = sorted(group, key=lambda row: rank(row, scenario_id))
        if scenario.golden_first:
            golden = [
                row for row in ordered
                if row.get("protocol_variant", "").strip() == "GOLDEN_115S"
                and int(row.get("duration_ms", "0") or 0) >= 110_000
            ]
            if golden:
                chosen = golden[0]
                selected_by_slot[f"{participant}-{scenario_id}-01"] = chosen
                ordered.remove(chosen)
                start_index = 2
            else:
                start_index = 2
            for repeat_index, row in zip(range(start_index, scenario.count + 1), ordered):
                selected_by_slot[f"{participant}-{scenario_id}-{repeat_index:02d}"] = row
        else:
            for repeat_index, row in zip(range(1, scenario.count + 1), ordered):
                selected_by_slot[f"{participant}-{scenario_id}-{repeat_index:02d}"] = row

    selected: list[dict[str, object]] = []
    manifest_rows: list[dict[str, object]] = []
    used_candidates: set[str] = set()
    for planned_row in planned:
        slot = str(planned_row["planned_slot_id"])
        source = selected_by_slot.get(slot)
        manifest = dict(planned_row)
        if source is None:
            manifest["notes"] = "MISSING_OR_UNCONFIRMED"
            selected.append({
                "candidate_id": "", "selection_status": "MISSING_OR_UNCONFIRMED",
                "planned_slot_id": slot, "participant_id": planned_row["participant_id"],
                "scenario_id": planned_row["scenario_id"], "capture_date": "", "duration_ms": "",
                "normalized_relpath": "", "sha256": "", "notes": "需要补拍或确认候选片段",
            })
        else:
            used_candidates.add(source["candidate_id"])
            manifest.update({
                "clip_id": slot,
                "capture_date": source.get("capture_date", ""),
                "event_start_ms": source.get("confirmed_event_start_ms", ""),
                "event_end_ms": source.get("confirmed_event_end_ms", ""),
                "lighting": source.get("lighting", ""),
                "camera_position_id": source.get("camera_position_id", "C6c-pos01"),
                "authorization_record_id": source.get("authorization_record_id", ""),
                "validity": "VALID",
                "video_relpath": source.get("normalized_relpath", ""),
                "sha256": source.get("sha256", ""),
                "notes": f"source_candidate={source['candidate_id']}; original={source.get('original_relpath', '')}",
            })
            selected.append({
                "candidate_id": source["candidate_id"], "selection_status": "SELECTED",
                "planned_slot_id": slot, "participant_id": planned_row["participant_id"],
                "scenario_id": planned_row["scenario_id"], "capture_date": source.get("capture_date", ""),
                "duration_ms": source.get("duration_ms", ""), "normalized_relpath": source.get("normalized_relpath", ""),
                "sha256": source.get("sha256", ""), "notes": manifest["notes"],
            })
        manifest_rows.append(manifest)

    for group in candidates.values():
        for row in group:
            if row["candidate_id"] in used_candidates:
                continue
            rejected.append({
                "candidate_id": row["candidate_id"], "selection_status": "EXTRA_RETAKE",
                "planned_slot_id": "", "participant_id": _confirmed(row, "confirmed_participant_id", "proposed_participant_id"),
                "scenario_id": row.get("confirmed_scenario_id", ""), "capture_date": row.get("capture_date", ""),
                "duration_ms": row.get("duration_ms", ""), "normalized_relpath": row.get("normalized_relpath", ""),
                "sha256": row.get("sha256", ""), "notes": "同场景候选超过计划数量，保留审计",
            })
    return selected, rejected, manifest_rows


def build_summary(rows: list[dict[str, object]], selected: list[dict[str, object]]) -> dict[str, object]:
    participant_counts = Counter(str(row["proposed_participant_id"]) for row in rows)
    formal_candidates = [row for row in rows if str(row.get("record_role_hint", "")).upper() != "SMOKE"]
    formal_by_participant = Counter(str(row["proposed_participant_id"]) for row in formal_candidates)
    smoke_count = len(rows) - len(formal_candidates)
    selected_count = sum(row["selection_status"] == "SELECTED" for row in selected)
    missing_count = sum(row["selection_status"] == "MISSING_OR_UNCONFIRMED" for row in selected)
    participant_quality: dict[str, object] = {}
    for participant in PARTICIPANTS:
        participant_rows = [row for row in rows if row["proposed_participant_id"] == participant]
        durations = [int(row["duration_ms"]) for row in participant_rows]
        pose_rows = [row for row in participant_rows if str(row.get("valid_frame_ratio", "")).strip()]
        participant_quality[participant] = {
            "video_count": len(participant_rows),
            "smoke_count": sum(str(row.get("record_role_hint", "")).upper() == "SMOKE" for row in participant_rows),
            "formal_candidate_count": formal_by_participant.get(participant, 0),
            "decode_pass_count": sum(row["decode_status"] == "PASS" for row in participant_rows),
            "capture_dates": sorted({str(row.get("capture_date", "")) for row in participant_rows if row.get("capture_date")}),
            "resolutions": sorted({
                f"{row.get('width')}x{row.get('height')}"
                for row in participant_rows if row.get("width") and row.get("height")
            }),
            "fps_values": sorted({float(row["fps"]) for row in participant_rows if row.get("fps")}),
            "duration_ms": {
                "minimum": min(durations) if durations else None,
                "maximum": max(durations) if durations else None,
                "mean": round(sum(durations) / len(durations), 1) if durations else None,
            },
            "folder_mismatch_count": sum(
                bool(row.get("folder_participant_id")) and row["folder_participant_id"] != participant
                for row in participant_rows
            ),
            "pose_smoke_quality": {
                "evaluated_clip_count": len(pose_rows),
                "valid_frame_ratio": [float(row["valid_frame_ratio"]) for row in pose_rows],
                "mean_core_visibility": [float(row["mean_core_visibility"]) for row in pose_rows],
            },
        }
    return {
        "schema_version": "three-participant-video-review/1.0",
        "status": "COMPLETE" if selected_count == 96 else "INCOMPLETE",
        "video_count": len(rows),
        "smoke_count": smoke_count,
        "formal_candidate_count": len(formal_candidates),
        "minimum_additional_formal_clips": max(0, 96 - len(formal_candidates)),
        "participant_video_counts": dict(sorted(participant_counts.items())),
        "formal_candidate_counts": {participant: formal_by_participant.get(participant, 0) for participant in PARTICIPANTS},
        "participant_quality": participant_quality,
        "decode_pass_count": sum(row["decode_status"] == "PASS" for row in rows),
        "exact_duplicate_count": sum(bool(row["exact_duplicate_group"]) for row in rows),
        "selected_count": selected_count,
        "missing_or_unconfirmed_slot_count": missing_count,
        "golden_115s_candidate_count": sum(
            int(row.get("duration_ms", 0)) >= 110_000 and row.get("protocol_variant") == "GOLDEN_115S"
            for row in rows
        ),
        "test_set_inference_run": False,
        "notes": [
            "冒烟小样不计入96段。",
            "场景真值必须由拍摄同学确认，观察动作分组不能替代ground_truth。",
            "P03清点阶段仅做媒体完整性和人工画面检查，不运行姿态或风险推理。",
        ],
    }


def build_review_html(rows: list[dict[str, object]], summary: dict[str, object], output: Path) -> None:
    body_rows = []
    for row in rows:
        participant = html.escape(str(row["proposed_participant_id"]))
        candidate = html.escape(str(row["candidate_id"]))
        confirmed_participant = str(row["confirmed_participant_id"]) or str(row["proposed_participant_id"])
        participant_options = "".join(
            f'<option value="{value}"{" selected" if value == confirmed_participant else ""}>{value}</option>'
            for value in PARTICIPANTS
        )
        proposed_scenario = str(row["confirmed_scenario_id"]) or str(row["proposed_scenario_id"])
        scenario_options = "".join(
            f'<option value="{html.escape(value)}"{" selected" if value == proposed_scenario else ""}>{html.escape(value)}</option>'
            for value in SCENARIO_IDS
        )
        confirmed_validity = str(row["confirmed_validity"]) or "PENDING"
        validity_options = "".join(
            f'<option value="{value}"{" selected" if value == confirmed_validity else ""}>{value}</option>'
            for value in REVIEW_VALIDITIES
        )
        body_rows.append(f"""
          <tr data-participant="{participant}" data-batch="{html.escape(str(row['batch']))}">
            <td><img src="{html.escape(str(row['preview_relpath']))}" alt="{candidate} preview"></td>
            <td><strong>{candidate}</strong><br><span>{html.escape(str(row['capture_date']))}</span></td>
            <td>{html.escape(str(row['folder_participant_id']))} → <select data-field="confirmed_participant_id">{participant_options}</select></td>
            <td>{html.escape(str(row['batch']))}<br><span>{int(row['duration_ms']) / 1000:.1f}s</span></td>
            <td>{html.escape(str(row['observed_action_group'])) or '待观察'}</td>
            <td><select data-field="confirmed_scenario_id"><option value="">待确认</option>{scenario_options}</select></td>
            <td><select data-field="confirmed_validity">{validity_options}</select></td>
            <td><input data-field="reviewer_notes" value="{html.escape(str(row['reviewer_notes']), quote=True)}"></td>
            <td><a href="{html.escape(str(row['normalized_relpath']))}">播放</a></td>
          </tr>""")
    data_json = html.escape(json.dumps(rows, ensure_ascii=False), quote=False)
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>三参与者视频确认</title>
<style>
:root{{--bg:#f5f6f7;--panel:#fff;--ink:#1d2329;--muted:#667085;--line:#d9dee5;--accent:#126e82;--warn:#a15c00}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 "Microsoft YaHei",sans-serif;letter-spacing:0}}
header{{background:var(--panel);border-bottom:1px solid var(--line);padding:14px 20px}}
h1{{font-size:20px;margin:0 0 10px}}.toolbar{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}.metric{{color:var(--muted)}}
button,select,input{{border:1px solid #b8c0ca;background:#fff;border-radius:4px;padding:7px 9px;font:inherit}}button{{background:var(--accent);color:#fff;border-color:var(--accent);cursor:pointer}}
main{{padding:14px 20px 30px;overflow:auto}}table{{width:100%;border-collapse:separate;border-spacing:0;background:var(--panel);border:1px solid var(--line)}}
th{{position:sticky;top:0;z-index:1;background:#eef2f4;text-align:left;padding:9px;border-bottom:1px solid var(--line)}}td{{padding:8px;border-bottom:1px solid #edf0f2;vertical-align:middle}}tr:last-child td{{border-bottom:0}}
td img{{display:block;width:240px;aspect-ratio:8/3;object-fit:cover;background:#e8ebee}}td span{{color:var(--muted)}}td input{{width:190px}}a{{color:var(--accent)}}
@media(max-width:900px){{th{{position:static}}main{{padding:8px}}td img{{width:180px}}}}
</style></head><body>
<header><h1>三参与者视频确认</h1><div class="toolbar">
<span class="metric">视频 {summary['video_count']} · 冒烟 {summary['smoke_count']} · 正式候选 {summary['formal_candidate_count']} · 至少缺 {summary['minimum_additional_formal_clips']}</span>
<select id="participant"><option value="">全部参与者</option><option>P01</option><option>P02</option><option>P03</option></select>
<input id="search" placeholder="筛选编号或动作"><button id="export">导出确认CSV</button></div></header>
<main><table><thead><tr><th>预览</th><th>候选编号</th><th>参与者</th><th>批次</th><th>观察动作</th><th>确认场景</th><th>有效性</th><th>备注</th><th>视频</th></tr></thead>
<tbody>{''.join(body_rows)}</tbody></table></main>
<script id="source" type="application/json">{data_json}</script><script>
const rows=JSON.parse(document.getElementById('source').textContent);const trs=[...document.querySelectorAll('tbody tr')];
function filter(){{const p=document.getElementById('participant').value;const q=document.getElementById('search').value.toLowerCase();trs.forEach((tr,i)=>{{const row=rows[i];tr.hidden=!!p&&row.proposed_participant_id!==p||!!q&&!JSON.stringify(row).toLowerCase().includes(q)}})}}
document.getElementById('participant').addEventListener('change',filter);document.getElementById('search').addEventListener('input',filter);
document.getElementById('export').addEventListener('click',()=>{{trs.forEach((tr,i)=>tr.querySelectorAll('[data-field]').forEach(el=>rows[i][el.dataset.field]=el.value));const fields={json.dumps(list(INVENTORY_FIELDS), ensure_ascii=False)};const esc=v=>'"'+String(v??'').replaceAll('"','""')+'"';const csv='\\ufeff'+fields.map(esc).join(',')+'\\r\\n'+rows.map(r=>fields.map(f=>esc(r[f])).join(',')).join('\\r\\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{{type:'text/csv;charset=utf-8'}}));a.download='video-confirmation-reviewed.csv';a.click();URL.revokeObjectURL(a.href)}});
</script></body></html>"""
    output.write_text(document, encoding="utf-8")


def build_readme(summary: dict[str, object], output: Path) -> None:
    output.write_text(
        "# 三参与者视频初筛包\n\n"
        f"状态：`{summary['status']}`\n\n"
        f"- 当前视频：{summary['video_count']}段\n"
        f"- 冒烟小样：{summary['smoke_count']}段，不计入96段\n"
        f"- 正式候选：{summary['formal_candidate_count']}段\n"
        f"- 在所有候选均可用的乐观前提下，至少还缺：{summary['minimum_additional_formal_clips']}段\n"
        f"- 完整解码：{summary['decode_pass_count']}段\n"
        f"- 115秒黄金候选：{summary['golden_115s_candidate_count']}段\n\n"
        "## 拍摄同学需要填写\n\n"
        "打开`review-index.html`，逐段选择正式`scenario_id`和有效性，完成后点击“导出确认CSV”。"
        "观察动作只用于找片，不能作为实验真值。\n\n"
        "允许的正式场景：\n\n"
        + "\n".join(f"- `{scenario}`" for scenario in SCENARIO_IDS)
        + "\n\n确认后运行：\n\n"
        "```powershell\n"
        "python scripts/review_three_participant_videos.py finalize `\n"
        "  --confirmation <video-confirmation-reviewed.csv> `\n"
        "  --output-dir <本目录>\n"
        "```\n\n"
        "`capture-manifest.draft.csv`只有在96个槽位全部真实匹配、事件区间完整且通过现有严格校验后，才能用于P03锁定和正式指标。\n",
        encoding="utf-8",
    )


def audit_command(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        raise ValueError(f"refusing to overwrite existing output directory: {output_dir}")
    output_dir.mkdir(parents=True)
    source = prepare_input(Path(args.input).resolve(), output_dir)
    overrides = load_overrides(Path(args.overrides).resolve() if args.overrides else None)
    rows, issues = inventory_videos(
        source,
        output_dir,
        overrides=overrides,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
        copy_normalized=not args.no_copy,
    )
    selected, rejected, manifest = select_protocol_slots([{key: str(value) for key, value in row.items()} for row in rows])
    summary = build_summary(rows, selected)
    write_csv(output_dir / "video-confirmation.csv", INVENTORY_FIELDS, rows)
    write_csv(output_dir / "filename-mapping.csv", (
        "candidate_id", "original_relpath", "normalized_relpath", "folder_participant_id", "proposed_participant_id", "sha256"
    ), rows)
    write_csv(output_dir / "selection-status.csv", SELECTION_FIELDS, selected + rejected)
    write_csv(output_dir / "issues.csv", ISSUE_FIELDS, issues)
    experiment.write_csv(output_dir / "capture-manifest.draft.csv", experiment.MANIFEST_FIELDS, manifest)
    (output_dir / "SHA256SUMS.txt").write_text(
        "".join(f"{row['sha256']}  {row['original_relpath']}\n" for row in sorted(rows, key=lambda item: str(item["original_relpath"]))),
        encoding="utf-8",
    )
    write_json(output_dir / "quality-summary.json", summary)
    build_review_html(rows, summary, output_dir / "review-index.html")
    build_readme(summary, output_dir / "README.md")
    print(json.dumps({**summary, "output_dir": str(output_dir)}, ensure_ascii=False, indent=2))
    return 0


def finalize_command(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    confirmation = Path(args.confirmation).resolve()
    rows = read_csv(confirmation)
    missing_columns = set(INVENTORY_FIELDS) - (set(rows[0]) if rows else set())
    if missing_columns:
        raise ValueError(f"confirmation CSV missing columns: {', '.join(sorted(missing_columns))}")
    selected, rejected, manifest = select_protocol_slots(rows)
    write_csv(output_dir / "selection-status.csv", SELECTION_FIELDS, selected + rejected)
    experiment.write_csv(output_dir / "capture-manifest.draft.csv", experiment.MANIFEST_FIELDS, manifest)
    template_report = experiment.validate_manifest(output_dir / "capture-manifest.draft.csv", stage="template")
    captured_report = experiment.validate_manifest(
        output_dir / "capture-manifest.draft.csv",
        stage="captured",
        media_root=output_dir,
    )
    selected_count = sum(row["selection_status"] == "SELECTED" for row in selected)
    payload = {
        "status": "COMPLETE" if selected_count == 96 and captured_report["status"] == "PASS" else "INCOMPLETE",
        "selected_count": selected_count,
        "missing_or_unconfirmed_slot_count": 96 - selected_count,
        "template_validation": template_report,
        "captured_validation": captured_report,
        "next_gate": "complete missing slots, event bounds, authorization fields, and cross-date checks",
    }
    write_json(output_dir / "finalize-summary.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "COMPLETE" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inventory and select three-participant capture videos.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit", help="Create a label-blind inventory and review package.")
    audit.add_argument("--input", required=True, help="Private source directory or ZIP archive.")
    audit.add_argument("--output-dir", required=True)
    audit.add_argument("--overrides", help="Optional local JSON with manual participant/action observations.")
    audit.add_argument("--ffmpeg", default="ffmpeg")
    audit.add_argument("--ffprobe", default="ffprobe")
    audit.add_argument("--no-copy", action="store_true", help="Do not create normalized private media copies.")
    audit.set_defaults(handler=audit_command)
    finalize = subparsers.add_parser("finalize", help="Assign confirmed candidates to the 96 planned slots.")
    finalize.add_argument("--confirmation", required=True)
    finalize.add_argument("--output-dir", required=True)
    finalize.set_defaults(handler=finalize_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, subprocess.TimeoutExpired, zipfile.BadZipFile) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
