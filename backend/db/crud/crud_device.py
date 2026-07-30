from backend.db.crud.base import CRUDBase
from backend.db.models.device import DeviceInfo
from pydantic import BaseModel

class DeviceCreate(BaseModel):
    resident_id: str
    device_sn: str
    channel_no: int
    device_name: str

class DeviceUpdate(BaseModel):
    is_online: bool | None = None
    rtsp_url: str | None = None
    flv_url: str | None = None
    adapter_mode: str | None = None

crud_device = CRUDBase[DeviceInfo, DeviceCreate, DeviceUpdate](DeviceInfo)