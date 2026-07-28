import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import whisper_demo  # noqa: E402
from observation import validate_observation_collection  # noqa: E402


class WhisperCheckTests(unittest.TestCase):
    def run_check(self, status):
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["whisper_demo.py", "--check"]),
            patch.object(whisper_demo, "environment_status", return_value=status),
            contextlib.redirect_stdout(output),
        ):
            return whisper_demo.main(), output.getvalue()

    def test_check_passes_when_dependencies_are_available(self):
        return_code, output = self.run_check(
            {
                "python_version": "3.13.14",
                "whisper_installed": True,
                "whisper_version": "20250625",
                "ffmpeg_available": True,
                "ffmpeg_command": "ffmpeg",
            }
        )
        self.assertEqual(return_code, 0)
        self.assertIn('"ffmpeg_available": true', output)

    def test_check_explains_missing_ffmpeg(self):
        return_code, output = self.run_check(
            {
                "python_version": "3.13.14",
                "whisper_installed": True,
                "whisper_version": "20250625",
                "ffmpeg_available": False,
                "ffmpeg_command": None,
            }
        )
        self.assertEqual(return_code, 2)
        self.assertIn("未找到FFmpeg", output)
        self.assertIn("winget install", output)


class WhisperObservationTests(unittest.TestCase):
    def test_transcript_builds_valid_observations(self):
        observations = whisper_demo.build_audio_observations(
            "可以保證收益，請把驗證馬告訴我並馬上完成轉帳",
            resident_id="resident-001",
            model="tiny",
            language="Chinese",
            asset_id="asset-audio-0001",
            simulated=True,
        )

        self.assertEqual(len(observations), 4)
        self.assertIs(validate_observation_collection(observations), observations)
        by_name = {
            item["feature_name"]: item["feature_value"]
            for item in observations
        }
        self.assertEqual(by_name["fraud_keyword_match_count"], 3)
        self.assertIn("guaranteed_return", by_name["fraud_keyword_labels"])
        self.assertTrue(by_name["audio_transcript_available"])


if __name__ == "__main__":
    unittest.main()
