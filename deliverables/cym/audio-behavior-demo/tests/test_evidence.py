import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from evidence import EvidenceValidationError  # noqa: E402
from evidence import validate_evidence  # noqa: E402
from evidence import validate_evidence_collection  # noqa: E402
from generate_evidence_samples import build_samples  # noqa: E402


class EvidenceValidationTests(unittest.TestCase):
    def setUp(self):
        self.samples = build_samples()
        self.valid_evidence = copy.deepcopy(self.samples[0])

    def test_three_samples_are_valid(self):
        self.assertEqual(len(validate_evidence_collection(self.samples)), 3)

    def test_missing_required_field_is_rejected(self):
        self.valid_evidence.pop("confidence")
        with self.assertRaisesRegex(EvidenceValidationError, "缺少必填字段"):
            validate_evidence(self.valid_evidence)

    def test_invalid_enum_is_rejected(self):
        self.valid_evidence["risk_domain"] = "UNKNOWN"
        with self.assertRaisesRegex(EvidenceValidationError, "risk_domain"):
            validate_evidence(self.valid_evidence)

    def test_out_of_range_score_is_rejected(self):
        self.valid_evidence["severity"] = 1.01
        with self.assertRaisesRegex(EvidenceValidationError, "severity"):
            validate_evidence(self.valid_evidence)

    def test_timestamp_without_timezone_is_rejected(self):
        self.valid_evidence["timestamp"] = "2026-07-24T10:00:00"
        with self.assertRaisesRegex(EvidenceValidationError, "必须包含时区"):
            validate_evidence(self.valid_evidence)

    def test_duplicate_evidence_id_is_rejected(self):
        duplicate = copy.deepcopy(self.samples[0])
        with self.assertRaisesRegex(EvidenceValidationError, "evidence_id重复"):
            validate_evidence_collection([self.samples[0], duplicate])


if __name__ == "__main__":
    unittest.main()
