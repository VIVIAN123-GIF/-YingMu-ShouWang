import asyncio
import inspect
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from adapters.contract import build_batch, validate_job  # noqa: E402
from adapters.language_adapter import run as run_language  # noqa: E402
from adapters.trajectory_adapter import run as run_trajectory  # noqa: E402
from contracts.v1.algorithm import AdapterBatch, AlgorithmJob  # noqa: E402


class AdapterContractTests(unittest.TestCase):
    def setUp(self):
        self.trajectory_job = json.loads(
            (ROOT / "adapter_contract" / "algorithm_job.trajectory.json").read_text(encoding="utf-8")
        )
        self.language_job = json.loads(
            (ROOT / "adapter_contract" / "algorithm_job.language.json").read_text(encoding="utf-8")
        )

    def test_entries_are_async_and_inherit_job_fields(self):
        self.assertTrue(inspect.iscoroutinefunction(run_trajectory))
        self.assertTrue(inspect.iscoroutinefunction(run_language))
        self.assertIs(inspect.signature(run_trajectory).parameters["job"].annotation, AlgorithmJob)
        self.assertIs(inspect.signature(run_language).parameters["job"].annotation, AlgorithmJob)
        trajectory = asyncio.run(run_trajectory(self.trajectory_job))
        language = asyncio.run(run_language(self.language_job))
        self.assertEqual(trajectory.module.value, "TRAJECTORY")
        self.assertEqual(language.module.value, "LANGUAGE")
        self.assertIn(trajectory.status.value, {"SUCCESS", "NO_EVIDENCE", "LOW_QUALITY"})
        self.assertEqual(language.status.value, "SUCCESS")
        self.assertIsInstance(trajectory, AdapterBatch)
        self.assertIsInstance(language, AdapterBatch)
        for batch, job in ((trajectory, self.trajectory_job), (language, self.language_job)):
            self.assertEqual(batch.schema_version, "adapter-batch/1.0")
            self.assertFalse(hasattr(batch, "risk_level"))
            for observation in batch.observations:
                for field in ("resident_id", "asset_id", "source_mode", "simulated"):
                    expected = job[field]
                    actual = getattr(observation, field)
                    actual = actual.value if hasattr(actual, "value") else actual
                    self.assertEqual(actual, expected)
            observation_ids = {item.observation_id for item in batch.observations}
            for evidence in batch.evidences:
                self.assertFalse(hasattr(evidence, "asset_id"))
                self.assertTrue(set(evidence.observation_ids).issubset(observation_ids))
                self.assertEqual(evidence.resident_id, job["resident_id"])

    def test_ids_are_stable_for_retries(self):
        first = asyncio.run(run_language(self.language_job))
        second = asyncio.run(run_language(self.language_job))
        self.assertEqual(
            [item.observation_id for item in first.observations],
            [item.observation_id for item in second.observations],
        )
        self.assertEqual(
            [item.evidence_id for item in first.evidences],
            [item.evidence_id for item in second.evidences],
        )

    def test_failed_input_has_no_fabricated_results(self):
        missing = dict(self.trajectory_job, media_locator="does-not-exist.json")
        result = asyncio.run(run_trajectory(missing))
        self.assertEqual(result.status.value, "FAILED")
        self.assertEqual(result.observations, [])
        self.assertEqual(result.evidences, [])
        self.assertEqual(result.error.code, "TRAJECTORY_INPUT_ERROR")

    def test_no_evidence_and_low_quality_batch_contract(self):
        job = validate_job(self.trajectory_job)
        normal = asyncio.run(run_trajectory(job))
        self.assertEqual(normal.status.value, "NO_EVIDENCE")
        low_job = dict(self.trajectory_job, media_locator="adapter_contract/trajectory_input.low_quality.summary.json")
        low = asyncio.run(run_trajectory(low_job))
        self.assertEqual(low.status.value, "LOW_QUALITY")
        self.assertEqual(low.evidences[0].evidence_type, "tracking_lost")


if __name__ == "__main__":
    unittest.main()
