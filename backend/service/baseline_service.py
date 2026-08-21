import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import RULESET_VERSION
from backend.db.models import Asset, Evidence, Observation, RiskEvent
from backend.service.serialization import aware, loads
from contracts.v1.memory import MemoryStore
from contracts.v1.models import Evidence as ContractEvidence
from contracts.v1.models import Observation as ContractObservation
from contracts.v1.ruleset import load_ruleset


EXPECTED_METRICS = ("rise_duration", "relative_gait_speed", "stable_trunk_angle_deg")
STATUS_ORDER = {"INSUFFICIENT": 0, "PROVISIONAL": 1, "STABLE": 2}


@dataclass(frozen=True)
class Candidate:
    evidence: Evidence
    observation: Observation
    asset: Asset
    metric: str
    value: float


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

    @staticmethod
    def _provenance_key(candidate: Candidate) -> tuple[str, str]:
        return candidate.asset.device_ref, candidate.asset.camera_position_id

    @staticmethod
    def _rank_cohort(items: list[Candidate]) -> tuple:
        days = defaultdict(set)
        for item in items:
            days[item.metric].add(aware(item.evidence.timestamp).date())
        counts = [len(days[metric]) for metric in EXPECTED_METRICS]
        newest = max(aware(item.evidence.timestamp) for item in items)
        return (sum(count >= 3 for count in counts), min(counts), sum(counts), len(items), newest)

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
                Evidence.source_mode == "RECORDED_REPLAY",
                Evidence.simulated.is_(True),
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
        observation_by_id = {item.observation_id: item for item in observations}
        asset_ids = {item.asset_id for item in observations if item.asset_id}
        assets = (await db.execute(select(Asset).where(Asset.asset_id.in_(asset_ids)))).scalars().all() if asset_ids else []
        asset_by_id = {item.asset_id: item for item in assets}
        events = (await db.execute(
            select(RiskEvent).where(
                RiskEvent.resident_id == resident_id,
                RiskEvent.created_at <= as_of,
            )
        )).scalars().all()

        candidates: list[Candidate] = []
        memory = MemoryStore(self.ruleset)
        recent_evidences = (await db.execute(
            select(Evidence)
            .where(
                Evidence.resident_id == resident_id,
                Evidence.timestamp >= as_of - timedelta(minutes=3),
                Evidence.timestamp <= as_of,
            )
            .order_by(Evidence.timestamp)
        )).scalars().all()
        recent_observation_ids = {
            observation_id
            for evidence in recent_evidences
            for observation_id in loads(evidence.observation_ids, [])
        }
        recent_observations = (await db.execute(
            select(Observation).where(Observation.observation_id.in_(recent_observation_ids))
        )).scalars().all() if recent_observation_ids else []
        for observation in recent_observations:
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
        for evidence in recent_evidences:
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
                observation_by_id[item]
                for item in loads(evidence.observation_ids, [])
                if item in observation_by_id
            ]
            mapped = [item for item in linked if item.feature_name in MemoryStore.METRIC_BY_FEATURE]
            if len(mapped) != 1 or evidence.current_value is None:
                continue
            observation = mapped[0]
            metric = MemoryStore.METRIC_BY_FEATURE[observation.feature_name]
            if metric not in EXPECTED_METRICS or observation.data_quality < self.ruleset.thresholds["data_quality"]:
                continue
            asset = asset_by_id.get(observation.asset_id)
            if not asset or not asset.device_ref or not asset.camera_position_id:
                continue
            if (
                asset.device_model != "EZVIZ_C6C"
                or asset.authorization_status != "AUTHORIZED"
                or not asset.authorization_record_id
                or not asset.retention_until
                or asset.source_mode != "RECORDED_REPLAY"
                or not asset.simulated
                or aware(asset.retention_until) < as_of
            ):
                continue
            candidates.append(Candidate(evidence, observation, asset, metric, float(evidence.current_value)))

        cohorts = defaultdict(list)
        for candidate in candidates:
            cohorts[self._provenance_key(candidate)].append(candidate)
        selected = max(cohorts.values(), key=self._rank_cohort) if cohorts else []

        values = defaultdict(list)
        days = defaultdict(set)
        for candidate in selected:
            values[candidate.metric].append(candidate.value)
            days[candidate.metric].add(aware(candidate.evidence.timestamp).date())

        result = {}
        for metric in EXPECTED_METRICS:
            samples = values[metric]
            distinct_days = len(days[metric])
            if samples:
                center = statistics.median(samples)
                mad = statistics.median(abs(value - center) for value in samples)
            else:
                center = mad = None
            status = "STABLE" if distinct_days >= self.ruleset.windows["long_days"] else (
                "PROVISIONAL" if distinct_days >= 3 else "INSUFFICIENT"
            )
            result[metric] = {
                "median": center,
                "mad": mad,
                "sample_count": len(samples),
                "distinct_days": distinct_days,
                "status": status,
            }

        overall_status = min((item["status"] for item in result.values()), key=STATUS_ORDER.get)
        observed_days = min(item["distinct_days"] for item in result.values())
        provenance = None
        if selected:
            asset = selected[0].asset
            provenance = {
                "device_ref": asset.device_ref,
                "device_model": asset.device_model,
                "camera_position_id": asset.camera_position_id,
            }
        return {
            "resident_id": resident_id,
            "as_of": as_of,
            "ruleset_version": RULESET_VERSION,
            "baselines": result,
            "overall_status": overall_status,
            "baseline_progress": {
                "observed_days": observed_days,
                "provisional_target_days": 3,
                "stable_target_days": self.ruleset.windows["long_days"],
            },
            "provenance": provenance,
            "pre_fall_summary": memory.forewarning_profile(resident_id, as_of),
            "source_mode": "RECORDED_REPLAY",
            "simulated": True,
        }


memory_store = BaselineStore()
