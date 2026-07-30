import math
from datetime import datetime


SCHEMA_VERSION = "1.0"

SOURCE_MODES = {
    "LIVE_DEVICE",
    "RECORDED_REPLAY",
    "PUBLIC_DATASET",
    "MOCK",
}

REQUIRED_FIELDS = {
    "schema_version",
    "observation_id",
    "resident_id",
    "timestamp",
    "source",
    "feature_name",
    "feature_value",
    "unit",
    "location",
    "confidence",
    "data_quality",
    "source_mode",
    "asset_id",
    "simulated",
}
ALLOWED_FIELDS = REQUIRED_FIELDS | {"metadata"}


class ObservationValidationError(ValueError):
    pass


def _is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _require_non_empty_string(observation, field_name):
    value = observation[field_name]
    if not isinstance(value, str) or not value.strip():
        raise ObservationValidationError(
            f"{field_name}必须是非空字符串"
        )


def _validate_timestamp(value):
    if not isinstance(value, str):
        raise ObservationValidationError(
            "timestamp必须是ISO 8601字符串"
        )

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ObservationValidationError(
            "timestamp不是有效的ISO 8601时间"
        ) from error

    if parsed.utcoffset() is None:
        raise ObservationValidationError("timestamp必须包含时区")


def _validate_nullable_string(observation, field_name):
    value = observation[field_name]
    if value is not None and (
        not isinstance(value, str) or not value.strip()
    ):
        raise ObservationValidationError(
            f"{field_name}必须是非空字符串或null"
        )


def validate_observation(observation):
    if not isinstance(observation, dict):
        raise ObservationValidationError("Observation必须是对象")

    missing_fields = sorted(REQUIRED_FIELDS - observation.keys())
    if missing_fields:
        raise ObservationValidationError(
            f"Observation缺少必填字段：{', '.join(missing_fields)}"
        )

    unexpected_fields = sorted(observation.keys() - ALLOWED_FIELDS)
    if unexpected_fields:
        raise ObservationValidationError(
            f"Observation包含未知字段：{', '.join(unexpected_fields)}"
        )

    if observation["schema_version"] != SCHEMA_VERSION:
        raise ObservationValidationError(
            f"schema_version必须是{SCHEMA_VERSION}"
        )

    for field_name in (
        "observation_id",
        "resident_id",
        "source",
        "feature_name",
    ):
        _require_non_empty_string(observation, field_name)

    _validate_timestamp(observation["timestamp"])

    feature_value = observation["feature_value"]
    if isinstance(feature_value, str):
        if not feature_value.strip():
            raise ObservationValidationError(
                "字符串类型的feature_value不能为空"
            )
    elif not isinstance(feature_value, bool) and not _is_number(feature_value):
        raise ObservationValidationError(
            "feature_value必须是数字、字符串或布尔值"
        )

    for field_name in ("unit", "location", "asset_id"):
        _validate_nullable_string(observation, field_name)

    for field_name in ("confidence", "data_quality"):
        value = observation[field_name]
        if not _is_number(value) or not 0 <= value <= 1:
            raise ObservationValidationError(
                f"{field_name}必须是0到1之间的有限数字"
            )

    if observation["source_mode"] not in SOURCE_MODES:
        raise ObservationValidationError(
            f"source_mode必须属于：{', '.join(sorted(SOURCE_MODES))}"
        )

    if not isinstance(observation["simulated"], bool):
        raise ObservationValidationError("simulated必须是布尔值")

    if "metadata" in observation and not isinstance(
        observation["metadata"], dict
    ):
        raise ObservationValidationError("metadata必须是对象")

    return observation


def validate_observation_collection(observation_items):
    if not isinstance(observation_items, list):
        raise ObservationValidationError("Observation集合必须是数组")

    observation_ids = []
    for observation in observation_items:
        validate_observation(observation)
        observation_ids.append(observation["observation_id"])

    duplicate_ids = sorted(
        observation_id
        for observation_id in set(observation_ids)
        if observation_ids.count(observation_id) > 1
    )
    if duplicate_ids:
        raise ObservationValidationError(
            f"observation_id重复：{', '.join(duplicate_ids)}"
        )

    return observation_items


def build_observation(
    *,
    observation_id,
    resident_id,
    timestamp,
    source,
    feature_name,
    feature_value,
    unit,
    location,
    confidence,
    data_quality,
    source_mode,
    asset_id,
    simulated,
    metadata=None,
):
    observation = {
        "schema_version": SCHEMA_VERSION,
        "observation_id": observation_id,
        "resident_id": resident_id,
        "timestamp": timestamp,
        "source": source,
        "feature_name": feature_name,
        "feature_value": feature_value,
        "unit": unit,
        "location": location,
        "confidence": confidence,
        "data_quality": data_quality,
        "source_mode": source_mode,
        "asset_id": asset_id,
        "simulated": simulated,
    }
    if metadata is not None:
        observation["metadata"] = metadata

    return validate_observation(observation)
