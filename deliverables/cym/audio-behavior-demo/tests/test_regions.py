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
        tracker = RegionTracker(
            self.regions,
            min_confirmation_updates=1,
            min_confirmation_seconds=0,
        )
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

    def test_boundary_jitter_does_not_create_transitions(self):
        tracker = RegionTracker(
            self.regions,
            min_confirmation_updates=3,
            min_confirmation_seconds=0.4,
        )
        tracker.update((20, 20), 0.0)
        tracker.update((20, 20), 0.2)
        tracker.update((20, 20), 0.5)
        self.assertEqual(tracker.current_region, "left")

        tracker.update((80, 20), 1.0)
        tracker.update((20, 20), 1.1)
        tracker.update((80, 20), 1.2)
        tracker.update((20, 20), 1.3)
        self.assertEqual(tracker.statistics()["transition_count"], 0)

        tracker.update((80, 20), 2.0)
        tracker.update((80, 20), 2.2)
        tracker.update((80, 20), 2.5)
        self.assertEqual(tracker.statistics()["transition_count"], 1)

    def test_region_change_requires_three_updates(self):
        tracker = RegionTracker(
            self.regions,
            min_confirmation_updates=3,
            min_confirmation_seconds=0,
        )
        tracker.update((20, 20), 0.0)
        tracker.update((20, 20), 0.1)
        tracker.update((20, 20), 0.2)
        self.assertEqual(tracker.current_region, "left")

        tracker.update((80, 20), 1.0)
        tracker.update((80, 20), 1.1)
        self.assertEqual(tracker.current_region, "left")
        tracker.update((80, 20), 1.2)
        self.assertEqual(tracker.current_region, "right")
        self.assertEqual(tracker.statistics()["transition_count"], 1)

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

    def test_normalized_config_maps_into_letterboxed_content(self):
        payload = {
            "scene_config_id": "scene-test-v1",
            "frame_size": [1280, 720],
            "regions": [{
                "id": "all",
                "polygon_norm": [[0, 0], [1, 0], [1, 1], [0, 1]],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "regions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            regions = load_region_config(
                path,
                (640, 480),
                expected_scene_config_id="scene-test-v1",
                content_rect=(0, 60, 640, 360),
            )
        self.assertEqual(regions[0]["polygon"], [(0, 60), (640, 60), (640, 420), (0, 420)])

    def test_scene_config_id_must_match_job(self):
        payload = {
            "scene_config_id": "scene-a",
            "frame_size": [640, 480],
            "regions": [{"id": "all", "polygon": [[0, 0], [640, 0], [640, 480]]}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "regions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "scene_config_id"):
                load_region_config(
                    path,
                    (640, 480),
                    expected_scene_config_id="scene-b",
                )


if __name__ == "__main__":
    unittest.main()
