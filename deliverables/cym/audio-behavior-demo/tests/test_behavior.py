import sys
import unittest
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from behavior_demo import render_frame  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
