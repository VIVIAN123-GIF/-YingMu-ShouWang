import statistics
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import RULESET_VERSION
from backend.db.models import Evidence, Observation, RiskEvent
from backend.service.serialization import aware, loads
from contracts.v1.memory import MemoryStore
from contracts.v1.models import Evidence as ContractEvidence
from contracts.v1.models import Observation as ContractObservation
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
        events = (await db.execute(
            select(RiskEvent).where(
                RiskEvent.resident_id == resident_id,
                RiskEvent.created_at <= as_of,
            )
        )).scalars().all()

        values = defaultdict(list)
        days = defaultdict(set)
        accepted = []
        memory = MemoryStore(self.ruleset)
        all_evidences = (await db.execute(
            select(Evidence)
            .where(
                Evidence.resident_id == resident_id,
                Evidence.timestamp >= as_of - timedelta(minutes=3),
                Evidence.timestamp <= as_of,
            )
            .order_by(Evidence.timestamp)
        )).scalars().all()
        all_observation_ids = {
            observation_id
            for evidence in all_evidences
            for observation_id in loads(evidence.observation_ids, [])
        } | observation_ids
        all_observations = (await db.execute(
            select(Observation).where(Observation.observation_id.in_(all_observation_ids))
        )).scalars().all() if all_observation_ids else []
        all_observation_by_id = {
            observation.observation_id: observation
            for observation in all_observations
        }
        for observation in all_observations:
            memory.add_observation(ContractObservation.model_validate({
                "schema_version": observation.schema_version,
                "observation_id": observation.observation_id,
                "resident_id": observation.resident_id,
                "timestamp": aware(observation.timestamp),
                "source": observation.source,
                "feature_name": observation.feature_name,
                "feature_value": observation.feature_value,
                "unit": observation.unit,
                "location": observation.location,
                "confidence": observation.confidence,
                "data_quality": observation.data_quality,
                "source_mode": observation.source_mode,
                "asset_id": observation.asset_id,
                "simulated": observation.simulated,
                "metadata": loads(observation.extra_metadata, {}),
            }))
        for evidence in all_evidences:
            memory.add_evidence(ContractEvidence.model_validate({
                "schema_version": evidence.schema_version,
                "evidence_id": evidence.evidence_id,
                "observation_ids": loads(evidence.observation_ids, []),
                "resident_id": evidence.resident_id,
                "timestamp": aware(evidence.timestamp),
                "risk_domain": evidence.risk_domain,
                "evidence_type": evidence.evidence_type,
                "severity": evidence.severity,
                "confidence": evidence.confidence,
                "data_quality": evidence.data_quality,
                "baseline_value": evidence.baseline_value,
                "current_value": evidence.current_value,
                "baseline_deviation": evidence.baseline_deviation,
                "time_scale": evidence.time_scale,
                "location": evidence.location,
                "explanation": evidence.explanation,
                "adapter_version": evidence.adapter_version,
                "source_mode": evidence.source_mode,
                "simulated": evidence.simulated,
            }))

        for evidence in evidences:
            timestamp = aware(evidence.timestamp)
            if any(self._event_blocks_sample(event, timestamp) for event in events):
                continue
            linked = [
                all_observation_by_id[observation_id]
                for observation_id in loads(evidence.observation_ids, [])
                if observation_id in all_observation_by_id
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
            "pre_fall_summary": memory.forewarning_profile(resident_id, as_of),
            "source_mode": source_mode,
            "simulated": simulated,
        }


memory_store = BaselineStore()
