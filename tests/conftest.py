"""Keep every test process isolated from local live-device configuration."""

import os
import tempfile
from pathlib import Path


_TEST_DATABASE_DIR = Path(tempfile.mkdtemp(prefix="yingmu-pytest-"))
os.environ["YINGMU_DB_PATH"] = str(_TEST_DATABASE_DIR / "test.db")
os.environ["YINGMU_ENV"] = "mock"
os.environ["YINGMU_CONTROL_TOKEN"] = "test-control-token"
os.environ["EZVIZ_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST"] = "false"
os.environ["EZVIZ_VOICE_VERIFIED"] = "false"
os.environ["EZVIZ_LIVE_PLAYBACK_VERIFIED"] = "false"
os.environ["YINGMU_STREAM_BUFFER_ENABLED"] = "false"
os.environ["YINGMU_STREAM_BUFFER_STALL_SECONDS"] = "8"
os.environ["MIN_EVIDENCE_QUALITY"] = "0.7"
os.environ["MIN_EVIDENCE_CONFIDENCE"] = "0.8"
