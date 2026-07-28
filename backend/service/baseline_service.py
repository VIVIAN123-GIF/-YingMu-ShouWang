import statistics
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import RULESET_VERSION
from backend.db.models import Evidence, Observation, RiskEvent
from backend.service.serialization import aware, loads
from contracts.v1.memory import MemoryStore
from contracts.v1.ruleset import load_ruleset


class BaselineStore:
    def __init__(self):
        self.ruleset = load_ruleset()

    @staticmethod
    def _event_blocks_sample(event: RiskEvent, timestamp) -> bool:
        created_at = aware(event.created_at)
        updated_at = aware(event.updated_at)
        if timestamp < created_at:
            return False
        if event.status in {"OPEN", "INTERVENING", "OBSERVING", "ESCALATED"}:
            return True
        return timestamp <= updated_at

    async def baseline(self, db: AsyncSession, resident_id: str, as_of):
        cutoff = as_of - timedelta(days=self.ruleset.windows["long_days"])
        evidences = (await db.execute(
            select(Evidence)
            .where(
                Evidence.resident_id == resident_id,
                Evidence.timestamp >= cutoff,
                Evidence.timestamp <= as_of,
                Evidence.evidence_type.in_(MemoryStore.SAFE_BASELINE_TYPES),
                Evidence.confidence >= self.ruleset.thresholds["confidence"],
                Evidence.data_quality >= self.ruleset.thresholds["data_quality"],
            )
            .order_by(Evidence.timestamp)
        )).scalars().all()
        observation_ids = {
            observation_id
            for evidence in evidences
            for observation_id in loads(evidence.observation_ids, [])
        }
        observations = (await db.execute(
            select(Observation).where(Observation.observation_id.in_(observation_ids))
        )).scalars().all() if observation_ids else []
        observation_by_id = {
            observation.observation_id: observation
            for observation in observations
        }
        events = (await db.execute(
            select(RiskEvent).where(
                RiskEvent.resident_id == resident_id,
                RiskEvent.created_at <= as_of,
            )
        )).scalars().all()

        values = defaultdict(list)
        days = defaultdict(set)
        accepted = []
        for evidence in evidences:
            timestamp = aware(evidence.timestamp)
            if any(self._event_blocks_sample(event, timestamp) for event in events):
                continue
            linked = [
                observation_by_id[observation_id]
                for observation_id in loads(evidence.observation_ids, [])
                if observation_id in observation_by_id
            ]
            observation = next(
                (
                    item for item in linked
                    if item.feature_name in MemoryStore.METRIC_BY_FEATURE
                    and item.feature_name not in MemoryStore.QUALITY_FLAGS
                    and item.data_quality >= self.ruleset.thresholds["data_quality"]
                ),
                None,
            )
            if observation is None or evidence.current_value is None:
                continue
            metric = MemoryStore.METRIC_BY_FEATURE[observation.feature_name]
            values[metric].append(float(evidence.current_value))
            days[metric].add(timestamp.date())
            accepted.append(evidence)

        result = {}
        for metric, samples in values.items():
            center = statistics.median(samples)
            mad = statistics.median(abs(value - center) for value in samples)
            distinct_days = len(days[metric])
            if distinct_days >= self.ruleset.windows["long_days"]:
                status = "STABLE"
            elif distinct_days >= 3:
                status = "PROVISIONAL"
            else:
                status = "INSUFFICIENT"
            result[metric] = {
                "median": center,
                "mad": mad,
                "sample_count": len(samples),
                "distinct_days": distinct_days,
                "status": status,
            }

        source_mode = accepted[-1].source_mode if accepted else "MOCK"
        simulated = all(item.simulated for item in accepted) if accepted else True
        return {
            "resident_id": resident_id,
            "as_of": as_of,
            "ruleset_version": RULESET_VERSION,
            "baselines": result,
            "source_mode": source_mode,
            "simulated": simulated,
        }


memory_store = BaselineStore()
