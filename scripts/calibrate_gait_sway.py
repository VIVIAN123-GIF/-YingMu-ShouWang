"""Compare authorized private Assets without exposing media or storage identifiers."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from backend.db.database import AsyncSessionLocal, engine
from backend.db.models import Asset
from backend.service.serialization import aware
from backend.service.snapshot_asset_service import SnapshotAssetError, resolve_private_asset_path
from contracts.v1.gait_adapter import ADAPTER_VERSION
from contracts.v1.gait_video import GaitVideoError, extract_gait_features


@dataclass(frozen=True)
class SampleResult:
    sample_ref: str
    label: str
    result: str
    amplitude_deg: float | None
    rise_duration_s: float | None
    window_type: str | None
    failure_reason: str | None


def evaluate_calibration(
    samples: list[SampleResult], *, current_threshold: float
) -> dict[str, Any]:
    positives = [
        item.amplitude_deg
        for item in samples
        if item.label == "POSITIVE"
        and item.result == "VALID"
        and item.window_type == "POST_RISE"
        and item.amplitude_deg is not None
    ]
    negatives = [
        item.amplitude_deg
        for item in samples
        if item.label == "NEGATIVE"
        and item.result == "VALID"
        and item.amplitude_deg is not None
    ]
    separable = bool(positives and negatives and min(positives) > max(negatives))
    if separable:
        recommended = round((min(positives) + max(negatives)) / 2.0, 3)
        status = "CALIBRATION_SEPARABLE"
    else:
        recommended = current_threshold
        status = "CALIBRATION_INCONCLUSIVE"
    return {
        "status": status,
        "positive_valid_count": len(positives),
        "negative_valid_count": len(negatives),
        "positive_min_amplitude_deg": min(positives) if positives else None,
        "negative_max_amplitude_deg": max(negatives) if negatives else None,
        "current_threshold_deg": current_threshold,
        "recommended_threshold_deg": recommended,
        "threshold_changed": separable and recommended != current_threshold,
    }


async def _load_sample(asset_id: str, *, label: str, sample_ref: str) -> SampleResult:
    async with AsyncSessionLocal() as db:
        asset = (
            await db.execute(select(Asset).where(Asset.asset_id == asset_id))
        ).scalar_one_or_none()
    if asset is None:
        return SampleResult(sample_ref, label, "INVALID", None, None, None, "ASSET_NOT_FOUND")
    if (
        asset.simulated
        or asset.source_mode != "LIVE_DEVICE"
        or asset.authorization_status != "AUTHORIZED"
        or asset.retention_until is None
        or aware(asset.retention_until) <= datetime.now(timezone.utc).astimezone()
        or not (asset.content_type or "").lower().startswith("video/")
        or not asset.storage_key
        or not asset.content_sha256
    ):
        return SampleResult(sample_ref, label, "INVALID", None, None, None, "ASSET_NOT_AUTHORIZED_VIDEO")
    try:
        path = resolve_private_asset_path(asset.storage_key)
        if not path.is_file():
            return SampleResult(sample_ref, label, "INVALID", None, None, None, "PRIVATE_MEDIA_MISSING")
        with path.open("rb") as media:
            digest = hashlib.file_digest(media, "sha256").hexdigest()
        if digest != asset.content_sha256:
            return SampleResult(sample_ref, label, "INVALID", None, None, None, "CONTENT_HASH_MISMATCH")
        features, diagnostics = await asyncio.to_thread(extract_gait_features, path)
    except (GaitVideoError, SnapshotAssetError, OSError):
        return SampleResult(sample_ref, label, "INVALID", None, None, None, "FEATURE_EXTRACTION_FAILED")
    amplitude = features.get("trunk_sway_angle_deg")
    rise_duration = features.get("rise_duration_s")
    window_type = diagnostics.get("trunk_sway_window_type")
    failure_reason = diagnostics.get("trunk_sway_failure_reason")
    result = "VALID" if isinstance(amplitude, (int, float)) else "INVALID"
    return SampleResult(
        sample_ref,
        label,
        result,
        float(amplitude) if isinstance(amplitude, (int, float)) else None,
        float(rise_duration) if isinstance(rise_duration, (int, float)) else None,
        str(window_type) if window_type else None,
        str(failure_reason) if failure_reason else None,
    )


async def _run(args: argparse.Namespace) -> int:
    samples: list[SampleResult] = []
    for index, asset_id in enumerate(args.positive_asset, start=1):
        samples.append(
            await _load_sample(asset_id, label="POSITIVE", sample_ref=f"positive-{index:02d}")
        )
    for index, asset_id in enumerate(args.negative_asset, start=1):
        samples.append(
            await _load_sample(asset_id, label="NEGATIVE", sample_ref=f"negative-{index:02d}")
        )
    calibration = evaluate_calibration(samples, current_threshold=args.current_threshold)
    report = {
        "schema_version": "gait-sway-calibration/1.0",
        "adapter_version": ADAPTER_VERSION,
        "samples": [item.__dict__ for item in samples],
        "calibration": calibration,
        "contains_asset_id": False,
        "contains_device_identifier": False,
        "contains_media_path": False,
        "contains_credentials": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if calibration["status"] == "CALIBRATION_SEPARABLE" else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calibrate post-rise trunk sway from authorized private Asset references."
    )
    parser.add_argument("--positive-asset", action="append", required=True)
    parser.add_argument("--negative-asset", action="append", required=True)
    parser.add_argument("--current-threshold", type=float, default=12.0)
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    finally:
        asyncio.run(engine.dispose())


if __name__ == "__main__":
    raise SystemExit(main())
