#!/usr/bin/env python3
"""Build a privacy-safe C6c provisional-baseline submission package.

The input manifest contains only asset references and already extracted engineering
metrics. Local video paths may be present in the input for an operator workflow,
but are deliberately never copied into the generated package.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


METRICS = {
    "rise_duration_seconds": ("sit_to_stand_duration", "second"),
    "relative_gait_speed_frame_heights_per_second": (
        "relative_gait_speed",
        "frame_height_per_second",
    ),
    "stable_trunk_angle_deg": ("stable_trunk_angle_deg", "degree"),
}


def aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timezone offset is required: {value}")
    return parsed


def slug(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in value).strip("-")


def build_package(manifest: dict) -> dict:
    resident_id = manifest["resident_id"]
    device_ref = manifest["device_ref"]
    camera_position_id = manifest["camera_position_id"]
    device_model = manifest.get("device_model", "EZVIZ_C6C")
    authorization_status = manifest.get("authorization_status", "PENDING")
    authorization_record_id = manifest.get("authorization_record_id")
    retention_until = manifest.get("retention_until")
    if retention_until:
        aware(retention_until)

    assets = {}
    observations = []
    evidences = []
    distinct_dates = set()
    quality_ready = True
    latest_capture = None

    for day in manifest.get("recordings", []):
        timestamp = aware(day["captured_at"])
        latest_capture = max(latest_capture, timestamp) if latest_capture else timestamp
        distinct_dates.add(timestamp.date().isoformat())
        asset_id = day["asset_id"]
        assets[asset_id] = {
            "asset_id": asset_id,
            "title": day.get("title", f"{timestamp.date().isoformat()} 正常动作脱敏片段"),
            "source_mode": "RECORDED_REPLAY",
            "simulated": True,
            "stream_url": None,
            "fallback_url": None,
            "fallback_kind": "LOCAL_AUTHORIZED_CLIP",
            "available": bool(day.get("asset_available", False)),
            "verification_status": "VERIFIED" if authorization_status == "AUTHORIZED" else "PENDING_ASSET",
            "captured_at": timestamp.isoformat(),
            "notice": "本包仅保存脱敏资产引用；本地路径、视频和授权原件不写入Git。",
            "device_ref": device_ref,
            "device_model": device_model,
            "camera_position_id": camera_position_id,
            "authorization_status": authorization_status,
            "authorization_record_id": authorization_record_id,
            "retention_until": retention_until,
        }
        confidence = float(day.get("confidence", 0.0))
        data_quality = float(day.get("data_quality", 0.0))
        quality_ready = quality_ready and confidence >= 0.70 and data_quality >= 0.70
        day_slug = slug(timestamp.date().isoformat())
        for input_name, (feature_name, unit) in METRICS.items():
            if input_name not in day:
                raise ValueError(f"recording {timestamp.date()} is missing {input_name}")
            value = float(day[input_name])
            observation_id = f"obs-baseline-{day_slug}-{slug(feature_name)}"
            evidence_id = f"evi-baseline-{day_slug}-{slug(feature_name)}"
            observations.append({
                "schema_version": "1.0",
                "observation_id": observation_id,
                "resident_id": resident_id,
                "timestamp": timestamp.isoformat(),
                "source": "pose",
                "feature_name": feature_name,
                "feature_value": value,
                "unit": unit,
                "location": day.get("location", "living_room"),
                "confidence": confidence,
                "data_quality": data_quality,
                "source_mode": "RECORDED_REPLAY",
                "asset_id": asset_id,
                "simulated": True,
                "metadata": {
                    "baseline_kind": "PROVISIONAL_CANDIDATE",
                    "camera_position_id": camera_position_id,
                    "adapter_version": manifest.get("adapter_version", "baseline-adapter-v1"),
                },
            })
            evidences.append({
                "schema_version": "1.0",
                "evidence_id": evidence_id,
                "observation_ids": [observation_id],
                "resident_id": resident_id,
                "timestamp": timestamp.isoformat(),
                "risk_domain": "FALL",
                "evidence_type": "normal_baseline_sample",
                "severity": 0.0,
                "confidence": confidence,
                "data_quality": data_quality,
                "baseline_value": None,
                "current_value": value,
                "baseline_deviation": None,
                "time_scale": "LONG",
                "location": day.get("location", "living_room"),
                "explanation": f"同一授权C6c、同一机位的安全正常样本：{feature_name}={value:g} {unit}",
                "adapter_version": manifest.get("adapter_version", "baseline-adapter-v1"),
                "source_mode": "RECORDED_REPLAY",
                "simulated": True,
            })

    retention_ready = bool(
        retention_until
        and latest_capture
        and aware(retention_until) >= latest_capture
    )
    ready = bool(
        len(distinct_dates) >= 3
        and len(observations) == len(distinct_dates) * len(METRICS)
        and quality_ready
        and device_model == "EZVIZ_C6C"
        and device_ref
        and camera_position_id
        and authorization_status == "AUTHORIZED"
        and authorization_record_id
        and retention_ready
    )
    status = "READY" if ready else "PENDING_ASSET"
    return {
        "schema_version": "1.0",
        "package_kind": "PROVISIONAL_BASELINE_CANDIDATES",
        "package_status": status,
        "baseline_status_before_submission": "INSUFFICIENT",
        "resident_id": resident_id,
        "device_ref": device_ref,
        "camera_position_id": camera_position_id,
        "distinct_dates": sorted(distinct_dates),
        "progress": {"observed_days": len(distinct_dates), "provisional_target_days": 3},
        "asset_manifest": list(assets.values()),
        "observations": observations,
        "evidences": evidences,
        "submission_timeline": [
            {"step": 1, "method": "POST", "path": "/api/v1/assets", "items": list(assets)},
            {"step": 2, "method": "POST", "path": "/api/v1/observations", "items": [item["observation_id"] for item in observations]},
            {"step": 3, "method": "POST", "path": "/api/v1/evidence", "items": [item["evidence_id"] for item in evidences]},
            {"step": 4, "method": "GET", "path": f"/api/v1/residents/{resident_id}/baseline"},
        ],
        "privacy_notice": "source_path/local_path, video bytes, credentials and authorization originals are excluded.",
        "exclusion_policy": "Backend admits only authorized C6c, same-position, GREEN, quality>=0.70 safe samples.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a C6c provisional baseline package")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package = build_package(json.loads(args.manifest.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{package['package_status']}: {package['progress']['observed_days']}/3 dates; "
        f"assets={len(package['asset_manifest'])}; observations={len(package['observations'])}; "
        f"evidences={len(package['evidences'])}"
    )


if __name__ == "__main__":
    main()
