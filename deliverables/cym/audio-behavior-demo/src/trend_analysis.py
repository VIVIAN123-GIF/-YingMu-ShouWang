from datetime import date, datetime
from statistics import median

from evidence import build_evidence, validate_evidence_collection
from observation import build_observation, validate_observation_collection


SOURCE_MODES = {"LIVE_DEVICE", "RECORDED_REPLAY", "PUBLIC_DATASET", "MOCK"}
METRICS = {
    "activity_range": ("visited_region_count", "count"),
    "room_transition": ("region_transition_count", "count"),
    "day_night_rhythm": ("daytime_activity_ratio", "ratio"),
}


class TrendInputError(ValueError):
    pass


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _score(value):
    return round(max(0.0, min(1.0, float(value))), 4)


def _baseline_status(day_count):
    if day_count < 3:
        return "INSUFFICIENT"
    if day_count < 7:
        return "PROVISIONAL"
    return "STABLE"


def _daytime_ratio(item):
    daytime = item["daytime_active_minutes"]
    nighttime = item["nighttime_active_minutes"]
    total = daytime + nighttime
    return daytime / total if total else 0.0


def _median_and_mad(values):
    center = float(median(values))
    return center, float(median([abs(value - center) for value in values]))


def _robust_deviation(current, baseline, mad):
    # 1.4826 converts MAD to a normal-distribution scale.  A zero MAD uses a
    # bounded fallback so identical historical samples do not divide by zero.
    scale = 1.4826 * mad if mad > 0 else max(abs(baseline), 1.0)
    return round((current - baseline) / scale, 4)


def validate_daily_activity(payload):
    if not isinstance(payload, dict):
        raise TrendInputError("日活动汇总必须是JSON对象")
    required = {"run_id", "resident_id", "location", "source_mode", "simulated", "days"}
    missing = sorted(required - payload.keys())
    if missing:
        raise TrendInputError(f"日活动汇总缺少字段：{', '.join(missing)}")
    if payload["source_mode"] not in SOURCE_MODES:
        raise TrendInputError("source_mode不是冻结枚举")
    if not isinstance(payload["simulated"], bool):
        raise TrendInputError("simulated必须是布尔值")
    if not isinstance(payload["days"], list) or len(payload["days"]) < 2:
        raise TrendInputError("至少需要两天活动汇总（一日基线加一日当前）")

    dates = set()
    for item in payload["days"]:
        if not isinstance(item, dict):
            raise TrendInputError("days中的每项必须是对象")
        missing_fields = {
            "date", "visited_region_count", "region_transition_count",
            "daytime_active_minutes", "nighttime_active_minutes", "data_quality",
        } - item.keys()
        if missing_fields:
            raise TrendInputError(f"单日汇总缺少字段：{', '.join(sorted(missing_fields))}")
        try:
            parsed_date = date.fromisoformat(item["date"])
        except (TypeError, ValueError) as error:
            raise TrendInputError("date必须是YYYY-MM-DD") from error
        if parsed_date in dates:
            raise TrendInputError("days不能出现重复日期")
        dates.add(parsed_date)
        for field in (
            "visited_region_count", "region_transition_count",
            "daytime_active_minutes", "nighttime_active_minutes", "data_quality",
        ):
            value = item[field]
            if not _is_number(value) or value < 0:
                raise TrendInputError(f"{field}必须是非负数字")
        if item["data_quality"] > 1:
            raise TrendInputError("data_quality必须在0到1")
    return payload


def build_trend_bundle(payload):
    """Build long-term behavior Observations and non-diagnostic Evidence.

    The final day is treated as the current day. Earlier days form a rolling
    personal baseline using median plus MAD. Trend Evidence is emitted only
    when there are at least seven prior days, as required for a stable baseline.
    """
    validate_daily_activity(payload)
    days = sorted(payload["days"], key=lambda item: item["date"])
    baseline_days = days[:-1]
    current_day = days[-1]
    status = _baseline_status(len(baseline_days))
    timestamp = f"{current_day['date']}T23:59:59+08:00"
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as error:  # Defensive guard for constructed timestamps.
        raise TrendInputError("无法构造带时区的统计时间") from error

    metric_values = {
        "activity_range": [float(day["visited_region_count"]) for day in baseline_days],
        "room_transition": [float(day["region_transition_count"]) for day in baseline_days],
        "day_night_rhythm": [_daytime_ratio(day) for day in baseline_days],
    }
    current_values = {
        "activity_range": float(current_day["visited_region_count"]),
        "room_transition": float(current_day["region_transition_count"]),
        "day_night_rhythm": _daytime_ratio(current_day),
    }
    quality = _score(min(
        float(current_day["data_quality"]),
        float(median([day["data_quality"] for day in baseline_days])),
    ))
    confidence = 0.80 if status == "STABLE" else 0.50
    common = {
        "resident_id": payload["resident_id"],
        "timestamp": timestamp,
        "source": "behavior_trend",
        "location": payload["location"],
        "confidence": confidence,
        "data_quality": quality,
        "source_mode": payload["source_mode"],
        "asset_id": payload.get("asset_id"),
        "simulated": payload["simulated"],
    }

    observations = []
    baselines = {}
    for metric_name, (feature_suffix, unit) in METRICS.items():
        baseline, mad = _median_and_mad(metric_values[metric_name])
        current = current_values[metric_name]
        baselines[metric_name] = {
            "baseline": baseline,
            "mad": mad,
            "current": current,
            "deviation": _robust_deviation(current, baseline, mad),
        }
        metadata = {
            "adapter_version": "trend-adapter-v1",
            "baseline_method": "rolling_median_mad",
            "baseline_days": len(baseline_days),
            "baseline_status": status,
            "baseline_mad": round(mad, 4),
            "threshold_status": "DEMO_UNCALIBRATED",
        }
        observations.extend([
            build_observation(
                observation_id=f"obs-trend-{metric_name}-baseline-{payload['run_id']}",
                feature_name=f"baseline_median_{feature_suffix}",
                feature_value=round(baseline, 4),
                unit=unit,
                metadata=metadata,
                **common,
            ),
            build_observation(
                observation_id=f"obs-trend-{metric_name}-current-{payload['run_id']}",
                feature_name=f"current_{feature_suffix}",
                feature_value=round(current, 4),
                unit=unit,
                metadata=metadata,
                **common,
            ),
        ])

    evidence_items = []
    if status == "STABLE":
        activity = baselines["activity_range"]
        if activity["current"] < activity["baseline"]:
            evidence_items.append(_build_evidence(
                payload, timestamp, "activity_range_decline", "activity_range",
                activity, "当前访问区域数低于个人滚动基线；仅提示活动范围变化，"
                "需结合外出、生病和家属反馈复核，不作心理诊断",
            ))
        transitions = baselines["room_transition"]
        if transitions["current"] < transitions["baseline"]:
            evidence_items.append(_build_evidence(
                payload, timestamp, "room_transition_decline", "room_transition",
                transitions, "当前房间转换次数低于个人滚动基线；仅提示日常活动变化，"
                "需排除外出和场景覆盖变化，不作心理诊断",
            ))
        rhythm = baselines["day_night_rhythm"]
        if abs(rhythm["current"] - rhythm["baseline"]) >= 0.20:
            evidence_items.append(_build_evidence(
                payload, timestamp, "day_night_rhythm_change", "day_night_rhythm",
                rhythm, "当前昼间活动占比偏离个人滚动基线；仅提示作息变化，"
                "需结合生活安排和人工反馈复核，不作心理诊断",
            ))

    return {
        "schema_version": "1.0",
        "source_mode": payload["source_mode"],
        "simulated": payload["simulated"],
        "baseline_status": status,
        "baseline_days": len(baseline_days),
        "threshold_status": "DEMO_UNCALIBRATED",
        "observations": validate_observation_collection(observations),
        "evidence": validate_evidence_collection(evidence_items),
    }


def _build_evidence(payload, timestamp, evidence_type, metric_name, values, explanation):
    baseline = values["baseline"]
    current = values["current"]
    if metric_name == "day_night_rhythm":
        severity = abs(current - baseline)
    else:
        severity = max(0.0, baseline - current) / max(baseline, 1.0)
    return build_evidence(
        evidence_id=f"evi-trend-{evidence_type}-{payload['run_id']}",
        observation_ids=[
            f"obs-trend-{metric_name}-baseline-{payload['run_id']}",
            f"obs-trend-{metric_name}-current-{payload['run_id']}",
        ],
        resident_id=payload["resident_id"],
        timestamp=timestamp,
        risk_domain="MENTAL",
        evidence_type=evidence_type,
        severity=_score(severity),
        confidence=0.80,
        data_quality=_score(min(1.0, max(0.0, payload["days"][-1]["data_quality"]))),
        baseline_value=round(baseline, 4),
        current_value=round(current, 4),
        baseline_deviation=values["deviation"],
        time_scale="LONG",
        location=payload["location"],
        explanation=explanation,
        adapter_version="trend-adapter-v1",
        source_mode=payload["source_mode"],
        simulated=payload["simulated"],
    )
