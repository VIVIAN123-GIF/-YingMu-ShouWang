import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from evidence import validate_evidence_collection  # noqa: E402
from observation import validate_observation_collection  # noqa: E402
from trend_analysis import TrendInputError, build_trend_bundle  # noqa: E402


class TrendAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(
            (ROOT / "samples" / "mock_daily_activity.json").read_text(encoding="utf-8")
        )

    def test_stable_history_generates_three_trend_evidence_items(self):
        bundle = build_trend_bundle(self.payload)
        self.assertEqual(bundle["baseline_status"], "STABLE")
        self.assertEqual(len(validate_observation_collection(bundle["observations"])), 6)
        evidence = validate_evidence_collection(bundle["evidence"])
        self.assertEqual(
            {item["evidence_type"] for item in evidence},
            {"activity_range_decline", "room_transition_decline", "day_night_rhythm_change"},
        )
        observation_ids = {item["observation_id"] for item in bundle["observations"]}
        self.assertTrue(all(set(item["observation_ids"]) <= observation_ids for item in evidence))
        self.assertTrue(all(item["source_mode"] == "MOCK" for item in evidence))

    def test_provisional_history_keeps_observations_but_does_not_emit_evidence(self):
        provisional = copy.deepcopy(self.payload)
        provisional["days"] = provisional["days"][:4]
        bundle = build_trend_bundle(provisional)
        self.assertEqual(bundle["baseline_status"], "PROVISIONAL")
        self.assertEqual(len(bundle["observations"]), 6)
        self.assertEqual(bundle["evidence"], [])

    def test_duplicate_dates_are_rejected(self):
        invalid = copy.deepcopy(self.payload)
        invalid["days"][1]["date"] = invalid["days"][0]["date"]
        with self.assertRaisesRegex(TrendInputError, "重复日期"):
            build_trend_bundle(invalid)


if __name__ == "__main__":
    unittest.main()
