"""Interpretable region-alternation features for the pacing demo rule."""


# Sensitive demo thresholds favor recall for staged real-video validation.
# They remain uncalibrated and must not be presented as production accuracy.
TRACKING_QUALITY_THRESHOLD = 0.35
MIN_TRANSITIONS = 3
MIN_ALTERNATING_PATTERNS = 2
MIN_SEQUENCE_LENGTH = 4


def analyze_pacing(region_statistics):
    """Measure repeated A-B-A region alternation without diagnosing illness."""
    if not isinstance(region_statistics, dict):
        return {
            "sequence_length": 0,
            "transition_count": 0,
            "revisit_count": 0,
            "alternating_transition_count": 0,
            "pacing_pattern_score": 0.0,
            "triggered": False,
        }
    sequence = region_statistics.get("region_sequence") or []
    if not isinstance(sequence, list):
        raise ValueError("region_sequence must be a list")
    cleaned = []
    for item in sequence:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("region_sequence items must be non-empty strings")
        if not cleaned or cleaned[-1] != item:
            cleaned.append(item)
    transition_count = max(0, len(cleaned) - 1)
    revisit_count = max(0, len(cleaned) - len(set(cleaned)))
    alternating_count = sum(
        1
        for index in range(2, len(cleaned))
        if cleaned[index] == cleaned[index - 2]
        and cleaned[index] != cleaned[index - 1]
    )
    score = min(
        1.0,
        0.70 * alternating_count / MIN_ALTERNATING_PATTERNS
        + 0.30 * revisit_count / MIN_ALTERNATING_PATTERNS,
    )
    triggered = (
        len(cleaned) >= MIN_SEQUENCE_LENGTH
        and transition_count >= MIN_TRANSITIONS
        and alternating_count >= MIN_ALTERNATING_PATTERNS
    )
    return {
        "sequence_length": len(cleaned),
        "transition_count": transition_count,
        "revisit_count": revisit_count,
        "alternating_transition_count": alternating_count,
        "pacing_pattern_score": round(score, 4),
        "triggered": triggered,
    }
