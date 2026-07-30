from datetime import datetime

from evidence import build_evidence, validate_evidence_collection
from observation import build_observation, validate_observation_collection


def _score(value):
    return round(max(0.0, min(1.0, float(value))), 4)


def _validate_settings(settings):
    required = {
        "run_id",
        "resident_id",
        "timestamp",
        "baseline_region_count",
        "current_region_count",
        "mock_visitor_count",
        "mock_authorization_matched",
        "mock_dwell_region",
        "mock_dwell_seconds",
        "mock_dwell_threshold_seconds",
    }
    missing = sorted(required - settings.keys())
    if missing:
        raise ValueError(f"模拟统计缺少字段：{', '.join(missing)}")
    try:
        parsed = datetime.fromisoformat(settings["timestamp"].replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError("timestamp必须是有效ISO 8601时间") from error
    if parsed.utcoffset() is None:
        raise ValueError("timestamp必须包含时区")
    if not isinstance(settings["mock_authorization_matched"], bool):
        raise ValueError("mock_authorization_matched必须是布尔值")
    for name in (
        "baseline_region_count",
        "current_region_count",
        "mock_visitor_count",
        "mock_dwell_seconds",
        "mock_dwell_threshold_seconds",
    ):
        value = settings[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"{name}必须是非负数字")
    if settings["baseline_region_count"] <= 0:
        raise ValueError("baseline_region_count必须大于0")
    if settings["mock_dwell_threshold_seconds"] <= 0:
        raise ValueError("mock_dwell_threshold_seconds必须大于0")
    if settings["current_region_count"] >= settings["baseline_region_count"]:
        raise ValueError("activity_range_decline要求当前区域数低于个人基线")
    if settings["mock_visitor_count"] <= 0 or settings["mock_authorization_matched"]:
        raise ValueError("unauthorized_visitor样例要求存在访客且MOCK授权未匹配")
    if settings["mock_dwell_seconds"] <= settings["mock_dwell_threshold_seconds"]:
        raise ValueError("unusual_dwell_time样例要求停留时间超过Demo阈值")


def build_behavior_evidence_bundle(settings):
    """Build three privacy-safe MOCK Evidence items with source-matched Observations."""
    _validate_settings(settings)
    run_id = settings["run_id"]
    resident_id = settings["resident_id"]
    timestamp = settings["timestamp"]
    location = settings.get("location")

    common = {
        "resident_id": resident_id,
        "timestamp": timestamp,
        "confidence": 0.78,
        "data_quality": 0.80,
        "source_mode": "MOCK",
        "asset_id": None,
        "simulated": True,
        "location": location,
    }
    observation_specs = [
        (
            "activity-baseline",
            "behavior_statistics",
            "baseline_visited_region_count",
            settings["baseline_region_count"],
            "count",
            location,
        ),
        (
            "activity-current",
            "behavior_statistics",
            "current_visited_region_count",
            settings["current_region_count"],
            "count",
            location,
        ),
        (
            "visitor-count",
            "mock_authorization",
            "visitor_person_count",
            settings["mock_visitor_count"],
            "count",
            location,
        ),
        (
            "visitor-authorized",
            "mock_authorization",
            "visitor_authorization_matched",
            settings["mock_authorization_matched"],
            None,
            location,
        ),
        (
            "dwell-observed",
            "mock_dwell_statistics",
            "visitor_dwell_seconds",
            settings["mock_dwell_seconds"],
            "second",
            settings["mock_dwell_region"],
        ),
        (
            "dwell-threshold",
            "mock_dwell_statistics",
            "demo_dwell_threshold_seconds",
            settings["mock_dwell_threshold_seconds"],
            "second",
            settings["mock_dwell_region"],
        ),
    ]
    observations = validate_observation_collection(
        [
            build_observation(
                observation_id=f"obs-{suffix}-{run_id}",
                source=source,
                feature_name=feature_name,
                feature_value=value,
                unit=unit,
                location=observation_location,
                metadata={
                    "adapter_version": "behavior-adapter-v1.1",
                    "threshold_status": "DEMO_UNCALIBRATED",
                    "purpose": "interface_rehearsal",
                },
                **{key: value for key, value in common.items() if key != "location"},
            )
            for suffix, source, feature_name, value, unit, observation_location in observation_specs
        ]
    )

    baseline_regions = float(settings["baseline_region_count"])
    current_regions = float(settings["current_region_count"])
    decline_ratio = max(0.0, baseline_regions - current_regions) / baseline_regions
    dwell_seconds = float(settings["mock_dwell_seconds"])
    dwell_threshold = float(settings["mock_dwell_threshold_seconds"])
    dwell_excess_ratio = max(0.0, dwell_seconds - dwell_threshold) / dwell_threshold

    evidence_items = validate_evidence_collection(
        [
            build_evidence(
                evidence_id=f"evi-activity-range-{run_id}",
                observation_ids=[
                    f"obs-activity-baseline-{run_id}",
                    f"obs-activity-current-{run_id}",
                ],
                resident_id=resident_id,
                timestamp=timestamp,
                risk_domain="MENTAL",
                evidence_type="activity_range_decline",
                severity=_score(decline_ratio),
                confidence=0.78,
                data_quality=0.80,
                baseline_value=baseline_regions,
                current_value=current_regions,
                baseline_deviation=current_regions - baseline_regions,
                time_scale="LONG",
                location=location,
                explanation=(
                    "模拟多日统计显示访问区域数低于个人基线；仅表示活动范围变化，"
                    "需结合外出、生病和家属反馈复核，不作心理诊断"
                ),
                adapter_version="behavior-adapter-v1.1",
                source_mode="MOCK",
                simulated=True,
            ),
            build_evidence(
                evidence_id=f"evi-unauthorized-visitor-{run_id}",
                observation_ids=[
                    f"obs-visitor-count-{run_id}",
                    f"obs-visitor-authorized-{run_id}",
                ],
                resident_id=resident_id,
                timestamp=timestamp,
                risk_domain="FRAUD",
                evidence_type="unauthorized_visitor",
                severity=0.55 if settings["mock_visitor_count"] and not settings["mock_authorization_matched"] else 0.0,
                confidence=0.74,
                data_quality=0.80,
                baseline_value=None,
                current_value=float(settings["mock_visitor_count"]),
                baseline_deviation=None,
                time_scale="SHORT",
                location=location,
                explanation=(
                    "MOCK授权信息未匹配，身份仍未确认；仅建议家属进行身份核验，"
                    "不表示系统识别出诈骗人员"
                ),
                adapter_version="behavior-adapter-v1.1",
                source_mode="MOCK",
                simulated=True,
            ),
            build_evidence(
                evidence_id=f"evi-unusual-dwell-{run_id}",
                observation_ids=[
                    f"obs-dwell-observed-{run_id}",
                    f"obs-dwell-threshold-{run_id}",
                ],
                resident_id=resident_id,
                timestamp=timestamp,
                risk_domain="FRAUD",
                evidence_type="unusual_dwell_time",
                severity=_score(dwell_excess_ratio),
                confidence=0.70,
                data_quality=0.78,
                baseline_value=dwell_threshold,
                current_value=dwell_seconds,
                baseline_deviation=dwell_seconds - dwell_threshold,
                time_scale="SHORT",
                location=settings["mock_dwell_region"],
                explanation=(
                    "MOCK访客停留时间超过未标定的Demo阈值；该结果只提示需要核验的"
                    "交互特征，不能据此判断诈骗"
                ),
                adapter_version="behavior-adapter-v1.1",
                source_mode="MOCK",
                simulated=True,
            ),
        ]
    )
    return {
        "schema_version": "1.0",
        "source_mode": "MOCK",
        "simulated": True,
        "threshold_status": "DEMO_UNCALIBRATED",
        "observations": observations,
        "evidence": evidence_items,
    }
