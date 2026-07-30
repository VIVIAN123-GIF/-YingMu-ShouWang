import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from behavior_evidence import build_behavior_evidence_bundle  # noqa: E402
from evidence import validate_evidence_collection  # noqa: E402
from observation import validate_observation_collection  # noqa: E402


class BehaviorEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.settings = json.loads(
            (ROOT / "samples" / "mock_behavior_statistics.json").read_text(encoding="utf-8")
        )

    def test_bundle_has_traceable_valid_items(self):
        bundle = build_behavior_evidence_bundle(self.settings)
        observations = validate_observation_collection(bundle["observations"])
        evidence = validate_evidence_collection(bundle["evidence"])
        observation_ids = {item["observation_id"] for item in observations}

        self.assertEqual(len(observations), 6)
        self.assertEqual(
            {item["evidence_type"] for item in evidence},
            {"activity_range_decline", "unauthorized_visitor", "unusual_dwell_time"},
        )
        self.assertTrue(all(item["simulated"] for item in observations + evidence))
        self.assertTrue(all(item["source_mode"] == "MOCK" for item in observations + evidence))
        for item in evidence:
            self.assertTrue(set(item["observation_ids"]).issubset(observation_ids))

    def test_invalid_dwell_threshold_is_rejected(self):
        invalid = copy.deepcopy(self.settings)
        invalid["mock_dwell_threshold_seconds"] = 0
        with self.assertRaisesRegex(ValueError, "必须大于0"):
            build_behavior_evidence_bundle(invalid)

    def test_non_declining_activity_does_not_create_decline_evidence(self):
        invalid = copy.deepcopy(self.settings)
        invalid["current_region_count"] = invalid["baseline_region_count"]
        with self.assertRaisesRegex(ValueError, "当前区域数低于"):
            build_behavior_evidence_bundle(invalid)


if __name__ == "__main__":
    unittest.main()
