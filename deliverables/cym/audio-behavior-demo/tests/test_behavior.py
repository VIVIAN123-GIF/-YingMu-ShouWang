import sys
import unittest
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from behavior_demo import build_behavior_observations, render_frame  # noqa: E402
from observation import validate_observation_collection  # noqa: E402


class RenderFrameTests(unittest.TestCase):
    def test_render_frame_does_not_modify_analysis_frame(self):
        analysis_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        original = analysis_frame.copy()
        result = {
            "detections": [
                {
                    "box": (100, 80, 80, 180),
                    "confidence": 0.8,
                    "area": 14400,
                }
            ],
            "person_count": 1,
            "track_points": [(140, 170), (145, 175)],
            "travel_distance": 7.1,
            "recent_distance": 7.1,
            "behavior_label": "STILL",
            "motion_area": 0,
            "activity_level": "LOW",
        }

        display_frame = render_frame(analysis_frame, result)

        self.assertTrue(np.array_equal(analysis_frame, original))
        self.assertFalse(np.array_equal(display_frame, original))
        self.assertIsNot(display_frame, analysis_frame)


class BehaviorObservationTests(unittest.TestCase):
    def test_summary_builds_valid_observations(self):
        summary = {
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

        observations = build_behavior_observations(
            summary,
            resident_id="resident-001",
            location="living_room",
            asset_id="asset-test-0001",
        )

        self.assertEqual(len(observations), 6)
        self.assertIs(validate_observation_collection(observations), observations)
        self.assertEqual(
            {item["feature_name"] for item in observations},
            {
                "max_person_count",
                "person_detected_frame_ratio",
                "dominant_activity_level",
                "max_motion_area",
                "track_point_count",
                "travel_distance",
            },
        )


if __name__ == "__main__":
    unittest.main()
