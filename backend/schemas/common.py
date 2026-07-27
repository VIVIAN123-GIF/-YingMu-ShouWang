from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import AfterValidator, Field


class RiskDomain(str, Enum):
    FALL = "FALL"
    MENTAL = "MENTAL"
    FRAUD = "FRAUD"
    SYSTEM = "SYSTEM"


class RiskLevel(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    INTERVENING = "INTERVENING"
    OBSERVING = "OBSERVING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    FALSE_ALARM = "FALSE_ALARM"


class SourceMode(str, Enum):
    LIVE_DEVICE = "LIVE_DEVICE"
    RECORDED_REPLAY = "RECORDED_REPLAY"
    PUBLIC_DATASET = "PUBLIC_DATASET"
    MOCK = "MOCK"


def timezone_required(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include timezone offset")
    return value


TimezoneDatetime = Annotated[datetime, AfterValidator(timezone_required)]
Score = Annotated[float, Field(ge=0.0, le=1.0)]
