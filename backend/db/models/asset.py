import datetime

from sqlalchemy import Boolean, Column, DateTime, String, Text

from backend.db.database import Base


class Asset(Base):
    __tablename__ = "asset"

    asset_id = Column(String(128), primary_key=True)
    title = Column(String(256), nullable=False)
    source_mode = Column(String(32), nullable=False)
    simulated = Column(Boolean, nullable=False)
    stream_url = Column(Text, nullable=True)
    fallback_url = Column(Text, nullable=True)
    fallback_kind = Column(String(64), nullable=False)
    available = Column(Boolean, nullable=False, default=False)
    verification_status = Column(String(64), nullable=False)
    captured_at = Column(DateTime, nullable=False)
    notice = Column(Text, nullable=False)
    device_ref = Column(String(128), nullable=True, index=True)
    device_model = Column(String(64), nullable=True)
    camera_position_id = Column(String(128), nullable=True, index=True)
    authorization_status = Column(String(32), nullable=False, default="PENDING")
    authorization_record_id = Column(String(128), nullable=True)
    retention_until = Column(DateTime, nullable=True)
    create_time = Column(DateTime, default=datetime.datetime.now, nullable=False)
