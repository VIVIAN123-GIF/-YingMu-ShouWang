from scripts.calibrate_gait_sway import SampleResult, evaluate_calibration


def sample(label: str, amplitude: float, index: int = 1) -> SampleResult:
    return SampleResult(
        sample_ref=f"sample-{index:02d}",
        label=label,
        result="VALID",
        amplitude_deg=amplitude,
        rise_duration_s=1.0 if label == "POSITIVE" else None,
        window_type="POST_RISE" if label == "POSITIVE" else "FULL_CLIP_FALLBACK",
        failure_reason=None,
    )


def test_calibration_recommends_midpoint_only_when_samples_separate():
    report = evaluate_calibration(
        [sample("POSITIVE", 18.0), sample("NEGATIVE", 6.0), sample("NEGATIVE", 8.0, 2)],
        current_threshold=12.0,
    )

    assert report["status"] == "CALIBRATION_SEPARABLE"
    assert report["recommended_threshold_deg"] == 13.0


def test_calibration_keeps_threshold_when_samples_overlap():
    report = evaluate_calibration(
        [sample("POSITIVE", 7.0), sample("NEGATIVE", 8.0)],
        current_threshold=12.0,
    )

    assert report["status"] == "CALIBRATION_INCONCLUSIVE"
    assert report["recommended_threshold_deg"] == 12.0
    assert report["threshold_changed"] is False
