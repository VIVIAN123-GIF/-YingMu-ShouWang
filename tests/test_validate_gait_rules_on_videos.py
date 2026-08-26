from scripts.validate_gait_rules_on_videos import _matches_expected, _sanitized_diagnostics


def test_expected_rule_result_matching():
    assert _matches_expected("ORANGE", "ORANGE")
    assert _matches_expected("GREEN", "GREEN")
    assert _matches_expected("NO_ORANGE", "GREEN")
    assert _matches_expected("NO_ORANGE", "YELLOW")
    assert _matches_expected("YELLOW", "YELLOW")
    assert _matches_expected("UNKNOWN", "UNKNOWN")
    assert not _matches_expected("NO_ORANGE", "ORANGE")


def test_report_diagnostics_are_allowlisted_and_omit_private_fields():
    diagnostics = _sanitized_diagnostics(
        {
            "rise_window_start_s": 1.2,
            "trunk_sway_p5_deg": None,
            "media_path": "private-video.mp4",
            "device_identifier": "private-device",
            "raw_landmarks": [[0.1, 0.2]],
        }
    )

    assert diagnostics == {"rise_window_start_s": 1.2}
