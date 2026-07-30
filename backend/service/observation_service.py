from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Observation
from backend.schemas.observation import ObservationCreate
from backend.service.errors import ServiceError
from backend.service.serialization import dumps, observation_dict


async def create_observation(db: AsyncSession, payload: ObservationCreate):
    existing = (await db.execute(select(Observation).where(
        Observation.observation_id == payload.observation_id))).scalar_one_or_none()
    normalized = payload.model_dump(mode="json")
    if existing:
        if dumps(observation_dict(existing) | {"timestamp": observation_dict(existing)["timestamp"].isoformat()}) != dumps(normalized):
            raise ServiceError(409, "OBSERVATION_ID_CONFLICT", "observation_id exists with different content")
        return observation_dict(existing), False, True
    row = Observation(**payload.model_dump(exclude={"metadata", "feature_value"}),
                      feature_value=dumps(payload.feature_value),
                      extra_metadata=dumps(payload.metadata) if payload.metadata is not None else None,
                      device_sn="camera-internal-mock")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return observation_dict(row), True, False
