from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, Enum
from sqlalchemy.orm import relationship
from backend.db.database import Base
import datetime

# 冻结输入来源枚举
SourceModeEnum = Enum("LIVE_DEVICE", "RECORDED_REPLAY", "PUBLIC_DATASET", "MOCK")

class DeviceInfo(Base):
    __tablename__ = "device_info"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    resident_id = Column(String(128), nullable=False, index=True, comment="唯一老人档案ID")
    device_sn = Column(String(100), unique=True, nullable=False, index=True, comment="萤石C6c序列号")
    channel_no = Column(Integer, nullable=False, default=1, comment="设备固定通道1")
    device_name = Column(String(128), nullable=False)
    is_online = Column(Boolean, default=False, comment="设备在线状态")
    rtsp_url = Column(Text, nullable=True)
    flv_url = Column(Text, nullable=True)
    adapter_mode = Column(SourceModeEnum, default="MOCK", nullable=False, comment="DeviceAdapter链路模式")
    stream_max_channel = Column(Integer, default=2, comment="最大并发拉流，读取配置")
    create_time = Column(DateTime, default=datetime.datetime.now, nullable=False)
    update_time = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now, nullable=False)

    # 关联观测、原始告警
    obs_list = relationship("Observation", back_populates="device")
    alarm_raw_list = relationship("RiskAlarm", back_populates="device")