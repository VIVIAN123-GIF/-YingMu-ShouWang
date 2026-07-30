from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from backend.db.database import Base
import datetime


class RiskEventEvidence(Base):
    __tablename__ = "risk_event_evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(
        String(128),
        ForeignKey("risk_event.event_id"),
        nullable=False,
        index=True,
    )
    evidence_id = Column(
        String(128),
        ForeignKey("evidence.evidence_id"),
        nullable=False,
        index=True,
    )
    create_time = Column(DateTime, default=datetime.datetime.now, nullable=False)

    __table_args__ = (
        UniqueConstraint("event_id", "evidence_id", name="uq_risk_event_evidence"),
    )