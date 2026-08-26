import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from backend.db.database import Base


class ForewarningSnapshot(Base):
    __tablename__ = "forewarning_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(String(160), unique=True, nullable=False, index=True)
    resident_id = Column(String(128), nullable=False, index=True)
    evaluated_at = Column(DateTime, nullable=False, index=True)
    phase = Column(String(32), nullable=False, default="PERIODIC")
    assessment_status = Column(String(32), nullable=False)
    confidence_level = Column(String(16), nullable=False)
    baseline_status = Column(String(16), nullable=False)
    instant_index = Column(Float, nullable=False)
    short_30s_index = Column(Float, nullable=False)
    trend_3min_index = Column(Float, nullable=False)
    components_payload = Column(Text, nullable=False)
    factors_payload = Column(Text, nullable=False)
    degradation_payload = Column(Text, nullable=False)
    evidence_ids = Column(Text, nullable=False)
    observation_ids = Column(Text, nullable=False)
    scene_config_id = Column(String(128), nullable=True, index=True)
    event_id = Column(String(128), nullable=True, index=True)
    intervention_result_id = Column(String(128), nullable=True, index=True)
    recommended_action = Column(Text, nullable=False)
    ruleset_version = Column(String(64), nullable=False)
    source_mode = Column(String(32), nullable=False)
    simulated = Column(Boolean, nullable=False)
    create_time = Column(DateTime, default=datetime.datetime.now, nullable=False)
