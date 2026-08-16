import asyncio
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT.parents[2]))

from adapters.contract import ContractValidationError, build_batch, validate_job  # noqa: E402
from adapters.language_adapter import run as run_language  # noqa: E402
from adapters.trajectory_adapter import run as run_trajectory  # noqa: E402
from contracts.v1.algorithm import (  # noqa: E402
    AdapterBatch as CanonicalAdapterBatch,
    AlgorithmJob as CanonicalAlgorithmJob,
    validate_batch_for_job,
)


class AdapterContractTests(unittest.TestCase):
    def setUp(self):
        self.trajectory_job = json.loads(
            (ROOT / "adapter_contract" / "algorithm_job.trajectory.json").read_text(encoding="utf-8")
        )
        self.language_job = json.loads(
            (ROOT / "adapter_contract" / "algorithm_job.language.json").read_text(encoding="utf-8")
        )

    def test_entries_are_async_and_inherit_job_fields(self):
        trajectory = asyncio.run(run_trajectory(self.trajectory_job))
        language = asyncio.run(run_language(self.language_job))
        self.assertEqual(trajectory["module"], "TRAJECTORY")
        self.assertEqual(language["module"], "LANGUAGE")
        self.assertIn(trajectory["status"], {"SUCCESS", "NO_EVIDENCE", "LOW_QUALITY"})
        self.assertEqual(language["status"], "SUCCESS")
        for batch, job in ((trajectory, self.trajectory_job), (language, self.language_job)):
            self.assertEqual(batch["schema_version"], "adapter-batch/1.0")
            self.assertNotIn("risk_level", batch)
            for observation in batch["observations"]:
                for field in ("resident_id", "asset_id", "source_mode", "simulated"):
                    self.assertEqual(observation[field], job[field])
            observation_ids = {item["observation_id"] for item in batch["observations"]}
            for evidence in batch["evidences"]:
                self.assertNotIn("asset_id", evidence)
                self.assertTrue(set(evidence["observation_ids"]).issubset(observation_ids))
                self.assertEqual(evidence["resident_id"], job["resident_id"])

            canonical_job = CanonicalAlgorithmJob.model_validate(job)
            canonical_batch = CanonicalAdapterBatch.model_validate(batch)
            validate_batch_for_job(canonical_batch, canonical_job)
        self.assertEqual(
            language["resident_response_candidate"]["intent"],
            "STABLE",
        )

    def test_ids_are_stable_for_retries(self):
        first = asyncio.run(run_language(self.language_job))
        second = asyncio.run(run_language(self.language_job))
        self.assertEqual(
            [item["observation_id"] for item in first["observations"]],
            [item["observation_id"] for item in second["observations"]],
        )
        self.assertEqual(
            [item["evidence_id"] for item in first["evidences"]],
            [item["evidence_id"] for item in second["evidences"]],
        )

    def test_failed_input_has_no_fabricated_results(self):
        missing = dict(self.trajectory_job, media_locator="does-not-exist.json")
        result = asyncio.run(run_trajectory(missing))
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["observations"], [])
        self.assertEqual(result["evidences"], [])
        self.assertEqual(result["error"]["code"], "TRAJECTORY_INPUT_ERROR")

    def test_no_evidence_and_low_quality_batch_contract(self):
        job = validate_job(self.trajectory_job)
        with self.assertRaises(ContractValidationError):
            build_batch(
                job, module="TRAJECTORY", status="NO_EVIDENCE", adapter_version="test-v1",
                started_at="2026-08-16T10:00:00+08:00", completed_at="2026-08-16T10:00:01+08:00",
                observations=[], evidences=[], diagnostics={"test": True},
            )
        with self.assertRaises(ContractValidationError):
            build_batch(
                job, module="TRAJECTORY", status="LOW_QUALITY", adapter_version="test-v1",
                started_at="2026-08-16T10:00:00+08:00", completed_at="2026-08-16T10:00:01+08:00",
                observations=[], evidences=[], diagnostics={"tracking_quality": 0.0},
            )


if __name__ == "__main__":
    unittest.main()
