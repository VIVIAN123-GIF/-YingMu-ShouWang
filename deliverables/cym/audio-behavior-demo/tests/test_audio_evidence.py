import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from audio_evidence import build_audio_bundle  # noqa: E402
from evidence import validate_evidence_collection  # noqa: E402
from observation import validate_observation_collection  # noqa: E402


class AudioEvidenceTests(unittest.TestCase):
    def test_multiple_phrases_create_linked_fraud_evidence(self):
        bundle = build_audio_bundle(
            "保证收益，请把验证码告诉我并马上转账",
            resident_id="resident-001",
            source_mode="RECORDED_REPLAY",
            simulated=True,
            run_id="test-001",
        )
        observations = validate_observation_collection(bundle["observations"])
        evidence = validate_evidence_collection(bundle["evidence"])
        self.assertEqual(len(observations), 4)
        self.assertEqual({item["evidence_type"] for item in evidence}, {"fraud_keyword"})
        self.assertTrue(set(evidence[0]["observation_ids"]).issubset({item["observation_id"] for item in observations}))

    def test_single_keyword_is_capped_and_low_quality_is_explicit(self):
        bundle = build_audio_bundle(
            "请告诉我验证码",
            resident_id="resident-001",
            quality_metrics={"data_quality": 0.30},
            run_id="test-002",
        )
        evidence = {item["evidence_type"]: item for item in bundle["evidence"]}
        self.assertIn("audio_quality_low", evidence)
        self.assertIn("fraud_keyword", evidence)
        self.assertLessEqual(evidence["fraud_keyword"]["severity"], 0.43)
        self.assertIn("不能独立判断诈骗", evidence["fraud_keyword"]["explanation"])

    def test_empty_transcript_remains_valid_and_is_not_classified(self):
        bundle = build_audio_bundle(
            "",
            resident_id="resident-001",
            quality_metrics={"data_quality": 0.20},
            run_id="test-003",
        )
        self.assertEqual(bundle["evidence"][0]["evidence_type"], "audio_quality_low")
        self.assertEqual(bundle["observations"][0]["feature_value"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
