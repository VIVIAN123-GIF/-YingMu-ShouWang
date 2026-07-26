"""Seven days of safe, explicitly simulated history for memory tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


RESIDENT_ID = "resident-mock-001"
TZ = timezone(timedelta(hours=8))
START = datetime(2026, 7, 19, 9, 0, tzinfo=TZ)

METRICS = (
    ("rise_duration", "sit_to_stand_duration", "rise_duration_baseline_sample", "FALL", "second", (3.4, 3.5, 3.6, 3.5, 3.4, 3.5, 3.6)),
    ("trunk_sway", "trunk_sway_angle", "trunk_sway_baseline_sample", "FALL", "degree", (4.8, 5.0, 5.2, 5.0, 4.9, 5.1, 5.0)),
    ("gait_stability", "gait_stability_score", "gait_stability_baseline_sample", "FALL", "score", (0.88, 0.87, 0.89, 0.88, 0.86, 0.88, 0.87)),
    ("activity_range", "activity_range", "activity_range_baseline_sample", "MENTAL", "zone_count", (4, 4, 5, 4, 4, 5, 4)),
    ("circadian", "sleep_midpoint", "circadian_baseline_sample", "MENTAL", "hour", (2.5, 2.4, 2.6, 2.5, 2.5, 2.4, 2.6)),
)


def safe_history() -> dict[str, list[dict]]:
    observations: list[dict] = []
    evidences: list[dict] = []
    for day_index in range(7):
        timestamp = START + timedelta(days=day_index)
        for metric, feature_name, evidence_type, domain, unit, values in METRICS:
            observation_id = f"obs-memory-{metric}-{day_index + 1:02d}"
            evidence_id = f"evi-memory-{metric}-{day_index + 1:02d}"
            value = values[day_index]
            observations.append(
                {
                    "schema_version": "1.0",
                    "observation_id": observation_id,
                    "resident_id": RESIDENT_ID,
                    "timestamp": timestamp.isoformat(),
                    "source": "mock-history",
                    "feature_name": feature_name,
                    "feature_value": float(value),
                    "unit": unit,
                    "location": "home",
                    "confidence": 0.95,
                    "data_quality": 0.95,
                    "source_mode": "MOCK",
                    "asset_id": None,
                    "simulated": True,
                    "metadata": {"fixture": "seven-day-safe-history", "metric": metric},
                }
            )
            evidences.append(
                {
                    "schema_version": "1.0",
                    "evidence_id": evidence_id,
                    "observation_ids": [observation_id],
                    "resident_id": RESIDENT_ID,
                    "timestamp": timestamp.isoformat(),
                    "risk_domain": domain,
                    "evidence_type": evidence_type,
                    "severity": 0.05,
                    "confidence": 0.95,
                    "data_quality": 0.95,
                    "baseline_value": None,
                    "current_value": float(value),
                    "baseline_deviation": None,
                    "time_scale": "LONG",
                    "location": "home",
                    "explanation": "明确标注的模拟安全历史，仅用于基线和接口测试",
                    "adapter_version": "memory-fixture-v1",
                    "source_mode": "MOCK",
                    "simulated": True,
                }
            )
    return {"observations": observations, "evidence": evidences}
