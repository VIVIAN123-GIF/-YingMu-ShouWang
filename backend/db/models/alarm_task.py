from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from backend.db.database import Base


def utcnow_naive() -> datetime:
    """Match the project's existing SQLite DATETIME convention without utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AlarmProcessingTask(Base):
    """Durable hand-off from a fast Ezviz callback to slower processing work."""

    __tablename__ = "alarm_processing_task"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    task_id = Column(String(160), unique=True, nullable=False, index=True)
    alarm_msg_id = Column(
        String(128),
        ForeignKey("risk_alarm.alarm_msg_id"),
        unique=True,
        nullable=False,
        index=True,
    )
    resident_id = Column(String(128), nullable=False, index=True)
    device_sn = Column(String(100), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    capture_asset_id = Column(String(160), nullable=True)
    capture_completed_at = Column(DateTime, nullable=True)
    algorithm_attempt_count = Column(Integer, nullable=False, default=0)
    algorithm_started_at = Column(DateTime, nullable=True)
    algorithm_completed_at = Column(DateTime, nullable=True)
    algorithm_summary = Column(Text, nullable=True)
    error_stage = Column(String(32), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(String(256), nullable=True)
    available_at = Column(DateTime, nullable=False, default=utcnow_naive)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    create_time = Column(DateTime, nullable=False, default=utcnow_naive)
    update_time = Column(
        DateTime,
        nullable=False,
        default=utcnow_naive,
        onupdate=utcnow_naive,
    )
