import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from behavior_evidence import build_behavior_evidence_bundle  # noqa: E402
from submit_to_backend import load_bundle, submit_bundle  # noqa: E402


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = body

    def read(self):
        return json.dumps(self.body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class BackendSubmissionTests(unittest.TestCase):
    def setUp(self):
        settings = json.loads(
            (ROOT / "samples" / "mock_behavior_statistics.json").read_text(encoding="utf-8")
        )
        self.bundle = build_behavior_evidence_bundle(settings)

    def test_dry_run_validates_all_items_without_http(self):
        log = submit_bundle(self.bundle, "http://127.0.0.1:8000", dry_run=True)
        self.assertTrue(log["success"])
        self.assertEqual(len(log["results"]), 9)
        self.assertTrue(all(item["status"] == "validated" for item in log["results"]))

    def test_observations_are_submitted_before_evidence(self):
        urls = []

        def opener(request, timeout):
            urls.append(request.full_url)
            body = {"saved": True, "idempotent": False}
            return FakeResponse(201, body)

        log = submit_bundle(self.bundle, "http://test.local", opener=opener)
        self.assertTrue(log["success"])
        self.assertEqual(len(urls), 9)
        self.assertTrue(all(url.endswith("/observations") for url in urls[:6]))
        self.assertTrue(all(url.endswith("/evidence") for url in urls[6:]))
        self.assertNotIn("risk_level", json.dumps(log))

    def test_bundle_rejects_missing_linked_observation(self):
        invalid = json.loads(json.dumps(self.bundle))
        invalid["observations"].pop()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不存在的Observation"):
                load_bundle(path)


if __name__ == "__main__":
    unittest.main()
