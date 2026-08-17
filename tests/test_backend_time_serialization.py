from datetime import datetime, timedelta

from backend.db.models import AgentExplanationJob
from backend.service.agent_explanation_job_service import job_dict
from backend.service.serialization import CN_TZ, cn_now_naive, utc_naive_to_cn


def test_agent_job_utc_timestamps_are_returned_as_beijing_time():
    job = AgentExplanationJob(
        request_id="agent-time-test",
        event_id="event-time-test",
        event_version_hash="a" * 64,
        request_payload="{}",
        status="SUCCESS",
        response_payload="{}",
        generated_by="test-provider",
        fallback_used=False,
        attempt_count=1,
        created_at=datetime(2026, 8, 17, 13, 48, 42),
        completed_at=datetime(2026, 8, 17, 13, 51, 2),
    )

    payload = job_dict(job)

    assert payload["created_at"].isoformat() == "2026-08-17T21:48:42+08:00"
    assert payload["completed_at"].isoformat() == "2026-08-17T21:51:02+08:00"


def test_beijing_scheduler_clock_matches_project_naive_time_convention():
    before = datetime.now(CN_TZ).replace(tzinfo=None)
    current = cn_now_naive()
    after = datetime.now(CN_TZ).replace(tzinfo=None)

    assert before <= current <= after
    assert utc_naive_to_cn(datetime(2026, 8, 17, 13, 48, 42)).utcoffset() == timedelta(hours=8)
