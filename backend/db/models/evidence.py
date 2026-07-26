from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, Enum
from sqlalchemy.orm import relationship
from backend.db.database import Base
import datetime

RiskDomainEnum = Enum("FALL", "MENTAL", "FRAUD", "SYSTEM")
SourceModeEnum = Enum("LIVE_DEVICE", "RECORDED_REPLAY", "PUBLIC_DATASET", "MOCK")


class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    schema_version = Column(String(16), default="1.0", nullable=False)
    evidence_id = Column(String(128), unique=True, nullable=False, index=True)
    resident_id = Column(String(128), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False)
    risk_domain = Column(RiskDomainEnum, nullable=False)
    evidence_type = Column(String(128), nullable=False, comment="rapid_rise/trunk_sway等规范特征")
    severity = Column(Float, nullable=False, comment="0~1异常程度")
    confidence = Column(Float, nullable=False)
    data_quality = Column(Float, nullable=False)
    baseline_value = Column(Float, nullable=True)
    current_value = Column(Float, nullable=True)
    baseline_deviation = Column(Float, nullable=True)
    time_scale = Column(String(16), nullable=False, comment="SHORT/MEDIUM/LONG")
    location = Column(String(32), nullable=True)
    explanation = Column(Text, nullable=False)
    adapter_version = Column(String(64), nullable=False)
    source_mode = Column(SourceModeEnum, nullable=False)
    simulated = Column(Boolean, nullable=False)
    observation_ids = Column(
        Text,
        nullable=True,
        comment="兼容字段：逗号分隔观测ID快照；建议以关系表为准",
    )
    create_time = Column(DateTime, default=datetime.datetime.now, nullable=False)

    risk_events = relationship(
        "RiskEvent",
        secondary="risk_event_evidence",
        back_populates="evidences",
        lazy="selectin",
    )