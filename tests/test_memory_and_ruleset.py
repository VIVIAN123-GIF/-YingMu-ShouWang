from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime

from contracts.v1.engine import MockRiskEngine
from contracts.v1.memory import BaselineStatus
from contracts.v1.mock_data import RESIDENT_ID, sequence
from contracts.v1.mock_memory_data import safe_history
from contracts.v1.models import EventStatus, RiskLevel
from contracts.v1.rehearsal import run_fixed_sequence
from contracts.v1.ruleset import load_ruleset


class MemoryAndRulesetTests(unittest.TestCase):
    def setUp(self):
        self.data = sequence()
        self.now = datetime.fromisoformat("2026-07-31T03:08:30+08:00")

    def test_ruleset_has_fixed_windows_weights_and_mock_score(self):
        ruleset = load_ruleset()
        self.assertEqual(ruleset.version, "ruleset-v1.0")
        self.assertEqual(ruleset.windows, {"short_seconds": 30, "medium_hours": 24, "long_days": 7})
        self.assertEqual(sum(ruleset.risk_weights.values()), 1.0)
        engine, _ = run_fixed_sequence()
        self.assertEqual(engine.events["event-mock-fall-001"].risk_score, 0.82)

    def test_three_memory_windows_are_time_bounded(self):
        engine = MockRiskEngine()
        history = safe_history()
        for observation, evidence in zip(history["observations"], history["evidence"]):
            engine.ingest_observation(observation)
            engine.ingest_evidence(evidence)
        for index in (1, 2, 3):
            engine.ingest_observation(self.data["observations"][index])
            if index == 3:
                engine.ingest_observation(self.data["observations"][4])
            engine.ingest_evidence(self.data["evidence"][index])
        snapshot = engine.memory.snapshot(RESIDENT_ID, datetime.fromisoformat("2026-07-31T03:07:30+08:00"))
        self.assertEqual(snapshot["short"]["window_seconds"], 30)
        self.assertEqual(snapshot["medium"]["window_hours"], 24)
        self.assertEqual(snapshot["long"]["window_days"], 7)
        self.assertIn("evi-mock-posture-recovered-001", snapshot["short"]["evidence_ids"])
        self.assertNotIn("evi-memory-rise_duration-01", snapshot["short"]["evidence_ids"])
        self.assertGreaterEqual(len(snapshot["long"]["evidence_ids"]), 3)

    def test_green_high_quality_safe_sample_updates_baseline(self):
        engine = MockRiskEngine()
        observation = deepcopy(self.data["observations"][0])
        evidence = deepcopy(self.data["evidence"][0])
        engine.ingest_observation(observation)
        engine.ingest_evidence(evidence)
        decision = engine.memory.baseline_decisions[-1]
        self.assertTrue(decision["accepted"])
        baseline_at = datetime.fromisoformat(observation["timestamp"])
        self.assertEqual(engine.memory.baseline(RESIDENT_ID, baseline_at)["rise_duration"].sample_count, 1)

    def test_yellow_orange_and_dangerous_samples_do_not_update_baseline(self):
        engine = MockRiskEngine()
        history = safe_history()
        first_obs, first_ev = history["observations"][0], history["evidence"][0]
        engine.ingest_observation(first_obs)
        engine.ingest_evidence(first_ev)
        engine.memory.set_state(RESIDENT_ID, RiskLevel.YELLOW)
        safe = deepcopy(first_ev)
        safe["evidence_id"] = "evi-yellow-safe"
        safe["observation_ids"] = [first_obs["observation_id"]]
        engine.ingest_evidence(safe)
        self.assertIn("state_yellow_blocks_baseline_update", engine.memory.baseline_decisions[-1]["reason"])
        engine.memory.set_state(RESIDENT_ID, RiskLevel.ORANGE)
        orange_safe = deepcopy(first_ev)
        orange_safe["evidence_id"] = "evi-orange-safe"
        orange_safe["observation_ids"] = [first_obs["observation_id"]]
        engine.ingest_evidence(orange_safe)
        self.assertIn("state_orange_blocks_baseline_update", engine.memory.baseline_decisions[-1]["reason"])
        dangerous = deepcopy(self.data["evidence"][1])
        dangerous["observation_ids"] = [self.data["observations"][1]["observation_id"]]
        engine.ingest_observation(self.data["observations"][1])
        engine.ingest_evidence(dangerous)
        self.assertFalse(engine.memory.baseline_decisions[-1]["accepted"])

    def test_low_quality_safe_sample_does_not_update_baseline(self):
        engine = MockRiskEngine()
        observation = deepcopy(self.data["observations"][0])
        evidence = deepcopy(self.data["evidence"][0])
        observation["observation_id"] = "obs-safe-low-quality"
        evidence["evidence_id"] = "evi-safe-low-quality"
        evidence["observation_ids"] = [observation["observation_id"]]
        observation["data_quality"] = evidence["data_quality"] = 0.69
        engine.ingest_observation(observation)
        engine.ingest_evidence(evidence)
        decision = next(item for item in engine.memory.baseline_decisions if item["evidence_id"] == evidence["evidence_id"])
        self.assertFalse(decision["accepted"])
        self.assertEqual(decision["reason"], "confidence_or_data_quality_below_threshold")

    def test_three_days_form_provisional_baseline(self):
        engine = MockRiskEngine()
        history = safe_history()
        rise_pairs = [
            (observation, evidence)
            for observation, evidence in zip(history["observations"], history["evidence"])
            if evidence["evidence_type"] == "rise_duration_baseline_sample"
        ][:3]
        for observation, evidence in rise_pairs:
            engine.ingest_observation(observation)
            engine.ingest_evidence(evidence)
        baseline = engine.memory.baseline(RESIDENT_ID, datetime.fromisoformat("2026-07-21T12:00:00+08:00"))
        self.assertEqual(baseline["rise_duration"].status, BaselineStatus.PROVISIONAL)

    def test_seven_day_mock_history_is_stable_with_median_and_mad(self):
        engine = MockRiskEngine()
        history = safe_history()
        for observation, evidence in zip(history["observations"], history["evidence"]):
            engine.ingest_observation(observation)
            engine.ingest_evidence(evidence)
        baseline = engine.memory.baseline(RESIDENT_ID, datetime.fromisoformat("2026-07-25T12:00:00+08:00"))
        self.assertEqual(baseline["rise_duration"].status, BaselineStatus.STABLE)
        self.assertEqual(baseline["rise_duration"].median, 3.5)
        self.assertAlmostEqual(baseline["trunk_sway"].mad, 0.1)
        self.assertEqual(baseline["activity_range"].distinct_days, 7)

    def test_low_quality_generates_system_evidence_and_trace(self):
        engine = MockRiskEngine()
        observation = deepcopy(self.data["observations"][2])
        evidence = deepcopy(self.data["evidence"][2])
        observation["observation_id"] = "obs-low-quality"
        evidence["evidence_id"] = "evi-low-quality"
        evidence["observation_ids"] = [observation["observation_id"]]
        observation["data_quality"] = evidence["data_quality"] = 0.69
        engine.ingest_observation(observation)
        engine.ingest_evidence(evidence)
        self.assertIn("sys-quality-evi-low-quality", engine.evidences)
        self.assertEqual(engine.traces[-1].matched_rule, "R-FALL-03")
        self.assertIsNone(engine.evaluate(RESIDENT_ID, datetime.fromisoformat(evidence["timestamp"])))

    def test_rapid_rise_alone_matches_rule_01(self):
        engine = MockRiskEngine()
        engine.ingest_observation(self.data["observations"][1])
        engine.ingest_evidence(self.data["evidence"][1])
        self.assertIsNone(engine.evaluate(RESIDENT_ID))
        self.assertEqual(engine.traces[-1].matched_rule, "R-FALL-01")

    def test_rapid_rise_and_sway_matches_rule_02_and_score(self):
        engine = MockRiskEngine()
        for index in (1, 2):
            engine.ingest_observation(self.data["observations"][index])
            engine.ingest_evidence(self.data["evidence"][index])
        event = engine.evaluate(RESIDENT_ID)
        if event is None:
            self.fail("rapid_rise + trunk_sway should create a RiskEvent")
        self.assertEqual((event.risk_level.value, event.status.value, event.risk_score), ("ORANGE", "INTERVENING", 0.82))
        self.assertEqual(engine.traces[-1].matched_rule, "R-FALL-02")

    def test_recovery_observing_then_resolution_rule_04_and_05(self):
        engine, _ = run_fixed_sequence()
        matches = [trace.matched_rule for trace in engine.traces]
        self.assertIn("R-FALL-04", matches)
        self.assertIn("R-FALL-05", matches)
        self.assertEqual(engine.events["event-mock-fall-001"].status.value, "RESOLVED")

    def test_observation_hazard_matches_rule_06_and_allows_second_intervention(self):
        engine = MockRiskEngine()
        data = self.data
        for index in (1, 2):
            engine.ingest_observation(data["observations"][index])
            engine.ingest_evidence(data["evidence"][index])
        event = engine.evaluate(RESIDENT_ID)
        if event is None:
            self.fail("initial fall evidence should create a RiskEvent")
        engine.intervene(event.event_id)
        recovered = deepcopy(data["observations"][3])
        recovered["timestamp"] = "2026-07-31T03:07:29+08:00"
        recovered["observation_id"] = "obs-recovery-r6"
        angle = deepcopy(data["observations"][4])
        angle["timestamp"] = recovered["timestamp"]
        angle["observation_id"] = "obs-recovery-r6-angle"
        recovery_evidence = deepcopy(data["evidence"][3])
        recovery_evidence["timestamp"] = recovered["timestamp"]
        recovery_evidence["evidence_id"] = "evi-recovery-r6"
        recovery_evidence["observation_ids"] = [recovered["observation_id"], angle["observation_id"]]
        engine.ingest_observation(recovered)
        engine.ingest_observation(angle)
        engine.ingest_evidence(recovery_evidence)
        observing = engine.evaluate(RESIDENT_ID)
        if observing is None:
            self.fail("posture_recovered should keep the RiskEvent in OBSERVING")
        self.assertEqual(observing.status.value, "OBSERVING")
        sway_obs = deepcopy(data["observations"][2])
        sway_obs["timestamp"] = "2026-07-31T03:07:40+08:00"
        sway_obs["observation_id"] = "obs-sway-r6"
        sway_evidence = deepcopy(data["evidence"][2])
        sway_evidence["timestamp"] = sway_obs["timestamp"]
        sway_evidence["evidence_id"] = "evi-sway-r6"
        sway_evidence["observation_ids"] = [sway_obs["observation_id"]]
        engine.ingest_observation(sway_obs)
        engine.ingest_evidence(sway_evidence)
        event = engine.evaluate(RESIDENT_ID)
        if event is None:
            self.fail("a hazard during observation should return the active RiskEvent")
        self.assertEqual(event.status.value, "INTERVENING")
        self.assertEqual(engine.traces[-1].matched_rule, "R-FALL-06")
        engine.intervene(event.event_id)
        self.assertEqual(engine.tool_call_count, 2)
        third_obs = deepcopy(data["observations"][2])
        third_obs["timestamp"] = "2026-07-31T03:07:45+08:00"
        third_obs["observation_id"] = "obs-sway-after-two-interventions"
        third_evidence = deepcopy(data["evidence"][2])
        third_evidence["timestamp"] = third_obs["timestamp"]
        third_evidence["evidence_id"] = "evi-sway-after-two-interventions"
        third_evidence["observation_ids"] = [third_obs["observation_id"]]
        engine.ingest_observation(third_obs)
        engine.ingest_evidence(third_evidence)
        escalated = engine.evaluate(RESIDENT_ID)
        if escalated is None:
            self.fail("a third hazard after two interventions should escalate")
        self.assertEqual((escalated.risk_level.value, escalated.status.value), ("RED", "ESCALATED"))
        self.assertEqual(engine.traces[-1].matched_rule, "R-FALL-07")

    def test_persistent_instability_matches_rule_07(self):
        engine = MockRiskEngine()
        for index in (1, 2):
            engine.ingest_observation(self.data["observations"][index])
            engine.ingest_evidence(self.data["evidence"][index])
        event = engine.evaluate(RESIDENT_ID)
        if event is None:
            self.fail("initial fall evidence should create a RiskEvent")
        self.assertEqual(event.status, EventStatus.INTERVENING)
        obs = deepcopy(self.data["observations"][2])
        obs["observation_id"] = "obs-persistent"
        obs["timestamp"] = self.now.isoformat()
        ev = deepcopy(self.data["evidence"][2])
        ev["evidence_id"] = "evi-persistent"
        ev["observation_ids"] = [obs["observation_id"]]
        ev["timestamp"] = self.now.isoformat()
        ev["evidence_type"] = "persistent_instability"
        ev["severity"] = 0.98
        engine.ingest_observation(obs)
        engine.ingest_evidence(ev)
        escalated = engine.evaluate(RESIDENT_ID, self.now)
        if escalated is None:
            self.fail("persistent instability should escalate the active event")
        self.assertEqual((escalated.risk_level.value, escalated.status.value), ("RED", "ESCALATED"))
        self.assertEqual(engine.traces[-1].matched_rule, "R-FALL-07")

    def test_duplicate_evidence_records_rule_01_system_trace_without_new_event(self):
        engine = MockRiskEngine()
        engine.ingest_observation(self.data["observations"][1])
        engine.ingest_evidence(self.data["evidence"][1])
        before = len(engine.traces)
        engine.ingest_evidence(self.data["evidence"][1])
        self.assertEqual(len(engine.events), 0)
        self.assertEqual(engine.traces[-1].matched_rule, "R-SYSTEM-01")
        self.assertGreater(len(engine.traces), before)

    def test_rule_trace_includes_windows_and_non_match_reason(self):
        engine = MockRiskEngine()
        engine.ingest_observation(self.data["observations"][1])
        engine.ingest_evidence(self.data["evidence"][1])
        engine.evaluate(RESIDENT_ID)
        trace = engine.traces[-1].as_dict()
        self.assertEqual(trace["queried_windows"], {"short_seconds": 30, "medium_hours": 24, "long_days": 7})
        self.assertIn("R-FALL-02", trace["not_matched"])


if __name__ == "__main__":
    unittest.main()
