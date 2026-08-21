"""Convert an OpenCV behavior summary into deterministic Observations."""

from datetime import datetime

from observation import build_observation, validate_observation_collection
from pacing import analyze_pacing


ADAPTER_VERSION = "behavior-adapter-v3"


def _timestamp(value):
    if value is None:
        return datetime.now().astimezone().isoformat(timespec="seconds")
    return value


def _namespace(job_id, asset_id):
    # The legacy path remains deterministic for old callers. New worker calls
    # must provide job_id so retries of the same window reuse the same IDs.
    return str(job_id or asset_id or "legacy-behavior")


def build_behavior_observations(
    summary,
    *,
    resident_id,
    location=None,
    asset_id=None,
    timestamp=None,
    job_id=None,
):
    """Build direct observations using capture time, never processing time."""
    frame_count = int(summary.get("frames_processed", 0))
    detected_ratio = (
        float(summary.get("detected_frames", 0)) / frame_count
        if frame_count
        else 0.0
    )
    tracking_ratio = (
        float(summary.get("tracked_frames", summary.get("detected_frames", 0)))
        / frame_count
        if frame_count
        else 0.0
    )
    detection_quality = round(min(1.0, max(0.0, tracking_ratio)), 4)
    activity_counts = summary.get("activity_counts") or {}
    dominant_activity = (
        max(activity_counts, key=activity_counts.get) if activity_counts else "UNKNOWN"
    )
    timestamp = _timestamp(timestamp or summary.get("captured_at"))
    namespace = _namespace(job_id, asset_id)
    common = {
        "resident_id": resident_id,
        "timestamp": timestamp,
        "source": "tracking",
        "location": location,
        "confidence": round(min(0.70, 0.30 + 0.40 * detection_quality), 4),
        "data_quality": detection_quality,
        "source_mode": summary.get("source_mode", "MOCK"),
        "asset_id": asset_id,
        "simulated": bool(summary.get("simulated", False)),
        "metadata": {
            "adapter_version": ADAPTER_VERSION,
            "threshold_status": summary.get("threshold_status", "DEMO_UNCALIBRATED"),
            "frames_processed": frame_count,
            "score_status": "DEMO_UNCALIBRATED",
            "detection_status": "OK" if detection_quality >= 0.50 else "LOW_DETECTION",
            "missing_frame_ratio": round(1.0 - detection_quality, 4),
            "hog_detection_quality": round(
                min(1.0, max(0.0, detected_ratio)), 4
            ),
            "scene_config_id": summary.get("scene_config_id"),
        },
    }
    feature_specs = [
        ("max_person_count", summary.get("max_person_count", 0), "count"),
        ("person_detected_frame_ratio", round(detected_ratio, 4), "ratio"),
        ("dominant_activity_level", dominant_activity, None),
        ("max_motion_area", summary.get("max_motion_area", 0), "pixel"),
        ("track_point_count", summary.get("track_points", 0), "count"),
        ("travel_distance", summary.get("travel_distance_px", 0.0), "pixel"),
    ]
    if "tracked_frames" in summary:
        feature_specs.insert(
            2,
            ("person_tracked_frame_ratio", round(tracking_ratio, 4), "ratio"),
        )
    region_statistics = summary.get("region_statistics")
    if region_statistics:
        max_dwell = max(region_statistics.get("dwell_seconds", {}).values(), default=0.0)
        feature_specs.extend(
            [
                ("visited_region_count", region_statistics.get("visited_region_count", 0), "count"),
                ("region_transition_count", region_statistics.get("transition_count", 0), "count"),
                ("max_region_dwell_seconds", max_dwell, "second"),
                (
                    "visited_region_sequence",
                    ">".join(region_statistics.get("region_sequence", [])) or "NONE",
                    None,
                ),
            ]
        )
        if job_id is not None:
            pacing = analyze_pacing(region_statistics)
            feature_specs.extend(
                [
                    ("region_revisit_count", pacing["revisit_count"], "count"),
                    (
                        "alternating_region_transition_count",
                        pacing["alternating_transition_count"],
                        "count",
                    ),
                    ("pacing_pattern_score", pacing["pacing_pattern_score"], "ratio"),
                ]
            )
    observations = [
        build_observation(
            observation_id=f"obs-{namespace}-behavior-{feature_name}",
            feature_name=feature_name,
            feature_value=feature_value,
            unit=unit,
            **common,
        )
        for feature_name, feature_value, unit in feature_specs
    ]
    return validate_observation_collection(observations)
