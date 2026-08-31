import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from backend.db.database import Base


class SceneCalibrationRecord(Base):
    __tablename__ = "scene_calibration"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scene_config_id = Column(String(128), unique=True, nullable=False, index=True)
    calibration_payload = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.now, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
        nullable=False,
    )
