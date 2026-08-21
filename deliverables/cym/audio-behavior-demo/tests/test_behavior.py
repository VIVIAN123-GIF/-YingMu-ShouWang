import sys
import unittest
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from behavior_demo import BehaviorAnalyzer, build_behavior_observations, render_frame  # noqa: E402
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

    def test_hog_part_box_is_not_counted_as_second_person(self):
        detections = [
            {
                "box": (346, 82, 166, 332),
                "area": 166 * 332,
                "confidence": 1.1,
                "source": "HOG",
            },
            {
                "box": (404, 222, 84, 167),
                "area": 84 * 167,
                "confidence": 0.48,
                "source": "HOG",
            },
        ]

        self.assertEqual(len(BehaviorAnalyzer._deduplicate_detections(detections)), 1)

    def test_overlapping_upper_and_lower_windows_are_one_person(self):
        detections = [
            {"box": (479, 56, 113, 227), "area": 113 * 227, "confidence": 0.465, "source": "HOG"},
            {"box": (472, 207, 92, 185), "area": 92 * 185, "confidence": 0.561, "source": "HOG"},
        ]

        self.assertEqual(len(BehaviorAnalyzer._deduplicate_detections(detections)), 1)


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

    def test_region_statistics_add_four_observations(self):
        summary = {
            "source_mode": "MOCK",
            "simulated": True,
            "frames_processed": 30,
            "detected_frames": 20,
            "max_person_count": 1,
            "max_motion_area": 1000,
            "activity_counts": {"LOW": 30},
            "track_points": 20,
            "travel_distance_px": 50.0,
            "threshold_status": "DEMO_UNCALIBRATED",
            "region_statistics": {
                "visited_region_count": 2,
                "transition_count": 1,
                "dwell_seconds": {"doorway": 2.0, "living_room": 8.0},
                "region_sequence": ["doorway", "living_room"],
            },
        }
        observations = build_behavior_observations(summary, resident_id="resident-001")
        self.assertEqual(len(observations), 10)
        self.assertIn("visited_region_count", {item["feature_name"] for item in observations})


if __name__ == "__main__":
    unittest.main()
