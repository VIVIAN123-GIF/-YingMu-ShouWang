from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import RiskEvent
from backend.service.serialization import aware, loads


async def weekly_report(db: AsyncSession, resident_id: str):
    now = datetime.now(timezone(timedelta(hours=8)))
    start = now - timedelta(days=7)
    rows = (await db.execute(select(RiskEvent).where(
        RiskEvent.resident_id == resident_id, RiskEvent.created_at >= start,
        RiskEvent.created_at <= now
    ).order_by(RiskEvent.created_at.desc()))).scalars().all()
    order = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}
    level = max((row.risk_level for row in rows), key=lambda item: order[item], default="GREEN")
    source_mode = rows[0].source_mode if rows else "MOCK"
    simulated = all(row.simulated for row in rows) if rows else True
    evidence = [summary for row in rows for summary in loads(row.evidence_summary, [])]
    return {"resident_id": resident_id,
            "period": f"{start.date().isoformat()} 至 {now.date().isoformat()}",
            "generated_at": now, "risk_level": level, "source_mode": source_mode,
            "simulated": simulated,
            "summary": "本周风险事件汇总；结论仅用于关怀与复核，不构成医疗诊断。",
            "trend": [],
            "evidence": [{"label": item["evidence_type"], "detail": item["explanation"],
                          "confidence": None} for item in evidence],
            "recommendations": ["结合事件证据与本人反馈进行温和联系。"],
            "care": {"status": "PENDING", "last_contact": None, "options": []},
            "visitor_case": None}
