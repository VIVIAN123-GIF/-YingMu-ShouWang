import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from regions import RegionTracker, find_region, load_region_config  # noqa: E402


class RegionTests(unittest.TestCase):
    def setUp(self):
        self.regions = [
            {"id": "left", "label": "Left", "polygon": [(0, 0), (50, 0), (50, 100), (0, 100)]},
            {"id": "right", "label": "Right", "polygon": [(51, 0), (100, 0), (100, 100), (51, 100)]},
        ]

    def test_point_in_polygon(self):
        self.assertEqual(find_region((20, 20), self.regions), "left")
        self.assertEqual(find_region((80, 20), self.regions), "right")
        self.assertIsNone(find_region((200, 20), self.regions))

    def test_enter_transition_exit_and_statistics(self):
        tracker = RegionTracker(self.regions)
        tracker.update((20, 20), 0.0)
        tracker.update((25, 20), 2.0)
        events = tracker.update((80, 20), 5.0)
        tracker.finalize(9.0)

        self.assertEqual([item["event_type"] for item in events], ["EXIT", "ENTER"])
        stats = tracker.statistics()
        self.assertEqual(stats["visited_region_count"], 2)
        self.assertEqual(stats["transition_count"], 1)
        self.assertEqual(stats["transitions"], {"left->right": 1})
        self.assertEqual(stats["dwell_seconds"], {"left": 5.0, "right": 4.0})
        self.assertEqual(stats["region_sequence"], ["left", "right"])

    def test_config_scales_to_analysis_frame(self):
        payload = {
            "frame_size": [320, 240],
            "regions": [{"id": "all", "polygon": [[0, 0], [320, 0], [320, 240], [0, 240]]}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "regions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            regions = load_region_config(path, (640, 480))
        self.assertEqual(regions[0]["polygon"][2], (640, 480))


if __name__ == "__main__":
    unittest.main()
