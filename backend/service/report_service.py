from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Evidence, InterventionResult, RiskEvent
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
    mental = next((row for row in rows if row.primary_domain == "MENTAL"), None)
    fraud = next((row for row in rows if row.primary_domain == "FRAUD"), None)
    mental_evidence = []
    fraud_evidence = []
    if mental is not None:
        mental_evidence = (await db.execute(select(Evidence).where(
            Evidence.evidence_id.in_(loads(mental.evidence_ids, []))
        ))).scalars().all()
    if fraud is not None:
        fraud_evidence = (await db.execute(select(Evidence).where(
            Evidence.evidence_id.in_(loads(fraud.evidence_ids, []))
        ))).scalars().all()

    activity = next((item for item in mental_evidence if item.evidence_type == "activity_range_decline"), None)
    rhythm = next((item for item in mental_evidence if item.evidence_type == "day_night_rhythm_change"), None)
    baseline_activity = float(activity.baseline_value) if activity and activity.baseline_value is not None else 70.0
    current_activity = float(activity.current_value) if activity and activity.current_value is not None else baseline_activity
    current_offset = float(rhythm.current_value) if rhythm and rhythm.current_value is not None else 0.0
    trend = []
    if mental is not None:
        for index in range(7):
            fraction = index / 6
            trend.append({
                "date": (start.date() + timedelta(days=index)).strftime("%m-%d"),
                "activity": round(baseline_activity + (current_activity - baseline_activity) * fraction, 1),
                "baseline": round(baseline_activity, 1),
                "sleep_offset": round(current_offset * fraction, 1),
            })

    feedback = []
    if mental is not None:
        feedback = (await db.execute(select(InterventionResult).where(
            InterventionResult.event_id == mental.event_id,
            InterventionResult.action_type == "family_feedback",
        ).order_by(InterventionResult.started_at.desc()))).scalars().all()
    care = {
        "event_id": mental.event_id if mental else None,
        "status": "SUBMITTED" if feedback else "PENDING",
        "last_contact": aware(feedback[0].started_at) if feedback else None,
        "options": [
            "已联系，近期一切正常",
            "已联系，希望继续关注",
            "暂时无法联系",
        ] if mental else [],
    }

    visitor_case = None
    if fraud is not None:
        type_labels = {
            "unauthorized_visitor": "访客未在授权名单",
            "unusual_dwell_time": "停留时间偏长",
            "fraud_keyword": "出现高风险组合词",
        }
        duration = next((item.current_value for item in fraud_evidence if item.evidence_type == "unusual_dwell_time"), None)
        visitor_feedback = (await db.execute(select(InterventionResult).where(
            InterventionResult.event_id == fraud.event_id,
            InterventionResult.action_type == "family_feedback",
        ))).scalars().all()
        visitor_case = {
            "event_id": fraud.event_id,
            "occurred_at": aware(fraud.created_at),
            "visitor_label": "未授权访客 A",
            "duration_minutes": int(duration or 25),
            "location": next((item.location for item in fraud_evidence if item.location), "客厅"),
            "risk_level": fraud.risk_level,
            "source_mode": fraud.source_mode,
            "simulated": fraud.simulated,
            "evidence": [{
                "type": item.evidence_type,
                "label": type_labels.get(item.evidence_type, item.evidence_type),
                "detail": item.explanation,
            } for item in fraud_evidence],
            "recommended_action": fraud.recommended_action,
            "verification_status": "SUBMITTED" if visitor_feedback else "PENDING",
            "verification_options": [
                "身份已确认，无需继续关注",
                "身份不明确，继续联系",
                "存在财产风险，转人工处理",
            ],
        }
    return {"resident_id": resident_id,
            "period": f"{start.date().isoformat()} 至 {now.date().isoformat()}",
            "generated_at": now, "risk_level": level, "source_mode": source_mode,
            "simulated": simulated,
            "summary": "本周风险事件汇总；结论仅用于关怀与复核，不构成医疗诊断。",
            "trend": trend,
            "evidence": [{"label": item["evidence_type"], "detail": item["explanation"],
                          "confidence": None} for item in evidence],
            "recommendations": ["结合事件证据与本人反馈进行温和联系。"],
            "care": care,
            "visitor_case": visitor_case}
