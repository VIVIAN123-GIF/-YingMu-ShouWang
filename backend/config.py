import os
from dotenv import load_dotenv

from contracts.v1.ruleset import load_ruleset

load_dotenv()

ENV_MODE = os.getenv("YINGMU_ENV", "mock").lower()
if ENV_MODE not in {"mock", "live"}:
    raise RuntimeError("YINGMU_ENV must be mock or live")

EZVIZ_BASE_URL = "http://127.0.0.1:8001/mock" if ENV_MODE == "mock" else "https://open.ys7.com/api/lapp"
EZVIZ_APP_KEY = os.getenv("EZVIZ_APP_KEY", "mock_default_key" if ENV_MODE == "mock" else "")
EZVIZ_APP_SECRET = os.getenv("EZVIZ_APP_SECRET", "mock_default_secret" if ENV_MODE == "mock" else "")
EZVIZ_ACCESS_TOKEN = os.getenv("EZVIZ_ACCESS_TOKEN", "")
EZVIZ_ACCESS_TOKEN_EXPIRES_AT = os.getenv("EZVIZ_ACCESS_TOKEN_EXPIRES_AT", "")
EZVIZ_DEVICE_SERIAL = os.getenv("EZVIZ_DEVICE_SERIAL", "")
EZVIZ_CHANNEL_NO = int(os.getenv("EZVIZ_CHANNEL_NO", "1"))
EZVIZ_CAPTURE_TIMEOUT_SECONDS = float(os.getenv("EZVIZ_CAPTURE_TIMEOUT_SECONDS", "45"))
EZVIZ_DEVICE_VERIFY_CODE = os.getenv("EZVIZ_DEVICE_VERIFY_CODE", "")
EZVIZ_VOICE_VERIFIED = os.getenv("EZVIZ_VOICE_VERIFIED", "false").lower() == "true"
EZVIZ_RESIDENT_ID = os.getenv("EZVIZ_RESIDENT_ID", "")
EZVIZ_DEVICE_MODEL = os.getenv("EZVIZ_DEVICE_MODEL", "EZVIZ_C6C")
YINGMU_PRIVATE_MEDIA_ROOT = os.getenv("YINGMU_PRIVATE_MEDIA_ROOT", "")
YINGMU_CAMERA_POSITION_ID = os.getenv("YINGMU_CAMERA_POSITION_ID", "")
YINGMU_AUTHORIZATION_RECORD_ID = os.getenv("YINGMU_AUTHORIZATION_RECORD_ID", "")
YINGMU_RETENTION_UNTIL = os.getenv("YINGMU_RETENTION_UNTIL", "")
YINGMU_SNAPSHOT_MAX_BYTES = int(os.getenv("YINGMU_SNAPSHOT_MAX_BYTES", str(10 * 1024 * 1024)))
YINGMU_SNAPSHOT_DOWNLOAD_TIMEOUT_SECONDS = float(
    os.getenv("YINGMU_SNAPSHOT_DOWNLOAD_TIMEOUT_SECONDS", "30")
)
AGENT_LLM_BASE_URL = os.getenv("AGENT_LLM_BASE_URL", "")
AGENT_LLM_API_KEY = os.getenv("AGENT_LLM_API_KEY", "") or os.getenv("EZVIZ_API_KEY", "")
AGENT_LLM_MODEL = os.getenv("AGENT_LLM_MODEL", "")
AGENT_LLM_TIMEOUT_SECONDS = float(os.getenv("AGENT_LLM_TIMEOUT_SECONDS", "30"))
AGENT_LLM_MAX_OUTPUT_TOKENS = int(os.getenv("AGENT_LLM_MAX_OUTPUT_TOKENS", "400"))
YINGMU_SCENE_CONFIG_ID = os.getenv("YINGMU_SCENE_CONFIG_ID", "scene-living-room-v1")
YINGMU_LOCATION = os.getenv("YINGMU_LOCATION", "living_room")
YINGMU_ALGORITHM_TIMEOUT_SECONDS = float(
    os.getenv("YINGMU_ALGORITHM_TIMEOUT_SECONDS", "90")
)
EZVIZ_WEBHOOK_SECRET = os.getenv("EZVIZ_WEBHOOK_SECRET", "")
EZVIZ_WEBHOOK_MAX_AGE_SECONDS = int(os.getenv("EZVIZ_WEBHOOK_MAX_AGE_SECONDS", "300"))
EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST = (
    os.getenv("EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST", "false").lower() == "true"
)
CONTROL_TOKEN = os.getenv("YINGMU_CONTROL_TOKEN", "")

TOKEN_REFRESH_OFFSET = 60
_RULESET = load_ruleset()
RULESET_VERSION = _RULESET.version
SCHEMA_VERSION = "1.0"
# Risk thresholds have one source of truth: ruleset-v1.0.json. Environment
# overrides previously let FastAPI and the agent assign different meanings.
MIN_EVIDENCE_QUALITY = _RULESET.thresholds["data_quality"]
MIN_EVIDENCE_CONFIDENCE = _RULESET.thresholds["confidence"]

if ENV_MODE == "live" and (not EZVIZ_APP_KEY or not EZVIZ_APP_SECRET or not EZVIZ_DEVICE_SERIAL):
    raise RuntimeError("live mode requires EZVIZ_APP_KEY, EZVIZ_APP_SECRET and EZVIZ_DEVICE_SERIAL")

if EZVIZ_CAPTURE_TIMEOUT_SECONDS <= 0:
    raise RuntimeError("EZVIZ_CAPTURE_TIMEOUT_SECONDS must be positive")
if YINGMU_SNAPSHOT_MAX_BYTES <= 0:
    raise RuntimeError("YINGMU_SNAPSHOT_MAX_BYTES must be positive")
if YINGMU_SNAPSHOT_DOWNLOAD_TIMEOUT_SECONDS <= 0:
    raise RuntimeError("YINGMU_SNAPSHOT_DOWNLOAD_TIMEOUT_SECONDS must be positive")
if AGENT_LLM_TIMEOUT_SECONDS <= 0:
    raise RuntimeError("AGENT_LLM_TIMEOUT_SECONDS must be positive")
if AGENT_LLM_MAX_OUTPUT_TOKENS <= 0:
    raise RuntimeError("AGENT_LLM_MAX_OUTPUT_TOKENS must be positive")
if not 0.1 <= YINGMU_ALGORITHM_TIMEOUT_SECONDS <= 120:
    raise RuntimeError("YINGMU_ALGORITHM_TIMEOUT_SECONDS must be between 0.1 and 120")
