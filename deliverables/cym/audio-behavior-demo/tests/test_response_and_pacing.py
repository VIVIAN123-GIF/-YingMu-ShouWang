import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from audio_evidence import build_audio_batch  # noqa: E402
from behavior_adapter import build_behavior_batch  # noqa: E402
from pacing import analyze_pacing  # noqa: E402


JOB = {
    "job_id": "job-response-pacing-001",
    "asset_id": "asset-response-pacing-001",
    "media_locator": "authorized-local-input",
    "captured_at": "2026-08-15T10:00:00+08:00",
    "source_mode": "RECORDED_REPLAY",
    "simulated": True,
}


class ResidentResponseTests(unittest.TestCase):
    def build(self, transcript, quality=0.90):
        return build_audio_batch(
            JOB,
            transcript,
            resident_id="resident-001",
            quality_metrics={"data_quality": quality},
            started_at="2026-08-15T10:00:01+08:00",
            completed_at="2026-08-15T10:00:02+08:00",
        )

    @staticmethod
    def values(batch):
        return {
            item["feature_name"]: item["feature_value"]
            for item in batch["observations"]
        }

    def test_stable_response_is_classified_without_raw_text(self):
        transcript = "我没事，我已经坐稳了"
        batch = self.build(transcript)
        self.assertEqual(self.values(batch)["resident_response_intent"], "stable")
        self.assertNotIn(transcript, json.dumps(batch, ensure_ascii=False))

    def test_help_request_is_classified(self):
        batch = self.build("我需要帮助，请帮我联系家人")
        self.assertEqual(
            self.values(batch)["resident_response_intent"],
            "help_requested",
        )

    def test_conflicting_response_is_uncertain(self):
        batch = self.build("我没事，但是我还是需要帮助")
        self.assertEqual(self.values(batch)["resident_response_intent"], "uncertain")

    def test_empty_and_low_quality_are_distinguished(self):
        no_response = self.build("")
        unavailable = self.build("我没事", quality=0.20)
        self.assertEqual(self.values(no_response)["resident_response_intent"], "no_response")
        self.assertEqual(self.values(unavailable)["resident_response_intent"], "unavailable")
        self.assertIn(
            "audio_quality_low",
            {item["evidence_type"] for item in unavailable["evidences"]},
        )


class UnusualPacingTests(unittest.TestCase):
    @staticmethod
    def summary(sequence, detected_frames=90):
        return {
            "source_mode": "RECORDED_REPLAY",
            "simulated": True,
            "frames_processed": 100,
            "detected_frames": detected_frames,
            "max_person_count": 1,
            "max_motion_area": 5000,
            "activity_counts": {"LOW": 20, "MEDIUM": 80},
            "track_points": 80,
            "travel_distance_px": 800.0,
            "threshold_status": "DEMO_UNCALIBRATED",
            "region_statistics": {
                "visited_region_count": len(set(sequence)),
                "dwell_seconds": {item: 10.0 for item in set(sequence)},
                "transition_count": max(0, len(sequence) - 1),
                "region_sequence": sequence,
            },
        }

    def build(self, summary):
        return build_behavior_batch(
            JOB,
            summary,
            resident_id="resident-001",
            started_at="2026-08-15T10:00:01+08:00",
            completed_at="2026-08-15T10:00:02+08:00",
        )

    def test_repeated_region_alternation_emits_unusual_pacing(self):
        batch = self.build(self.summary(["room_a", "room_b", "room_a", "room_b", "room_a"]))
        evidence_types = {item["evidence_type"] for item in batch["evidences"]}
        self.assertIn("unusual_pacing", evidence_types)
        values = {
            item["feature_name"]: item["feature_value"]
            for item in batch["observations"]
        }
        self.assertEqual(values["alternating_region_transition_count"], 3)
        self.assertEqual(values["region_revisit_count"], 3)

    def test_normal_route_does_not_emit_unusual_pacing(self):
        batch = self.build(self.summary(["room_a", "room_b", "room_c"]))
        self.assertNotIn(
            "unusual_pacing",
            {item["evidence_type"] for item in batch["evidences"]},
        )

    def test_low_tracking_quality_suppresses_pacing_and_reports_loss(self):
        batch = self.build(
            self.summary(
                ["room_a", "room_b", "room_a", "room_b", "room_a"],
                detected_frames=20,
            )
        )
        evidence_types = {item["evidence_type"] for item in batch["evidences"]}
        self.assertNotIn("unusual_pacing", evidence_types)
        self.assertIn("tracking_lost", evidence_types)

    def test_pacing_metrics_are_deterministic(self):
        first = analyze_pacing({"region_sequence": ["a", "b", "a", "b", "a"]})
        second = analyze_pacing({"region_sequence": ["a", "b", "a", "b", "a"]})
        self.assertEqual(first, second)
        self.assertTrue(first["triggered"])


if __name__ == "__main__":
    unittest.main()
