"""Fixed-camera trajectory and scene-interaction adapter."""

from __future__ import annotations

import hashlib
import asyncio
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from contracts.v1.algorithm import (
    AdapterBatch,
    AdapterError,
    AdapterStatus,
    AlgorithmJob,
    AlgorithmModule,
    MediaType,
    validate_batch_for_job,
)
from contracts.v1.forewarning import SceneCalibration, SceneZone
from contracts.v1.gait_video import GaitVideoError, extract_pose_video_analysis
from contracts.v1.models import Evidence, Observation, RiskDomain, TimeScale
from contracts.v1.ruleset import load_forewarning_ruleset


ADAPTER_VERSION = "trajectory-adapter-v1.3-min"
MODULE = AlgorithmModule.TRAJECTORY
RULESET = load_forewarning_ruleset()
SCENE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _score(value: float) -> float:
    return round(min(max(float(value), 0.0), 1.0), 3)


def _scene_root() -> Path:
    configured = os.getenv("YINGMU_SCENE_CONFIG_DIR", "scene-calibrations").strip()
    return Path(configured or "scene-calibrations").expanduser().resolve()


def load_scene_calibration(scene_config_id: str) -> SceneCalibration:
    if not SCENE_ID_PATTERN.fullmatch(scene_config_id):
        raise ValueError("SCENE_CONFIG_ID_INVALID")
    root = _scene_root()
    target = (root / f"{scene_config_id}.json").resolve()
    if root not in target.parents or not target.is_file():
        raise FileNotFoundError("SCENE_CONFIG_MISSING")
    try:
        return SceneCalibration.model_validate_json(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("SCENE_CONFIG_INVALID") from exc


def point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if ((y1 > y) != (y2 > y)) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
        previous = current
    return inside


def _cross(
    start: tuple[float, float],
    end: tuple[float, float],
    point: tuple[float, float],
) -> float:
    return (
        (end[0] - start[0]) * (point[1] - start[1])
        - (end[1] - start[1]) * (point[0] - start[0])
    )


def _point_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    epsilon: float = 1e-9,
) -> bool:
    return (
        abs(_cross(start, end, point)) <= epsilon
        and min(start[0], end[0]) - epsilon <= point[0] <= max(start[0], end[0]) + epsilon
        and min(start[1], end[1]) - epsilon <= point[1] <= max(start[1], end[1]) + epsilon
    )


def segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
    *,
    epsilon: float = 1e-9,
) -> bool:
    first_left = _cross(first_start, first_end, second_start)
    first_right = _cross(first_start, first_end, second_end)
    second_left = _cross(second_start, second_end, first_start)
    second_right = _cross(second_start, second_end, first_end)
    if (
        ((first_left > epsilon and first_right < -epsilon) or (first_left < -epsilon and first_right > epsilon))
        and ((second_left > epsilon and second_right < -epsilon) or (second_left < -epsilon and second_right > epsilon))
    ):
        return True
    return (
        (abs(first_left) <= epsilon and _point_on_segment(second_start, first_start, first_end, epsilon=epsilon))
        or (abs(first_right) <= epsilon and _point_on_segment(second_end, first_start, first_end, epsilon=epsilon))
        or (abs(second_left) <= epsilon and _point_on_segment(first_start, second_start, second_end, epsilon=epsilon))
        or (abs(second_right) <= epsilon and _point_on_segment(first_end, second_start, second_end, epsilon=epsilon))
    )


def segment_intersects_zone(
    start: tuple[float, float],
    end: tuple[float, float],
    zone: SceneZone,
) -> bool:
    if point_in_polygon(start, zone.polygon_norm) or point_in_polygon(end, zone.polygon_norm):
        return True
    return any(
        segments_intersect(start, end, left, right)
        for left, right in zip(
            zone.polygon_norm,
            zone.polygon_norm[1:] + zone.polygon_norm[:1],
        )
    )


def trajectory_intersects_zone(
    points: list[tuple[float, float, float, float]],
    zone: SceneZone,
) -> bool:
    if any(point_in_polygon((point[1], point[2]), zone.polygon_norm) for point in points):
        return True
    return any(
        0 < current[0] - previous[0] <= 1.0
        and segment_intersects_zone(
            (previous[1], previous[2]),
            (current[1], current[2]),
            zone,
        )
        for previous, current in zip(points, points[1:])
    )


def _point_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float],
) -> float:
    px, py = point
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return math.hypot(px - sx, py - sy)
    ratio = min(max(((px - sx) * dx + (py - sy) * dy) / length_squared, 0.0), 1.0)
    return math.hypot(px - (sx + ratio * dx), py - (sy + ratio * dy))


def distance_to_zone(point: tuple[float, float], zone: SceneZone) -> float:
    if point_in_polygon(point, zone.polygon_norm):
        return 0.0
    return min(
        _point_segment_distance(point, left, right)
        for left, right in zip(zone.polygon_norm, zone.polygon_norm[1:] + zone.polygon_norm[:1])
    )


def _dwell_seconds(
    points: list[tuple[float, float, float, float]], zone: SceneZone,
) -> float:
    total = 0.0
    for previous, current in zip(points, points[1:]):
        gap = current[0] - previous[0]
        if 0 < gap <= 1.0 and point_in_polygon((previous[1], previous[2]), zone.polygon_norm) and point_in_polygon((current[1], current[2]), zone.polygon_norm):
            total += gap
    return round(total, 3)


def _observation(
    job: AlgorithmJob, feature_name: str, value: object, unit: str | None,
    quality: float, *, zone_ids: Iterable[str] = (),
) -> Observation:
    return Observation(
        schema_version="1.0",
        observation_id=_stable_id("obs-trajectory", job.job_id, job.asset_id, feature_name),
        resident_id=job.resident_id,
        timestamp=job.captured_at,
        source="trajectory_adapter",
        feature_name=feature_name,
        feature_value=value,
        unit=unit,
        location=job.location,
        confidence=_score(0.72 + 0.25 * quality),
        data_quality=quality,
        source_mode=job.source_mode,
        asset_id=job.asset_id,
        simulated=job.simulated,
        metadata={
            "adapter_module": MODULE.value,
            "camera_position_id": job.camera_position_id,
            "scene_config_id": job.scene_config_id,
            "zone_ids": sorted(set(zone_ids)),
        },
    )


def _evidence(
    job: AlgorithmJob, evidence_type: str, observations: list[Observation],
    severity: float, explanation: str,
) -> Evidence:
    return Evidence(
        schema_version="1.0",
        evidence_id=_stable_id("evi-trajectory", job.job_id, job.asset_id, evidence_type, *(item.observation_id for item in observations)),
        observation_ids=[item.observation_id for item in observations],
        resident_id=job.resident_id,
        timestamp=job.captured_at,
        risk_domain=RiskDomain.SYSTEM,
        evidence_type=evidence_type,
        severity=_score(severity),
        confidence=min(item.confidence for item in observations),
        data_quality=min(item.data_quality for item in observations),
        baseline_value=None,
        current_value=float(observations[0].feature_value) if isinstance(observations[0].feature_value, (int, float)) else None,
        baseline_deviation=None,
        time_scale=TimeScale.SHORT,
        location=job.location,
        explanation=explanation,
        adapter_version=ADAPTER_VERSION,
        source_mode=job.source_mode,
        simulated=job.simulated,
    )


def _failed(job: AlgorithmJob, started_at: datetime, code: str) -> AdapterBatch:
    return AdapterBatch(
        schema_version="adapter-batch/1.0",
        job_id=job.job_id,
        module=MODULE,
        adapter_version=ADAPTER_VERSION,
        status=AdapterStatus.FAILED,
        started_at=started_at,
        completed_at=_now(),
        error=AdapterError(code=code, message="Trajectory analysis could not use the configured fixed-camera scene.", retryable=False),
    )


async def run(job: AlgorithmJob) -> AdapterBatch:
    started_at = _now()
    if job.media_type != MediaType.VIDEO:
        return _failed(job, started_at, "VIDEO_REQUIRED")
    try:
        scene = await asyncio.to_thread(load_scene_calibration, job.scene_config_id)
        if scene.camera_position_id != job.camera_position_id or scene.location != job.location:
            return _failed(job, started_at, "SCENE_CAMERA_MISMATCH")
        analysis = await asyncio.to_thread(extract_pose_video_analysis, Path(job.media_locator))
    except FileNotFoundError:
        return _failed(job, started_at, "SCENE_CONFIG_MISSING")
    except ValueError as exc:
        return _failed(job, started_at, str(exc) if str(exc).startswith("SCENE_") else "SCENE_CONFIG_INVALID")
    except GaitVideoError as exc:
        return _failed(job, started_at, str(exc).upper())

    points = list(analysis.trajectory_points)
    declared_frames = max(int(analysis.diagnostics.get("frames_processed", len(points))), 1)
    tracking_ratio = len(points) / declared_frames
    quality = _score(min(tracking_ratio, float(analysis.features.get("valid_frame_ratio", tracking_ratio))))
    observations: list[Observation] = [
        _observation(job, "trajectory_tracking_ratio", tracking_ratio, "ratio", quality),
        _observation(job, "illumination_norm", analysis.illumination_norm, "ratio", quality),
    ]
    evidences: list[Evidence] = []
    if quality < float(RULESET.thresholds["post_rise_tracking_ratio"]):
        evidences.append(_evidence(job, "quality_gate_failed", [observations[0]], 0.0, "人体轨迹有效帧不足，交互风险不可判定。"))
        batch = AdapterBatch(
            schema_version="adapter-batch/1.0", job_id=job.job_id, module=MODULE,
            adapter_version=ADAPTER_VERSION, status=AdapterStatus.LOW_QUALITY,
            started_at=started_at, completed_at=_now(), observations=observations,
            evidences=evidences, diagnostics={"point_count": len(points), "scene_config_id": scene.scene_config_id},
        )
        return validate_batch_for_job(batch, job)

    low_light_threshold = float(RULESET.thresholds["low_illumination_norm"])
    if analysis.illumination_norm < low_light_threshold:
        evidences.append(_evidence(
            job, "low_illumination", [observations[1]],
            (low_light_threshold - analysis.illumination_norm) / low_light_threshold,
            "视频实际亮度低于工程观察门槛，作为环境质量证据。",
        ))

    for zone_type, feature_name in (("HIGH_RISK", "danger_zone_dwell_s"), ("OBSTACLE", "trajectory_intersects_obstacle")):
        zones = [zone for zone in scene.zones if zone.zone_type == zone_type]
        matched = [
            (
                zone,
                _dwell_seconds(points, zone)
                if zone_type == "HIGH_RISK"
                else float(trajectory_intersects_zone(points, zone)),
            )
            for zone in zones
        ]
        matched = [
            (zone, value)
            for zone, value in matched
            if (
                value >= float(RULESET.thresholds["zone_min_dwell_seconds"])
                if zone_type == "HIGH_RISK"
                else bool(value)
            )
        ]
        if matched:
            value = max(dwell for _, dwell in matched) if zone_type == "HIGH_RISK" else True
            observation = _observation(job, feature_name, value, "second" if zone_type == "HIGH_RISK" else None, quality, zone_ids=(zone.zone_id for zone, _ in matched))
            observations.append(observation)
            evidences.append(_evidence(
                job, "high_risk_zone_entry", [observation],
                0.7 if zone_type == "OBSTACLE" else min(max(dwell for _, dwell in matched) / 3.0, 1.0),
                "人体轨迹与人工标定区域发生持续交互；环境证据不能单独升级跌倒事件。",
            ))

    support_zones = [zone for zone in scene.zones if zone.zone_type == "SUPPORT"]
    if support_zones and points:
        distance = min(distance_to_zone((point[1], point[2]), zone) for point in points for zone in support_zones)
        observation = _observation(job, "support_zone_distance_norm", distance, "frame_diagonal_ratio", quality, zone_ids=(zone.zone_id for zone in support_zones))
        observations.append(observation)
        if distance > float(RULESET.thresholds["support_distance_norm"]):
            evidences.append(_evidence(
                job, "high_risk_zone_entry", [observation],
                distance / max(float(RULESET.thresholds["support_distance_norm"]), 1e-6) - 1.0,
                "人体轨迹持续远离人工标定支撑区；仅作为人-环境交互证据。",
            ))

    status = AdapterStatus.SUCCESS if evidences else AdapterStatus.NO_EVIDENCE
    batch = AdapterBatch(
        schema_version="adapter-batch/1.0", job_id=job.job_id, module=MODULE,
        adapter_version=ADAPTER_VERSION, status=status, started_at=started_at,
        completed_at=_now(), observations=observations, evidences=evidences,
        diagnostics={
            "point_count": len(points), "scene_config_id": scene.scene_config_id,
            "illumination_norm": analysis.illumination_norm,
        },
    )
    return validate_batch_for_job(batch, job)
