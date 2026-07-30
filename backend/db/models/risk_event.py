from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, Enum
from sqlalchemy.orm import relationship
from backend.db.database import Base
import datetime

RiskDomainEnum = Enum("FALL", "MENTAL", "FRAUD", "SYSTEM")
RiskLevelEnum = Enum("GREEN", "YELLOW", "ORANGE", "RED")
EventStatusEnum = Enum("OPEN", "INTERVENING", "OBSERVING", "RESOLVED", "ESCALATED", "FALSE_ALARM")


class RiskEvent(Base):
    __tablename__ = "risk_event"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    schema_version = Column(String(16), default="1.0", nullable=False)
    event_id = Column(String(128), unique=True, nullable=False, index=True)
    resident_id = Column(String(128), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    primary_domain = Column(RiskDomainEnum, nullable=False)
    related_domains = Column(Text, nullable=False, comment="JSON数组")
    risk_level = Column(RiskLevelEnum, nullable=False)
    risk_score = Column(Float, nullable=False, comment="0~1综合风险分")
    evidence_ids = Column(
        Text,
        nullable=True,
        comment="JSON数组格式的证据ID快照",
    )
    evidence_summary = Column(Text, nullable=False)
    time_horizon = Column(String(32), nullable=False, comment="TREND/TODAY/IMMINENT")
    recommended_action = Column(Text, nullable=False)
    intervention_policy = Column(String(128), nullable=False)
    status = Column(EventStatusEnum, nullable=False, default="OPEN")
    ruleset_version = Column(String(64), nullable=False, default="ruleset-v1.0")
    source_mode = Column(String(32), nullable=False, default="MOCK")
    simulated = Column(Boolean, nullable=False, default=True)
    create_time = Column(DateTime, default=datetime.datetime.now, nullable=False)

    evidences = relationship(
        "Evidence",
        secondary="risk_event_evidence",
        back_populates="risk_events",
        lazy="selectin",
    )
    intervention_list = relationship("InterventionResult", back_populates="event_rel")
