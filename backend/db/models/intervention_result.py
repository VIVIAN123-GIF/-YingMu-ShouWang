from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from backend.db.database import Base
import datetime

DeliveryStatusEnum = Enum("SUCCESS", "FAILED", "RETRYING")

class InterventionResult(Base):
    __tablename__ = "intervention_result"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    schema_version = Column(String(16), default="1.0", nullable=False)
    result_id = Column(String(128), unique=True, nullable=False, index=True)
    event_id = Column(String(128), ForeignKey("risk_event.event_id"), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    action_type = Column(String(64), nullable=False, comment="voice/push/family_call")
    tool_name = Column(String(64), nullable=False, comment="ezviz_voice/ezviz_push")
    delivery_status = Column(DeliveryStatusEnum, nullable=False)
    resident_response = Column(String(64), nullable=True)
    family_feedback = Column(String(64), nullable=True)
    risk_after = Column(Float, nullable=True)
    resolved = Column(Boolean, nullable=False, default=False)
    resolution_reason = Column(Text, nullable=True)
    operator = Column(String(32), nullable=False, default="system")
    create_time = Column(DateTime, default=datetime.datetime.now, nullable=False)

    event_rel = relationship("RiskEvent", back_populates="intervention_list")