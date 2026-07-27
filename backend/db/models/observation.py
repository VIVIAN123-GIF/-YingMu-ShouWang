from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from backend.db.database import Base
import datetime

SourceModeEnum = Enum("LIVE_DEVICE", "RECORDED_REPLAY", "PUBLIC_DATASET", "MOCK")


class Observation(Base):
    __tablename__ = "observation"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    schema_version = Column(String(16), default="1.0", nullable=False, comment="固定v1.0")
    observation_id = Column(String(128), unique=True, nullable=False, index=True)
    resident_id = Column(String(128), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, comment="ISO 8601带时区存储")
    source = Column(String(64), nullable=False, comment="pose/tracking/audio/environment")
    feature_name = Column(String(128), nullable=False)
    feature_value = Column(Text, nullable=False, comment="数值/字符串统一存文本")
    unit = Column(String(32), nullable=True)
    location = Column(String(32), nullable=True, comment="bedroom/living_room/corridor")
    confidence = Column(Float, nullable=False, comment="0~1")
    data_quality = Column(Float, nullable=False, comment="0~1")
    source_mode = Column(SourceModeEnum, nullable=False)
    asset_id = Column(String(128), nullable=True, comment="音视频资源标识")
    simulated = Column(Boolean, nullable=False, default=False)
    extra_metadata = Column("metadata", Text, nullable=True, comment="JSON存储model_version")
    device_sn = Column(
        String(100),
        ForeignKey("device_info.device_sn"),
        nullable=True,
        index=True,
    )
    create_time = Column(DateTime, default=datetime.datetime.now, nullable=False)

    device = relationship("DeviceInfo", back_populates="obs_list", lazy="selectin")
