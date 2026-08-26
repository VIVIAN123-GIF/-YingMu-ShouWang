from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime
from backend.db.database import Base
import datetime

class SystemConfig(Base):
    __tablename__ = "system_config"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    config_key = Column(String(64), unique=True, nullable=False, index=True)
    config_value = Column(Text, nullable=True)
    desc = Column(String(256), nullable=True)
    intervention_retry_times = Column(Integer, default=1)
    stream_max_channel = Column(Integer, default=2)
    auto_analysis_switch = Column(Boolean, default=True)
    ruleset_version = Column(String(64), default="ruleset-v1.2")
    update_time = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now, nullable=False)

class WeeklyStat(Base):
    __tablename__ = "weekly_stat"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    resident_id = Column(String(128), nullable=False, index=True)
    week_start = Column(DateTime, nullable=False, index=True)
    week_end = Column(DateTime, nullable=False)
    total_event_count = Column(Integer, default=0, nullable=False)
    fall_orange_count = Column(Integer, default=0)
    mental_yellow_count = Column(Integer, default=0)
    fraud_orange_count = Column(Integer, default=0)
    avg_risk_score = Column(Float, default=0.0)
    avg_online_device = Column(Integer, default=0)
    create_time = Column(DateTime, default=datetime.datetime.now, nullable=False)
