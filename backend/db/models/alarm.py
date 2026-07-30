from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from backend.db.database import Base
import datetime

class RiskAlarm(Base):
    __tablename__ = "risk_alarm"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    alarm_msg_id = Column(String(128), unique=True, nullable=False, index=True, comment="萤石原始告警ID去重")
    resident_id = Column(String(128), nullable=False, index=True)
    device_sn = Column(String(100), ForeignKey("device_info.device_sn"), nullable=False, index=True)
    alarm_source = Column(String(64), nullable=False, default="ezviz_cloud")
    alarm_type = Column(String(64), nullable=False)
    capture_img_path = Column(Text, nullable=True)
    alarm_time = Column(DateTime, nullable=False)
    raw_callback_json = Column(Text, nullable=False, comment="完整原始回调报文用于溯源")
    create_time = Column(DateTime, default=datetime.datetime.now, nullable=False)

    device = relationship("DeviceInfo", back_populates="alarm_raw_list")