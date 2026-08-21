import asyncio
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from adapters.contract import build_batch, validate_job  # noqa: E402
from adapters.language_adapter import run as run_language  # noqa: E402
from adapters.trajectory_adapter import (  # noqa: E402
    SceneConfigMismatchError,
    _resolve_scene_config,
    run as run_trajectory,
)
from backend.service.adapter_registry import AdapterRegistry  # noqa: E402
from contracts.v1.algorithm import (  # noqa: E402
    AdapterBatch,
    AlgorithmJob,
    AlgorithmModule,
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
        self.assertTrue(inspect.iscoroutinefunction(run_trajectory))
        self.assertTrue(inspect.iscoroutinefunction(run_language))
        self.assertIs(inspect.signature(run_trajectory).parameters["job"].annotation, AlgorithmJob)
        self.assertIs(inspect.signature(run_language).parameters["job"].annotation, AlgorithmJob)
        trajectory_job = AlgorithmJob.model_validate(self.trajectory_job)
        language_job = AlgorithmJob.model_validate(self.language_job)
        trajectory = asyncio.run(run_trajectory(trajectory_job))
        language = asyncio.run(run_language(language_job))
        self.assertEqual(trajectory.module.value, "TRAJECTORY")
        self.assertEqual(language.module.value, "LANGUAGE")
        self.assertIn(trajectory.status.value, {"SUCCESS", "NO_EVIDENCE", "LOW_QUALITY"})
        self.assertEqual(language.status.value, "SUCCESS")
        self.assertIsInstance(trajectory, AdapterBatch)
        self.assertIsInstance(language, AdapterBatch)
        for batch, job in ((trajectory, trajectory_job), (language, language_job)):
            self.assertEqual(batch.schema_version, "adapter-batch/1.0")
            self.assertFalse(hasattr(batch, "risk_level"))
            for observation in batch.observations:
                for field in ("resident_id", "asset_id", "source_mode", "simulated"):
                    self.assertEqual(getattr(observation, field), getattr(job, field))
            observation_ids = {item.observation_id for item in batch.observations}
            for evidence in batch.evidences:
                self.assertFalse(hasattr(evidence, "asset_id"))
                self.assertTrue(set(evidence.observation_ids).issubset(observation_ids))
                self.assertEqual(evidence.resident_id, job.resident_id)
            validate_batch_for_job(batch, job)

    def test_registry_loads_canonical_entrypoints(self):
        configured = {
            "YINGMU_TRAJECTORY_ADAPTER": "adapters.trajectory_adapter:run",
            "YINGMU_LANGUAGE_ADAPTER": "adapters.language_adapter:run",
        }
        with patch.dict(os.environ, configured, clear=False):
            registry = AdapterRegistry()
            registry.load_configured()

        for module in (AlgorithmModule.TRAJECTORY, AlgorithmModule.LANGUAGE):
            adapter = registry.get(module)
            self.assertTrue(inspect.iscoroutinefunction(adapter))
            signature = inspect.signature(adapter)
            self.assertIs(signature.parameters["job"].annotation, AlgorithmJob)
            self.assertIs(signature.return_annotation, AdapterBatch)

        trajectory_job = AlgorithmJob.model_validate(self.trajectory_job)
        language_job = AlgorithmJob.model_validate(self.language_job)
        trajectory = asyncio.run(registry.invoke(AlgorithmModule.TRAJECTORY, trajectory_job))
        language = asyncio.run(registry.invoke(AlgorithmModule.LANGUAGE, language_job))
        self.assertIsInstance(trajectory, AdapterBatch)
        self.assertIsInstance(language, AdapterBatch)

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
        self.assertEqual(
            first.resident_response_candidate,
            second.resident_response_candidate,
        )

    def test_language_accepts_only_redacted_results_and_emits_frozen_response(self):
        result = asyncio.run(run_language(self.language_job))
        self.assertEqual(result.resident_response_candidate.intent, "STABLE")
        response_values = {
            item.feature_value
            for item in result.observations
            if item.feature_name == "resident_response"
        }
        self.assertEqual(response_values, {"resident_response_stable"})
        serialized = result.model_dump_json()
        self.assertNotIn(self.language_job["media_locator"], serialized)
        self.assertNotIn("media_locator", serialized)
        self.assertNotIn("audio_path", serialized)

    def test_language_rejects_raw_audio_and_raw_transcript_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "raw.wav"
            audio_path.write_bytes(b"not-a-real-wave")
            audio_job = dict(self.language_job, media_locator=str(audio_path))
            audio_result = asyncio.run(run_language(audio_job))
            self.assertEqual(audio_result.status.value, "FAILED")
            self.assertEqual(audio_result.error.code, "LANGUAGE_INPUT_ERROR")

            unsafe_path = Path(temp_dir) / "unsafe.json"
            unsafe_path.write_text(
                json.dumps({
                    "schema_version": "language-analysis/1.0",
                    "raw_transcript": "forbidden",
                    "keyword_groups": [],
                    "resident_response": None,
                    "audio_quality": 0.9,
                    "processing_source": "ASR_REDACTED",
                    "model_version": "test",
                }),
                encoding="utf-8",
            )
            unsafe_job = dict(self.language_job, media_locator=str(unsafe_path))
            unsafe_result = asyncio.run(run_language(unsafe_job))
            self.assertEqual(unsafe_result.status.value, "FAILED")
            self.assertEqual(unsafe_result.observations, [])
            self.assertEqual(unsafe_result.evidences, [])

    def test_language_help_is_the_only_other_resident_response(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "help.json"
            input_path.write_text(
                json.dumps({
                    "schema_version": "language-analysis/1.0",
                    "keyword_groups": [],
                    "resident_response": "resident_response_help",
                    "audio_quality": 0.9,
                    "processing_source": "MOCK_REDACTED",
                    "model_version": "test-v1",
                    "language": "Chinese",
                }),
                encoding="utf-8",
            )
            job = dict(self.language_job, media_locator=str(input_path))
            result = asyncio.run(run_language(job))
            self.assertEqual(result.status.value, "NO_EVIDENCE")
            self.assertEqual(result.resident_response_candidate.intent, "HELP")
            response_values = {
                item.feature_value
                for item in result.observations
                if item.feature_name == "resident_response"
            }
            self.assertEqual(response_values, {"resident_response_help"})
            self.assertNotIn("UNCERTAIN", result.model_dump_json())

    def test_trajectory_json_can_join_pacing_and_long_term_trends(self):
        job = dict(
            self.trajectory_job,
            media_locator="adapter_contract/trajectory_input.trends.json",
        )
        result = asyncio.run(run_trajectory(job))
        self.assertEqual(result.status.value, "SUCCESS")
        evidence_types = {item.evidence_type for item in result.evidences}
        self.assertTrue({
            "unusual_pacing",
            "activity_range_decline",
            "room_transition_decline",
        }.issubset(evidence_types))
        self.assertTrue(all(item.asset_id == job["asset_id"] for item in result.observations))

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

    def test_scene_config_must_match_camera_position(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "scene-demo-v1.json"
            config_path.write_text(json.dumps({
                "scene_config_id": "scene-demo-v1",
                "camera_position_id": "another-camera",
                "frame_size": [640, 480],
                "regions": [{
                    "id": "all",
                    "polygon": [[0, 0], [640, 0], [640, 480]],
                }],
            }), encoding="utf-8")
            job = AlgorithmJob.model_validate(self.trajectory_job)
            with patch.dict(
                os.environ,
                {"YINGMU_SCENE_CONFIG_DIR": temp_dir},
                clear=False,
            ):
                with self.assertRaises(SceneConfigMismatchError):
                    _resolve_scene_config(job)


if __name__ == "__main__":
    unittest.main()
