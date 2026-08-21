import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from behavior_adapter import build_behavior_bundle  # noqa: E402


class BehaviorAdapterTests(unittest.TestCase):
    def setUp(self):
        self.summary = {
            "source_mode": "RECORDED_REPLAY",
            "simulated": True,
            "frames_processed": 60,
            "detected_frames": 30,
            "max_person_count": 1,
            "max_motion_area": 8000,
            "activity_counts": {"LOW": 40, "MEDIUM": 20},
            "track_points": 30,
            "travel_distance_px": 120.5,
            "threshold_status": "DEMO_UNCALIBRATED",
        }

    def test_short_video_has_observations_but_no_long_term_evidence(self):
        bundle = build_behavior_bundle(self.summary, resident_id="resident-001")
        self.assertEqual(len(bundle["observations"]), 6)
        self.assertEqual(bundle["evidence"], [])

    def test_mismatched_trend_source_is_rejected(self):
        trend = json.loads(
            (ROOT / "samples" / "mock_daily_activity.json").read_text(encoding="utf-8")
        )
        with self.assertRaisesRegex(ValueError, "source_mode"):
            build_behavior_bundle(
                self.summary,
                resident_id="resident-001",
                trend_payload=trend,
            )

    def test_matching_stable_trend_can_be_appended(self):
        trend = json.loads(
            (ROOT / "samples" / "mock_daily_activity.json").read_text(encoding="utf-8")
        )
        trend["source_mode"] = "RECORDED_REPLAY"
        trend["simulated"] = True
        bundle = build_behavior_bundle(
            self.summary,
            resident_id="resident-001",
            trend_payload=trend,
        )
        self.assertGreater(len(bundle["evidence"]), 0)
        self.assertNotIn("risk_level", bundle)


if __name__ == "__main__":
    unittest.main()
