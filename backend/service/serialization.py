import json
from datetime import datetime, timezone, timedelta
from typing import Any

CN_TZ = timezone(timedelta(hours=8))


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=CN_TZ)


def utc_naive_to_cn(value: datetime) -> datetime:
    """Convert timestamps explicitly stored as naive UTC into Beijing time."""
    source = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return source.astimezone(CN_TZ)


def cn_now_naive() -> datetime:
    """Return current Beijing wall time for tables using local naive values."""
    return datetime.now(CN_TZ).replace(tzinfo=None)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def observation_dict(row: Any) -> dict[str, Any]:
    value = row.feature_value
    try:
        value = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        pass
    return {"schema_version": row.schema_version, "observation_id": row.observation_id,
            "resident_id": row.resident_id, "timestamp": aware(row.timestamp), "source": row.source,
            "feature_name": row.feature_name, "feature_value": value, "unit": row.unit,
            "location": row.location, "confidence": row.confidence, "data_quality": row.data_quality,
            "source_mode": row.source_mode, "asset_id": row.asset_id, "simulated": row.simulated,
            "metadata": loads(row.extra_metadata, None)}


def evidence_dict(row: Any) -> dict[str, Any]:
    return {"schema_version": row.schema_version, "evidence_id": row.evidence_id,
            "observation_ids": loads(row.observation_ids, []), "resident_id": row.resident_id,
            "timestamp": aware(row.timestamp), "risk_domain": row.risk_domain,
            "evidence_type": row.evidence_type, "severity": row.severity, "confidence": row.confidence,
            "data_quality": row.data_quality, "baseline_value": row.baseline_value,
            "current_value": row.current_value, "baseline_deviation": row.baseline_deviation,
            "time_scale": row.time_scale, "location": row.location, "explanation": row.explanation,
            "adapter_version": row.adapter_version, "source_mode": row.source_mode,
            "simulated": row.simulated}


def event_dict(row: Any) -> dict[str, Any]:
    return {"schema_version": row.schema_version, "event_id": row.event_id,
            "resident_id": row.resident_id, "created_at": aware(row.created_at),
            "updated_at": aware(row.updated_at), "primary_domain": row.primary_domain,
            "related_domains": loads(row.related_domains, []), "risk_level": row.risk_level,
            "risk_score": row.risk_score, "evidence_ids": loads(row.evidence_ids, []),
            "evidence_summary": loads(row.evidence_summary, []), "time_horizon": row.time_horizon,
            "recommended_action": row.recommended_action, "intervention_policy": row.intervention_policy,
            "status": row.status, "ruleset_version": row.ruleset_version,
            "source_mode": row.source_mode, "simulated": row.simulated}


def intervention_dict(row: Any) -> dict[str, Any]:
    return {"schema_version": row.schema_version, "result_id": row.result_id,
            "event_id": row.event_id, "started_at": aware(row.started_at),
            "completed_at": aware(row.completed_at) if row.completed_at else None,
            "action_type": row.action_type, "tool_name": row.tool_name,
            "delivery_status": row.delivery_status, "resident_response": row.resident_response,
            "family_feedback": row.family_feedback, "risk_after": row.risk_after,
            "resolved": row.resolved, "resolution_reason": row.resolution_reason,
            "operator": row.operator, "source_mode": row.source_mode,
            "simulated": row.simulated}
