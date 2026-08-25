"""Deterministic MENTAL and FRAUD scenario catalog with explicit mock provenance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


GENERATOR_VERSION = "extension-scenarios-v1.0"
SCENARIO_KIND = "STRUCTURED_SYNTHETIC"
SOURCE_MODE = "MOCK"
CN_TZ = timezone(timedelta(hours=8))
BASE_TIME = datetime(2026, 8, 1, 19, 0, tzinfo=CN_TZ)


def _step(evidence_type: str | None, minute: int, *, quality: float = 0.92) -> dict[str, Any]:
    return {
        "minute": minute,
        "evidence_type": evidence_type,
        "confidence": 0.93,
        "data_quality": quality,
    }


def _scenario(
    scenario_id: str,
    domain: str,
    category: str,
    title: str,
    steps: list[dict[str, Any]],
    *,
    expected_peak: str,
    expected_status: str | None,
    closure_required: bool = False,
) -> dict[str, Any]:
    evidence_types = [
        step["evidence_type"] for step in steps if step["evidence_type"] is not None
    ]
    return {
        "scenario_id": scenario_id,
        "resident_id": f"resident-{scenario_id.lower()}",
        "risk_domain": domain,
        "category": category,
        "title": title,
        "source_mode": SOURCE_MODE,
        "simulated": True,
        "scenario_kind": SCENARIO_KIND,
        "generator_version": GENERATOR_VERSION,
        "steps": steps,
        "expected": {
            "evidence_types": evidence_types,
            "event_created": bool(evidence_types),
            "peak_risk_level": expected_peak,
            "final_status": expected_status,
            "closure_required": closure_required,
        },
    }


def _mental_trend_days(category: str, variant: int) -> list[dict[str, Any]]:
    days = []
    for day in range(12):
        activity_range = 5.0 + ((day + variant) % 3 - 1) * 0.12
        room_transitions = 12 + ((day + variant) % 3 - 1)
        daytime_activity_ratio = 0.78 + ((day + variant) % 3 - 1) * 0.015
        if category == "activity_decline" and day >= 7:
            decline = 0.45 * (day - 6)
            if variant != 1:
                activity_range = max(2.4, activity_range - decline)
            if variant != 0:
                room_transitions = max(5, room_transitions - (day - 6))
        elif category == "rhythm_shift" and day >= 8:
            daytime_activity_ratio = max(0.38, daytime_activity_ratio - 0.09 * (day - 7))
        elif category == "trend_recovery":
            if 7 <= day <= 9:
                activity_range -= 1.4
                room_transitions -= 4
                daytime_activity_ratio -= 0.20
            elif day >= 10:
                activity_range = 4.9 + 0.08 * (day - 10)
                room_transitions = 11 + (day - 10)
                daytime_activity_ratio = 0.74 + 0.02 * (day - 10)
        days.append({
            "date": (BASE_TIME.date() + timedelta(days=day)).isoformat(),
            "activity_range": round(activity_range, 3),
            "room_transitions": room_transitions,
            "daytime_activity_ratio": round(daytime_activity_ratio, 3),
            "data_quality": 0.92,
        })
    return days


def _fraud_script(category: str, variant: int) -> dict[str, Any]:
    authorized = category in {"authorized_normal", "authorized_risk_words"}
    long_dwell = category in {
        "unknown_long_no_words", "risk_combination",
    } or (category == "identity_recovery" and variant == 1)
    has_risk_words = category in {"authorized_risk_words", "risk_combination"}
    return {
        "visitor_authorized": authorized,
        "dwell_minutes": 22 + variant * 4 if long_dwell else 3 + variant,
        "conversation_tags": (
            ["transfer_request", "account_security"] if has_risk_words else ["routine_visit"]
        ),
        "raw_transcript_stored": False,
        "media_present": False,
    }


def scenario_catalog() -> list[dict[str, Any]]:
    mental = [
        _scenario("MENTAL-NORMAL-01", "MENTAL", "normal_baseline", "Stable daily activity", [_step(None, 0)], expected_peak="GREEN", expected_status=None),
        _scenario("MENTAL-NORMAL-02", "MENTAL", "normal_baseline", "Stable room transitions", [_step(None, 0)], expected_peak="GREEN", expected_status=None),
        _scenario("MENTAL-NORMAL-03", "MENTAL", "normal_baseline", "Stable day/night rhythm", [_step(None, 0)], expected_peak="GREEN", expected_status=None),
        _scenario("MENTAL-DECLINE-01", "MENTAL", "activity_decline", "Activity range decline", [_step("activity_range_decline", 0)], expected_peak="YELLOW", expected_status="OPEN"),
        _scenario("MENTAL-DECLINE-02", "MENTAL", "activity_decline", "Room transition decline", [_step("room_transition_decline", 0)], expected_peak="YELLOW", expected_status="OPEN"),
        _scenario("MENTAL-DECLINE-03", "MENTAL", "activity_decline", "Combined activity and room decline", [_step("activity_range_decline", 0), _step("room_transition_decline", 10)], expected_peak="YELLOW", expected_status="OPEN"),
        _scenario("MENTAL-RHYTHM-01", "MENTAL", "rhythm_shift", "Later daytime activity shift", [_step("day_night_rhythm_change", 0)], expected_peak="YELLOW", expected_status="OPEN"),
        _scenario("MENTAL-RHYTHM-02", "MENTAL", "rhythm_shift", "Night activity increase", [_step("day_night_rhythm_change", 0)], expected_peak="YELLOW", expected_status="OPEN"),
        _scenario("MENTAL-RHYTHM-03", "MENTAL", "rhythm_shift", "Irregular day/night ratio", [_step("day_night_rhythm_change", 0)], expected_peak="YELLOW", expected_status="OPEN"),
        _scenario("MENTAL-RECOVERY-01", "MENTAL", "trend_recovery", "Activity decline followed by recovery", [_step("activity_range_decline", 0), _step("family_contact_completed", 10), _step("trend_recovered", 20)], expected_peak="YELLOW", expected_status="RESOLVED", closure_required=True),
        _scenario("MENTAL-RECOVERY-02", "MENTAL", "trend_recovery", "Room transition decline followed by recovery", [_step("room_transition_decline", 0), _step("family_contact_completed", 10), _step("trend_recovered", 20)], expected_peak="YELLOW", expected_status="RESOLVED", closure_required=True),
        _scenario("MENTAL-RECOVERY-03", "MENTAL", "trend_recovery", "Rhythm shift followed by recovery", [_step("day_night_rhythm_change", 0), _step("family_contact_completed", 10), _step("trend_recovered", 20)], expected_peak="YELLOW", expected_status="RESOLVED", closure_required=True),
    ]
    fraud = [
        _scenario("FRAUD-AUTH-NORMAL-01", "FRAUD", "authorized_normal", "Authorized visitor and routine conversation", [_step(None, 0)], expected_peak="GREEN", expected_status=None),
        _scenario("FRAUD-AUTH-NORMAL-02", "FRAUD", "authorized_normal", "Authorized visitor and delivery conversation", [_step(None, 0)], expected_peak="GREEN", expected_status=None),
        _scenario("FRAUD-UNKNOWN-BRIEF-01", "FRAUD", "unknown_brief", "Unknown brief visitor", [_step("unauthorized_visitor", 0)], expected_peak="YELLOW", expected_status="OPEN"),
        _scenario("FRAUD-UNKNOWN-BRIEF-02", "FRAUD", "unknown_brief", "Unknown brief service visitor", [_step("unauthorized_visitor", 0)], expected_peak="YELLOW", expected_status="OPEN"),
        _scenario("FRAUD-AUTH-WORD-01", "FRAUD", "authorized_risk_words", "Authorized visitor with isolated risk word", [_step("fraud_keyword", 0)], expected_peak="YELLOW", expected_status="OPEN"),
        _scenario("FRAUD-AUTH-WORD-02", "FRAUD", "authorized_risk_words", "Family conversation with isolated transfer word", [_step("fraud_keyword", 0)], expected_peak="YELLOW", expected_status="OPEN"),
        _scenario("FRAUD-UNKNOWN-LONG-01", "FRAUD", "unknown_long_no_words", "Unknown visitor with long dwell and no risk words", [_step("unauthorized_visitor", 0), _step("unusual_dwell_time", 5)], expected_peak="YELLOW", expected_status="OPEN"),
        _scenario("FRAUD-UNKNOWN-LONG-02", "FRAUD", "unknown_long_no_words", "Unknown maintenance visitor with long dwell", [_step("unauthorized_visitor", 0), _step("unusual_dwell_time", 5)], expected_peak="YELLOW", expected_status="OPEN"),
        _scenario("FRAUD-COMBINATION-01", "FRAUD", "risk_combination", "Unknown long-stay visitor with transfer words", [_step("unauthorized_visitor", 0), _step("unusual_dwell_time", 5), _step("fraud_keyword", 10)], expected_peak="ORANGE", expected_status="INTERVENING"),
        _scenario("FRAUD-COMBINATION-02", "FRAUD", "risk_combination", "Unknown long-stay visitor with account words", [_step("fraud_keyword", 0), _step("unauthorized_visitor", 5), _step("unusual_dwell_time", 10)], expected_peak="ORANGE", expected_status="INTERVENING"),
        _scenario("FRAUD-VERIFY-01", "FRAUD", "identity_recovery", "Unknown visitor identity verified", [_step("unauthorized_visitor", 0), _step("identity_verified", 5)], expected_peak="YELLOW", expected_status="RESOLVED", closure_required=True),
        _scenario("FRAUD-VERIFY-02", "FRAUD", "identity_recovery", "Long-stay visitor confirmed as false alarm", [_step("unauthorized_visitor", 0), _step("unusual_dwell_time", 5), _step("false_alarm_confirmed", 10)], expected_peak="YELLOW", expected_status="FALSE_ALARM", closure_required=True),
    ]
    for index, scenario in enumerate(mental):
        scenario["input_kind"] = "MULTI_DAY_TREND"
        scenario["structured_input"] = {
            "trend_days": _mental_trend_days(scenario["category"], index % 3)
        }
    for index, scenario in enumerate(fraud):
        scenario["input_kind"] = "VISITOR_CONVERSATION_SCRIPT"
        scenario["structured_input"] = _fraud_script(scenario["category"], index % 2)
    return mental + fraud


def build_payloads(scenario: dict[str, Any], index: int) -> list[dict[str, Any]]:
    """Build strict API payload pairs without media or personal data."""
    start = BASE_TIME + timedelta(days=index)
    payloads = []
    for step_index, step in enumerate(scenario["steps"], start=1):
        timestamp = start + timedelta(minutes=step["minute"])
        suffix = f"{scenario['scenario_id'].lower()}-{step_index:02d}"
        evidence_type = step["evidence_type"]
        feature_name = evidence_type or "normal_scenario_marker"
        observation = {
            "schema_version": "1.0",
            "observation_id": f"obs-{suffix}",
            "resident_id": scenario["resident_id"],
            "timestamp": timestamp,
            "source": "structured_scenario_generator",
            "feature_name": feature_name,
            "feature_value": 0.0 if evidence_type is None else 1.0,
            "unit": "scenario_flag",
            "location": "synthetic_living_room",
            "confidence": step["confidence"],
            "data_quality": step["data_quality"],
            "source_mode": SOURCE_MODE,
            "asset_id": None,
            "simulated": True,
            "metadata": {
                "scenario_id": scenario["scenario_id"],
                "scenario_kind": SCENARIO_KIND,
                "generator_version": GENERATOR_VERSION,
                "contains_real_person_data": False,
                "contains_media": False,
                "input_kind": scenario["input_kind"],
                "structured_input": scenario["structured_input"],
            },
        }
        evidence = None
        if evidence_type is not None:
            is_closure = evidence_type in {
                "family_contact_completed",
                "trend_recovered",
                "identity_verified",
                "false_alarm_confirmed",
            }
            evidence = {
                "schema_version": "1.0",
                "evidence_id": f"evi-{suffix}",
                "observation_ids": [observation["observation_id"]],
                "resident_id": scenario["resident_id"],
                "timestamp": timestamp,
                "risk_domain": scenario["risk_domain"],
                "evidence_type": evidence_type,
                "severity": 0.0 if is_closure else 0.76,
                "confidence": step["confidence"],
                "data_quality": step["data_quality"],
                "baseline_value": 1.0,
                "current_value": 1.0,
                "baseline_deviation": 0.0 if is_closure else 1.0,
                "time_scale": "LONG" if scenario["risk_domain"] == "MENTAL" else "SHORT",
                "location": "synthetic_living_room",
                "explanation": (
                    "Structured synthetic engineering marker; not a clinical diagnosis "
                    "or confirmation of fraud."
                ),
                "adapter_version": GENERATOR_VERSION,
                "source_mode": SOURCE_MODE,
                "simulated": True,
            }
        payloads.append({"observation": observation, "evidence": evidence})
    return payloads
