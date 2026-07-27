import statistics
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import RULESET_VERSION
from backend.db.models import Observation
from backend.service.serialization import aware, loads


class MemoryStore:
    async def baseline(self, db: AsyncSession, resident_id: str, as_of):
        rows = (await db.execute(select(Observation).where(
            Observation.resident_id == resident_id, Observation.timestamp <= as_of
        ))).scalars().all()
        values = defaultdict(list)
        days = defaultdict(set)
        for row in rows:
            try:
                value = float(loads(row.feature_value, row.feature_value))
            except (TypeError, ValueError):
                continue
            values[row.feature_name].append(value)
            days[row.feature_name].add(aware(row.timestamp).date())
        result = {}
        for name, samples in values.items():
            median = statistics.median(samples)
            mad = statistics.median([abs(v - median) for v in samples])
            count, distinct = len(samples), len(days[name])
            status = "STABLE" if count >= 7 and distinct >= 7 else "BUILDING" if count >= 3 else "INSUFFICIENT"
            result[name] = {"median": median, "mad": mad, "sample_count": count,
                            "distinct_days": distinct, "status": status}
        source_mode = rows[-1].source_mode if rows else "MOCK"
        simulated = all(row.simulated for row in rows) if rows else True
        return {"resident_id": resident_id, "as_of": as_of, "ruleset_version": RULESET_VERSION,
                "baselines": result, "source_mode": source_mode, "simulated": simulated}


memory_store = MemoryStore()
