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

TOKEN_REFRESH_OFFSET = 60
_RULESET = load_ruleset()
RULESET_VERSION = _RULESET.version
SCHEMA_VERSION = "1.0"
MIN_EVIDENCE_QUALITY = float(
    os.getenv("MIN_EVIDENCE_QUALITY", str(_RULESET.thresholds["data_quality"]))
)
MIN_EVIDENCE_CONFIDENCE = float(
    os.getenv("MIN_EVIDENCE_CONFIDENCE", str(_RULESET.thresholds["confidence"]))
)

if ENV_MODE == "live" and (not EZVIZ_APP_KEY or not EZVIZ_APP_SECRET or not EZVIZ_DEVICE_SERIAL):
    raise RuntimeError("live mode requires EZVIZ_APP_KEY, EZVIZ_APP_SECRET and EZVIZ_DEVICE_SERIAL")
