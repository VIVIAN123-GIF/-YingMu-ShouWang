import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PROJECT_ROOT = ROOT.parents[2]
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(PROJECT_ROOT))

from contracts.v1.models import Observation as CanonicalObservation  # noqa: E402
from observation import (  # noqa: E402
    ObservationValidationError,
    build_observation,
    validate_observation,
    validate_observation_collection,
)


def make_observation():
    return build_observation(
        observation_id="obs-contract-test-0001",
        resident_id="resident-001",
        timestamp="2026-07-26T18:30:00+08:00",
        source="tracking",
        feature_name="max_person_count",
        feature_value=1,
        unit="count",
        location="living_room",
        confidence=0.50,
        data_quality=0.60,
        source_mode="RECORDED_REPLAY",
        asset_id="asset-test-0001",
        simulated=True,
        metadata={"adapter_version": "behavior-adapter-v1"},
    )


class ObservationValidationTests(unittest.TestCase):
    def test_valid_observation_passes_local_and_canonical_contracts(self):
        observation = make_observation()

        self.assertIs(validate_observation(observation), observation)
        canonical = CanonicalObservation.model_validate(observation)
        self.assertEqual(canonical.observation_id, observation["observation_id"])

    def test_missing_required_field_is_rejected(self):
        observation = make_observation()
        del observation["resident_id"]

        with self.assertRaises(ObservationValidationError):
            validate_observation(observation)

    def test_unknown_field_is_rejected(self):
        observation = make_observation()
        observation["risk_level"] = "RED"

        with self.assertRaises(ObservationValidationError):
            validate_observation(observation)

    def test_timestamp_without_timezone_is_rejected(self):
        observation = make_observation()
        observation["timestamp"] = "2026-07-26T18:30:00"

        with self.assertRaises(ObservationValidationError):
            validate_observation(observation)

    def test_duplicate_observation_id_is_rejected(self):
        observation = make_observation()

        with self.assertRaises(ObservationValidationError):
            validate_observation_collection(
                [observation, copy.deepcopy(observation)]
            )


if __name__ == "__main__":
    unittest.main()
