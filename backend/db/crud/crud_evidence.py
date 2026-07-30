from backend.db.crud.base import CRUDBase
from backend.db.models.evidence import Evidence
from pydantic import BaseModel
import datetime

class EvidenceCreate(BaseModel):
    schema_version: str = "1.0"
    evidence_id: str
    resident_id: str
    timestamp: datetime.datetime
    risk_domain: str
    evidence_type: str
    severity: float
    confidence: float
    data_quality: float
    baseline_value: float | None
    current_value: float | None
    baseline_deviation: float | None
    time_scale: str
    location: str | None
    explanation: str
    adapter_version: str
    source_mode: str
    simulated: bool
    observation_ids: str

class EvidenceUpdate(BaseModel):
    pass

crud_evidence = CRUDBase[Evidence, EvidenceCreate, EvidenceUpdate](Evidence)