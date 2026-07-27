import json
import logging

logger = logging.getLogger("risk_rule")


def log_rule(payload: dict) -> None:
    forbidden = {"accessToken", "access_token", "appSecret", "app_secret", "password", "device_sn",
                 "family_ip", "stream_url", "playback_url"}
    safe = {key: ("***" if key in forbidden else value) for key, value in payload.items()}
    logger.info(json.dumps(safe, ensure_ascii=False, default=str))
