"""Durable post-WebHook processing without blocking the Ezviz callback."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import AlarmProcessingTask, RiskAlarm
from backend.service.device_adapter import device_adapter
from backend.service.snapshot_asset_service import (
    SnapshotAssetError,
    persist_snapshot_asset,
)
from contracts.v1.platform import PlatformSnapshotResult


CLAIMABLE_STATUSES = ("PENDING", "RETRY")


def _now() -> datetime:
    # Existing SQLite models use timezone-naive DATETIME values.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def task_dict(task: AlarmProcessingTask) -> dict[str, Any]:
    """Public, redacted task status. Never expose capture URLs or raw callbacks."""
    # Provider alarm IDs and physical-device serials are retained only in the
    # database for traceability; browser-facing task status uses opaque refs.
    alarm_ref = hashlib.sha256(task.alarm_msg_id.encode("utf-8")).hexdigest()[:12]
    device_ref = hashlib.sha256(task.device_sn.encode("utf-8")).hexdigest()[:12]
    return {
        "task_id": task.task_id,
        "alarm_ref": f"alarm-{alarm_ref}",
        "resident_id": task.resident_id,
        "device_ref": f"device-{device_ref}",
        "status": task.status,
        "attempt_count": task.attempt_count,
        "max_attempts": task.max_attempts,
        "capture_asset_id": task.capture_asset_id,
        "error_code": task.error_code,
        "error_message": task.error_message,
        "available_at": task.available_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "create_time": task.create_time,
        "update_time": task.update_time,
    }


async def enqueue_alarm_task(db: AsyncSession, alarm_msg_id: str) -> tuple[AlarmProcessingTask, bool]:
    """Create exactly one processing task per persisted raw alarm."""
    existing = (await db.execute(select(AlarmProcessingTask).where(
        AlarmProcessingTask.alarm_msg_id == alarm_msg_id
    ))).scalar_one_or_none()
    if existing:
        return existing, False

    alarm = (await db.execute(select(RiskAlarm).where(
        RiskAlarm.alarm_msg_id == alarm_msg_id
    ))).scalar_one()
    task = AlarmProcessingTask(
        task_id=f"alarm-task-{uuid4().hex}",
        alarm_msg_id=alarm.alarm_msg_id,
        resident_id=alarm.resident_id,
        device_sn=alarm.device_sn,
        status="PENDING",
        available_at=_now(),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task, True


async def claim_next_task(db: AsyncSession) -> AlarmProcessingTask | None:
    """Atomically claim one due task so duplicate workers do not process it twice."""
    now = _now()
    candidate = (await db.execute(
        select(AlarmProcessingTask)
        .where(
            AlarmProcessingTask.status.in_(CLAIMABLE_STATUSES),
            AlarmProcessingTask.available_at <= now,
        )
        .order_by(AlarmProcessingTask.create_time)
        .limit(1)
    )).scalar_one_or_none()
    if candidate is None:
        return None

    claimed = await db.execute(
        update(AlarmProcessingTask)
        .where(
            AlarmProcessingTask.id == candidate.id,
            AlarmProcessingTask.status.in_(CLAIMABLE_STATUSES),
        )
        .values(
            status="PROCESSING",
            started_at=now,
            attempt_count=AlarmProcessingTask.attempt_count + 1,
            error_code=None,
            error_message=None,
        )
    )
    await db.commit()
    if claimed.rowcount != 1:
        return None
    return await db.get(AlarmProcessingTask, candidate.id)


async def process_claimed_task(
    db: AsyncSession,
    task: AlarmProcessingTask,
    *,
    capture_snapshot: Callable[[], Awaitable[dict[str, Any] | PlatformSnapshotResult]] | None = None,
    store_snapshot_asset: Callable[
        [AsyncSession, PlatformSnapshotResult, str], Awaitable[dict[str, Any]]
    ] | None = None,
) -> AlarmProcessingTask:
    """Capture and persist an Asset before handing the task to an algorithm."""
    try:
        snapshot = await (capture_snapshot() if capture_snapshot else device_adapter.capture_snapshot())
        if isinstance(snapshot, dict):
            # Backward-compatible injection for tests or an already-persisted
            # downloader. Production platform calls always return the contract.
            task.capture_asset_id = snapshot.get("asset_id")
        elif store_snapshot_asset is not None:
            asset = await store_snapshot_asset(db, snapshot, task.task_id)
            task.capture_asset_id = asset.get("asset_id")
        else:
            asset, _ = await persist_snapshot_asset(
                db, snapshot, task_id=task.task_id
            )
            task.capture_asset_id = asset["asset_id"]
        if not task.capture_asset_id:
            raise SnapshotAssetError(
                "CAPTURE_ASSET_REQUIRED",
                "A persisted Asset is required before algorithm handoff",
                retryable=False,
            )
        task.status = "WAITING_ALGORITHM"
        task.finished_at = _now()
        task.error_code = None
        task.error_message = (
            "Platform snapshot stored as an authorized Asset; algorithm adapter is pending."
        )
    except SnapshotAssetError as exc:
        if exc.retryable and task.attempt_count < task.max_attempts:
            task.status = "RETRY"
            task.available_at = _now() + timedelta(seconds=2 ** task.attempt_count)
        else:
            task.status = "FAILED"
            task.finished_at = _now()
        task.error_code = exc.code
        task.error_message = exc.message
    except Exception as exc:
        if task.attempt_count < task.max_attempts:
            task.status = "RETRY"
            task.available_at = _now() + timedelta(seconds=2 ** task.attempt_count)
            task.error_code = "EZVIZ_CAPTURE_RETRY"
        else:
            task.status = "FAILED"
            task.finished_at = _now()
            task.error_code = "EZVIZ_CAPTURE_FAILED"
        # Do not persist provider URLs, tokens, or exception chains.
        task.error_message = f"Snapshot request failed: {type(exc).__name__}"
    await db.commit()
    await db.refresh(task)
    return task


async def list_alarm_tasks(
    db: AsyncSession,
    *,
    resident_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = select(AlarmProcessingTask).order_by(AlarmProcessingTask.create_time.desc()).limit(limit)
    if resident_id:
        query = query.where(AlarmProcessingTask.resident_id == resident_id)
    rows = (await db.execute(query)).scalars().all()
    return [task_dict(row) for row in rows]
