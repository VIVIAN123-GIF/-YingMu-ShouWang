from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime

from contracts.v1.engine import ConflictError, ContractError, MockRiskEngine, validate_contract
from contracts.v1.mock_data import RESIDENT_ID, sequence
from contracts.v1.models import Evidence, InterventionResult, Observation, RiskEvent
from contracts.v1.rehearsal import run_fixed_sequence


class ContractModelTests(unittest.TestCase):
    def setUp(self):
        self.data = sequence()

    def test_four_valid_objects_parse(self):
        engine, _ = run_fixed_sequence()
        snapshot = engine.snapshot()
        Observation.model_validate(self.data["observations"][0])
        Evidence.model_validate(self.data["evidence"][0])
        RiskEvent.model_validate(snapshot["events"][0])
        InterventionResult.model_validate(snapshot["interventions"][0])

    def test_missing_required_field_is_422(self):
        payload = deepcopy(self.data["observations"][0])
        del payload["resident_id"]
        with self.assertRaises(ContractError) as caught:
            MockRiskEngine().ingest_observation(payload)
        self.assertEqual(caught.exception.status_code, 422)

    def test_unknown_field_is_422(self):
        payload = deepcopy(self.data["observations"][0])
        payload["risk_level"] = "ORANGE"
        with self.assertRaises(ContractError) as caught:
            MockRiskEngine().ingest_observation(payload)
        self.assertEqual(caught.exception.status_code, 422)

    def test_score_out_of_range_is_422(self):
        payload = deepcopy(self.data["evidence"][0])
        payload["confidence"] = 1.1
        engine = MockRiskEngine()
        engine.ingest_observation(self.data["observations"][0])
        with self.assertRaises(ContractError) as caught:
            engine.ingest_evidence(payload)
        self.assertEqual(caught.exception.status_code, 422)

    def test_timestamp_without_timezone_is_422(self):
        payload = deepcopy(self.data["observations"][0])
        payload["timestamp"] = "2026-07-31T03:06:00"
        with self.assertRaises(ContractError) as caught:
            MockRiskEngine().ingest_observation(payload)
        self.assertEqual(caught.exception.status_code, 422)

    def test_invalid_risk_level_is_rejected(self):
        engine, _ = run_fixed_sequence()
        payload = engine.snapshot()["events"][0]
        payload["risk_level"] = "BLUE"
        with self.assertRaises(ContractError) as caught:
            validate_contract(RiskEvent, payload)
        self.assertEqual(caught.exception.status_code, 422)


class EngineContractTests(unittest.TestCase):
    def setUp(self):
        self.data = sequence()

    def test_duplicate_same_payload_is_idempotent(self):
        engine = MockRiskEngine()
        first = engine.ingest_observation(self.data["observations"][0])
        second = engine.ingest_observation(self.data["observations"][0])
        self.assertIs(first, second)
        self.assertEqual(len(engine.observations), 1)

    def test_duplicate_id_with_changed_payload_is_409(self):
        engine = MockRiskEngine()
        engine.ingest_observation(self.data["observations"][0])
        changed = deepcopy(self.data["observations"][0])
        changed["feature_value"] = 9.9
        with self.assertRaises(ConflictError) as caught:
            engine.ingest_observation(changed)
        self.assertEqual(caught.exception.status_code, 409)

    def test_unknown_observation_reference_is_409(self):
        engine = MockRiskEngine()
        with self.assertRaises(ConflictError) as caught:
            engine.ingest_evidence(self.data["evidence"][0])
        self.assertEqual(caught.exception.status_code, 409)

    def test_source_mismatch_is_409(self):
        engine = MockRiskEngine()
        engine.ingest_observation(self.data["observations"][0])
        payload = deepcopy(self.data["evidence"][0])
        payload["source_mode"] = "PUBLIC_DATASET"
        with self.assertRaises(ConflictError):
            engine.ingest_evidence(payload)

    def test_rapid_rise_alone_does_not_upgrade(self):
        engine = MockRiskEngine()
        engine.ingest_observation(self.data["observations"][1])
        engine.ingest_evidence(self.data["evidence"][1])
        self.assertIsNone(engine.evaluate(RESIDENT_ID))

    def test_rapid_rise_and_sway_trigger_orange(self):
        engine = MockRiskEngine()
        for index in (1, 2):
            engine.ingest_observation(self.data["observations"][index])
            engine.ingest_evidence(self.data["evidence"][index])
        event = engine.evaluate(RESIDENT_ID)
        self.assertEqual(event.risk_level.value, "ORANGE")
        self.assertEqual(event.status.value, "INTERVENING")

    def test_low_quality_sway_does_not_upgrade(self):
        engine = MockRiskEngine()
        engine.ingest_observation(self.data["observations"][1])
        engine.ingest_evidence(self.data["evidence"][1])
        low_observation = deepcopy(self.data["observations"][2])
        low_observation["data_quality"] = 0.69
        low_evidence = deepcopy(self.data["evidence"][2])
        low_evidence["data_quality"] = 0.69
        engine.ingest_observation(low_observation)
        engine.ingest_evidence(low_evidence)
        self.assertIsNone(engine.evaluate(RESIDENT_ID))

    def test_recovery_enters_observing_then_resolves(self):
        engine, steps = run_fixed_sequence()
        event = engine.events["event-mock-fall-001"]
        result = engine.interventions["result-mock-voice-001"]
        self.assertEqual(steps[4]["status"], "OBSERVING")
        self.assertEqual(event.status.value, "RESOLVED")
        self.assertTrue(result.resolved)
        self.assertEqual(result.risk_after, 0.24)

    def test_three_runs_are_identical_and_tool_is_idempotent(self):
        snapshots = []
        for _ in range(3):
            engine, _ = run_fixed_sequence()
            snapshots.append(engine.snapshot())
            self.assertEqual(engine.tool_call_count, 1)
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(snapshots[1], snapshots[2])


if __name__ == "__main__":
    unittest.main()
