from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from backend.db.database import Base


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AgentExplanationJob(Base):
    """Durable, versioned request to the non-safety-critical explanation worker."""

    __tablename__ = "agent_explanation_job"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    request_id = Column(String(128), unique=True, nullable=False, index=True)
    event_id = Column(
        String(128), ForeignKey("risk_event.event_id"), nullable=False, index=True
    )
    event_version_hash = Column(String(64), nullable=False, index=True)
    request_payload = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="PENDING", index=True)
    response_payload = Column(Text, nullable=True)
    generated_by = Column(String(64), nullable=True)
    fallback_used = Column(Boolean, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    available_at = Column(DateTime, nullable=False, default=utcnow_naive)
    lease_until = Column(DateTime, nullable=True)
    error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(
        DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive
    )
    completed_at = Column(DateTime, nullable=True)
