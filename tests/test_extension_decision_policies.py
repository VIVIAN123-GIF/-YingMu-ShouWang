from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from contracts.v1.decision import FraudDecisionPolicy, MentalDecisionPolicy
from contracts.v1.ruleset import load_ruleset


CN_TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 1, 19, 0, tzinfo=CN_TZ)


def item(evidence_id: str, evidence_type: str, *, quality: float = 0.92):
    return SimpleNamespace(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        risk_domain="MENTAL" if evidence_type in {
            "activity_range_decline", "room_transition_decline",
            "day_night_rhythm_change", "family_contact_completed", "trend_recovered",
        } else "FRAUD",
        timestamp=NOW,
        severity=0.76,
        confidence=0.93,
        data_quality=quality,
    )


def evaluate(policy, recent, trigger, *, state="GREEN", status=None):
    return policy.evaluate(
        now=NOW,
        previous_state=state,
        active_status=status,
        active_created_at=NOW - timedelta(minutes=1) if status else None,
        recovery_started_at=None,
        recent=recent,
        trigger=trigger,
    )


def test_mental_policy_opens_observes_and_resolves_without_diagnosis():
    policy = MentalDecisionPolicy(load_ruleset())
    decline = item("evi-decline", "activity_range_decline")
    opened = evaluate(policy, [decline], decline)
    assert (opened.matched_rule, opened.risk_level, opened.next_status) == (
        "R-MENTAL-01", "YELLOW", "OPEN"
    )
    contact = item("evi-contact", "family_contact_completed")
    observing = evaluate(policy, [decline, contact], contact, state="YELLOW", status="OPEN")
    assert (observing.matched_rule, observing.next_status) == ("R-MENTAL-02", "OBSERVING")
    recovered = item("evi-recovered", "trend_recovered")
    resolved = evaluate(
        policy, [decline, contact, recovered], recovered,
        state="YELLOW", status="OBSERVING",
    )
    assert (resolved.matched_rule, resolved.risk_level, resolved.next_status) == (
        "R-MENTAL-03", "GREEN", "RESOLVED"
    )
    assert "diagnos" not in " ".join((opened.reason, observing.reason, resolved.reason)).lower()


def test_low_quality_mental_evidence_never_opens_an_event():
    policy = MentalDecisionPolicy(load_ruleset())
    decline = item("evi-low-quality", "activity_range_decline", quality=0.4)
    decision = evaluate(policy, [decline], decline)
    assert decision.matched_rule == "R-MENTAL-00"
    assert decision.action == "NONE"
    assert decision.risk_level == "GREEN"


def test_fraud_policy_keeps_difficult_negatives_below_orange():
    policy = FraudDecisionPolicy(load_ruleset())
    unauthorized = item("evi-visitor", "unauthorized_visitor")
    dwell = item("evi-dwell", "unusual_dwell_time")
    keyword = item("evi-keyword", "fraud_keyword")

    single = evaluate(policy, [keyword], keyword)
    assert (single.matched_rule, single.risk_level, single.next_status) == (
        "R-FRAUD-01", "YELLOW", "OPEN"
    )
    double = evaluate(
        policy, [unauthorized, dwell], dwell, state="YELLOW", status="OPEN"
    )
    assert (double.matched_rule, double.risk_level) == ("R-FRAUD-01", "YELLOW")
    triple = evaluate(
        policy, [unauthorized, dwell, keyword], keyword,
        state="YELLOW", status="OPEN",
    )
    assert (triple.matched_rule, triple.risk_level, triple.next_status) == (
        "R-FRAUD-02", "ORANGE", "INTERVENING"
    )
    assert triple.risk_level != "RED"


def test_fraud_verification_closes_without_confirming_fraud():
    policy = FraudDecisionPolicy(load_ruleset())
    verified = item("evi-verified", "identity_verified")
    resolved = evaluate(policy, [verified], verified, state="YELLOW", status="OPEN")
    false_alarm = item("evi-false-alarm", "false_alarm_confirmed")
    closed = evaluate(policy, [false_alarm], false_alarm, state="YELLOW", status="OPEN")
    assert (resolved.risk_level, resolved.next_status) == ("GREEN", "RESOLVED")
    assert (closed.risk_level, closed.next_status) == ("GREEN", "FALSE_ALARM")
    assert "confirmed fraud" not in (resolved.reason + closed.reason).lower()
