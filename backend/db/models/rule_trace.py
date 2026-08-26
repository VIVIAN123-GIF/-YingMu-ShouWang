import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from backend.db.database import Base


class RuleTrace(Base):
    __tablename__ = "rule_trace"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(128), unique=True, nullable=False, index=True)
    event_id = Column(String(128), nullable=True, index=True)
    resident_id = Column(String(128), nullable=False, index=True)
    evidence_id = Column(String(128), nullable=True, index=True)
    evaluated_at = Column(DateTime, nullable=False)
    ruleset_version = Column(String(64), nullable=False, default="ruleset-v1.2")
    matched_rule = Column(String(64), nullable=False)
    previous_state = Column(String(16), nullable=False)
    next_state = Column(String(16), nullable=False)
    previous_status = Column(String(16), nullable=True)
    next_status = Column(String(16), nullable=True)
    event_created = Column(Boolean, nullable=False, default=False)
    error = Column(Text, nullable=True)
    trace_payload = Column(Text, nullable=True, comment="完整规则输入、上下文、评分和解释JSON")
    create_time = Column(DateTime, default=datetime.datetime.now, nullable=False)
