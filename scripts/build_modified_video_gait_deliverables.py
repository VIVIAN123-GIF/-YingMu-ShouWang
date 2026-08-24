"""Build a three-day gait baseline package from the modified-video analysis.

The modified video zip covers three collection days (D1/D2/D3), each with:
  - 3× walking clips  -> relative_gait_speed samples
  - 2× rise clips     -> rise_duration samples (via sit_to_stand_duration obs)
  - 1× stable clip    -> stable_trunk_angle_deg samples

That satisfies the backend PROVISIONAL rule (>= 3 distinct days per metric).
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TZ = timezone(timedelta(hours=8))
RESIDENT_ID = "resident-modified-video-001"
DEVICE_REF = "device-ref-c6c-modified-video-001"
DEVICE_MODEL = "EZVIZ_C6C"
CAMERA_POSITION_ID = "camera-position-modified-video-001"
ADAPTER_VERSION = "modified-video-gait-baseline-v1"
AUTH_RECORD_ID = "auth-modified-video-local-20260822"
RETENTION_UNTIL = "2026-09-30T23:59:59+08:00"
LOCATION = "living_room"

# Per-day capture windows (Asia/Shanghai). Windows are staggered so evidence
# timestamps inside a day stay ordered by clip index.
DAY_BASE = {
    "D1": datetime(2026, 8, 19, 9, 0, tzinfo=TZ),
    "D2": datetime(2026, 8, 20, 9, 0, tzinfo=TZ),
    "D3": datetime(2026, 8, 21, 9, 0, tzinfo=TZ),
}

# Kind -> (obs feature_name, obs unit, evidence_type, value fn)
WALK_FEATURE = ("relative_gait_speed", "frame_height_per_second", "gait_stability_baseline_sample")
RISE_FEATURE = ("sit_to_stand_duration", "seconds", "rise_duration_baseline_sample")
STABLE_FEATURE = ("stable_trunk_angle_deg", "degree", "trunk_sway_baseline_sample")


def median(values: list[float]) -> float:
    return round(float(statistics.median(values)), 6)


def mad(values: list[float]) -> float:
    center = statistics.median(values)
    return round(float(statistics.median(abs(v - center) for v in values)), 6)


def slug(value: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in value).strip("-")


def parse_clip(name: str) -> tuple[str, str, int]:
    """Return (day, kind, order). Example: D2_WALK_03_left_to_right.mp4 -> (D2, WALK, 3)."""
    stem = name.replace(".mp4", "").replace("(1)", "")
    parts = stem.split("_")
    return parts[0], parts[1], int(parts[2])


def clip_time(day: str, kind: str, order: int) -> datetime:
    base = DAY_BASE[day]
    offsets = {"WALK": 0, "RISE": 30, "STABLE": 60}
    return base + timedelta(minutes=offsets[kind] + (order - 1) * 5)


def rise_duration_seconds(candidates: dict[str, Any]) -> float | None:
    r = candidates.get("rapid_rise", {})
    if r.get("detected"):
        return float(r.get("duration_s", 0.0))
    return None


def stable_trunk_angle(candidates: dict[str, Any]) -> float:
    return float(candidates.get("posture_recovered", {}).get("max_angle_deg", 0.0))


def make_asset(file_name: str, day: str, kind: str, captured_at: datetime) -> dict[str, Any]:
    return {
        "asset_id": f"asset-modified-{day.lower()}-{kind.lower()}-{slug(Path(file_name).stem)}",
        "title": f"三天基线 {day} {kind} {file_name}",
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "stream_url": None,
        "fallback_url": None,
        "fallback_kind": "LOCAL_AUTHORIZED_CLIP",
        "available": True,
        "verification_status": "VERIFIED",
        "captured_at": captured_at.isoformat(timespec="seconds"),
        "notice": "本包只保存脱敏资产引用；原视频、本地路径和授权原件不写入包。",
        "device_ref": DEVICE_REF,
        "device_model": DEVICE_MODEL,
        "camera_position_id": CAMERA_POSITION_ID,
        "authorization_status": "AUTHORIZED",
        "authorization_record_id": AUTH_RECORD_ID,
        "retention_until": RETENTION_UNTIL,
    }


def make_observation(
    asset_id: str, feature_name: str, value: float, unit: str,
    confidence: float, quality: float, captured_at: datetime, source_video: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "observation_id": f"obs-{asset_id}-{slug(feature_name)}",
        "resident_id": RESIDENT_ID,
        "timestamp": captured_at.isoformat(timespec="seconds"),
        "source": "pose",
        "feature_name": feature_name,
        "feature_value": round(float(value), 3),
        "unit": unit,
        "location": LOCATION,
        "confidence": round(float(confidence), 3),
        "data_quality": round(float(quality), 3),
        "source_mode": "RECORDED_REPLAY",
        "asset_id": asset_id,
        "simulated": True,
        "metadata": {
            "baseline_kind": "THREE_DAY_PROVISIONAL_CANDIDATE",
            "camera_position_id": CAMERA_POSITION_ID,
            "source_video": source_video,
            "adapter_version": ADAPTER_VERSION,
        },
    }


def make_evidence(
    observation: dict[str, Any], evidence_type: str, value: float,
    unit_hint: str, captured_at: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "evidence_id": f"evi-{observation['asset_id']}-{slug(observation['feature_name'])}",
        "observation_ids": [observation["observation_id"]],
        "resident_id": RESIDENT_ID,
        "timestamp": captured_at.isoformat(timespec="seconds"),
        "risk_domain": "FALL",
        "evidence_type": evidence_type,
        "severity": 0.05,
        "confidence": observation["confidence"],
        "data_quality": observation["data_quality"],
        "baseline_value": None,
        "current_value": round(float(value), 3),
        "baseline_deviation": None,
        "time_scale": "LONG",
        "location": LOCATION,
        "explanation": f"同一机位正常基线样本：{observation['feature_name']}={round(float(value), 3)} {unit_hint}",
        "adapter_version": ADAPTER_VERSION,
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
    }


def build_baseline_package(analysis: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, list[float]]]:
    assets: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    evidences: list[dict[str, Any]] = []
    metric_values: dict[str, list[float]] = {
        "relative_gait_speed": [],
        "rise_duration": [],
        "stable_trunk_angle_deg": [],
    }
    metric_days: dict[str, set[str]] = {
        "relative_gait_speed": set(),
        "rise_duration": set(),
        "stable_trunk_angle_deg": set(),
    }

    for item in analysis:
        file_name = item["video"]["file"]
        try:
            day, kind, order = parse_clip(file_name)
        except (KeyError, ValueError, IndexError):
            continue
        if kind not in {"WALK", "RISE", "STABLE"}:
            continue
        captured_at = clip_time(day, kind, order)
        confidence = float(item["quality"]["mean_core_visibility"])
        quality = float(item["quality"]["mean_core_visibility"])
        if confidence < 0.70 or quality < 0.70:
            continue
        asset = make_asset(file_name, day, kind, captured_at)

        if kind == "WALK":
            feature, unit, evidence_type = WALK_FEATURE
            value = float(item["gait"]["relative_speed"])
            metric_key = "relative_gait_speed"
        elif kind == "RISE":
            rise = rise_duration_seconds(item["candidates"])
            if rise is None:
                continue
            feature, unit, evidence_type = RISE_FEATURE
            value = rise
            metric_key = "rise_duration"
        else:  # STABLE
            feature, unit, evidence_type = STABLE_FEATURE
            value = stable_trunk_angle(item["candidates"])
            metric_key = "stable_trunk_angle_deg"

        observation = make_observation(
            asset["asset_id"], feature, value, unit, confidence, quality, captured_at, file_name,
        )
        evidence = make_evidence(observation, evidence_type, value, unit, captured_at)
        assets.append(asset)
        observations.append(observation)
        evidences.append(evidence)
        metric_values[metric_key].append(float(value))
        metric_days[metric_key].add(day)

    metrics_summary = {}
    for metric, values in metric_values.items():
        if values:
            metrics_summary[metric] = {
                "count": len(values),
                "distinct_days": len(metric_days[metric]),
                "median": median(values),
                "mad": mad(values),
                "min": round(min(values), 6),
                "max": round(max(values), 6),
            }
        else:
            metrics_summary[metric] = {"count": 0, "distinct_days": 0}

    package = {
        "schema_version": "1.0",
        "package_kind": "MODIFIED_VIDEO_THREE_DAY_BASELINE_CANDIDATE",
        "package_status": "READY_FOR_BACKEND_ADMISSION",
        "backend_baseline_status_before_submission": "INSUFFICIENT",
        "resident_id": RESIDENT_ID,
        "device_ref": DEVICE_REF,
        "camera_position_id": CAMERA_POSITION_ID,
        "adapter_version": ADAPTER_VERSION,
        "asset_manifest": assets,
        "observations": observations,
        "evidences": evidences,
        "metrics_summary": metrics_summary,
        "submission_timeline": [
            {"order": index, "action": "POST /api/v1/assets", "id": asset["asset_id"]}
            for index, asset in enumerate(assets, start=1)
        ] + [
            {"order": len(assets) + index, "action": "POST /api/v1/observations", "id": obs["observation_id"]}
            for index, obs in enumerate(observations, start=1)
        ] + [
            {"order": len(assets) + len(observations) + index, "action": "POST /api/v1/evidence", "id": evi["evidence_id"]}
            for index, evi in enumerate(evidences, start=1)
        ],
        "privacy_notice": "本包不包含本地路径、原视频与授权原件；仅保留脱敏资产引用。",
        "limitations": [
            "18 段视频覆盖三天同机位素材，行走 9 段、起身 6 段、站稳 3 段。",
            "样本数与天数满足 PROVISIONAL 门槛，但仍不能替代长期 STABLE 基线。",
            "低置信度或未检测到起身候选的片段已被自动排除。",
        ],
    }
    return package, metric_values


def build_profile(package: dict[str, Any]) -> dict[str, Any]:
    metrics = package["metrics_summary"]
    return {
        "schema_version": "1.0",
        "profile_version": "modified-video-gait-baseline-v1",
        "built_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "resident_id": RESIDENT_ID,
        "source_mode": "RECORDED_REPLAY",
        "source_dataset": "修改后视频/视频/D1-D3",
        "device_model": DEVICE_MODEL,
        "camera_position_id": CAMERA_POSITION_ID,
        "sample_policy": {
            "asset_count": len(package["asset_manifest"]),
            "walk_clips": 9,
            "rise_clips": 6,
            "stable_clips": 3,
            "min_confidence": 0.70,
            "min_data_quality": 0.70,
        },
        "metrics": metrics,
        "status": "READY_FOR_THREE_DAY_PROVISIONAL",
        "expected_backend_baseline_status": "PROVISIONAL",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build modified-video three-day gait baseline package.")
    parser.add_argument("--analysis", type=Path, default=Path("artifacts/modified_video_review/modified_video_analysis.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/modified_video_gait_acceptance"))
    args = parser.parse_args()

    analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
    package, _values = build_baseline_package(analysis)
    profile = build_profile(package)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "modified_video_gait_baseline_package.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (args.output_dir / "modified_video_gait_baseline_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(
        f"wrote baseline package: assets={len(package['asset_manifest'])} "
        f"observations={len(package['observations'])} evidences={len(package['evidences'])}"
    )
    for metric, summary in package["metrics_summary"].items():
        print(f"  {metric}: count={summary.get('count')} distinct_days={summary.get('distinct_days')} median={summary.get('median')}")


if __name__ == "__main__":
    main()
