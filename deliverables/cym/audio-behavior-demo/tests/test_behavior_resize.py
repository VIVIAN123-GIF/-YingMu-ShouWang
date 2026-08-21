import sys
import unittest
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from behavior_demo import analysis_content_rect, resize_for_analysis  # noqa: E402


class ResizeForAnalysisTests(unittest.TestCase):
    def test_wide_frame_is_padded_without_distortion(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[100:300, 400:600] = (255, 255, 255)
        result = resize_for_analysis(frame)

        self.assertEqual(result.shape, (480, 640, 3))
        # 16:9 content becomes 640x360 with 60px top/bottom padding.
        self.assertTrue(np.array_equal(result[:60], np.zeros((60, 640, 3), dtype=np.uint8)))
        self.assertGreater(int(result[110:210, 200:300].sum()), 0)

    def test_native_aspect_frame_has_no_padding(self):
        frame = np.full((480, 640, 3), 127, dtype=np.uint8)
        result = resize_for_analysis(frame)
        self.assertTrue(np.array_equal(result, frame))

    def test_content_rect_reports_letterbox_offsets(self):
        self.assertEqual(analysis_content_rect((1280, 720)), (0, 60, 640, 360))


if __name__ == "__main__":
    unittest.main()
