"""Durable AlgorithmJob orchestration after a captured Asset is persisted."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import YINGMU_LOCATION, YINGMU_SCENE_CONFIG_ID
from backend.db.models import AlarmProcessingTask, Asset
from backend.schemas.evidence import EvidenceCreate
from backend.schemas.observation import ObservationCreate
from backend.service.adapter_registry import AdapterRegistry, AdapterRegistryError, adapter_registry
from backend.service.algorithm_gateway import AlgorithmGateway
from backend.service.evidence_service import create_evidence
from backend.service.observation_service import create_observation
from backend.service.serialization import aware, dumps
from backend.service.snapshot_asset_service import resolve_private_asset_path
from backend.schemas.intervention_result import InterventionResultCreate
from backend.service.event_service import create_intervention_result
from backend.db.models import RiskEvent
from contracts.v1.algorithm import (
    AdapterBatch,
    AdapterStatus,
    AlgorithmJob,
    AlgorithmModule,
    MediaType,
    validate_batch_for_job,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _media_plan(asset: Asset, path: Path) -> tuple[MediaType, list[AlgorithmModule]]:
    content_type = (asset.content_type or "").lower()
    suffix = path.suffix.lower()
    if content_type.startswith("image/") or suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return MediaType.IMAGE, [AlgorithmModule.GAIT]
    if content_type.startswith("video/") or suffix in {".mp4", ".mov", ".avi", ".mkv"}:
        return MediaType.VIDEO, [AlgorithmModule.GAIT, AlgorithmModule.TRAJECTORY]
    if content_type.startswith("audio/") or suffix in {".wav", ".mp3", ".m4a", ".aac"}:
        return MediaType.AUDIO, [AlgorithmModule.LANGUAGE]
    raise ValueError("ASSET_MEDIA_TYPE_UNSUPPORTED")


async def claim_next_algorithm_task(db: AsyncSession) -> AlarmProcessingTask | None:
    now = _now()
    candidate = (await db.execute(
        select(AlarmProcessingTask)
        .where(
            or_(
                AlarmProcessingTask.status.in_(("CAPTURED", "WAITING_ALGORITHM")),
                and_(
                    AlarmProcessingTask.status == "RETRY",
                    AlarmProcessingTask.error_stage == "ALGORITHM",
                    AlarmProcessingTask.available_at <= now,
                ),
            )
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
            AlarmProcessingTask.status == candidate.status,
        )
        .values(
            status="ALGORITHM_PROCESSING",
            algorithm_started_at=now,
            algorithm_attempt_count=AlarmProcessingTask.algorithm_attempt_count + 1,
            error_code=None,
            error_message=None,
            error_stage=None,
        )
    )
    await db.commit()
    if claimed.rowcount != 1:
        return None
    return await db.get(AlarmProcessingTask, candidate.id)


def _module_summary(
    module: AlgorithmModule,
    *,
    status: str,
    elapsed_ms: int,
    adapter_version: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    return {
        "module": module.value,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "adapter_version": adapter_version,
        "error_code": error_code,
    }


async def _persist_batches(
    db: AsyncSession,
    task: AlarmProcessingTask,
    batches: list[AdapterBatch],
) -> tuple[int, int]:
    observations = [item for batch in batches for item in batch.observations]
    evidences = [item for batch in batches for item in batch.evidences]
    for observation in observations:
        await create_observation(
            db,
            ObservationCreate.model_validate(observation.model_dump(mode="json")),
        )
    for evidence in evidences:
        await create_evidence(
            db,
            EvidenceCreate.model_validate(evidence.model_dump(mode="json")),
            f"algorithm-{task.task_id}-{evidence.evidence_id}",
        )
    return len(observations), len(evidences)


async def _persist_resident_responses(
    db: AsyncSession,
    task: AlarmProcessingTask,
    batches: list[AdapterBatch],
) -> None:
    event = (await db.execute(
        select(RiskEvent)
        .where(
            RiskEvent.resident_id == task.resident_id,
            RiskEvent.status.in_(("OPEN", "INTERVENING", "OBSERVING")),
        )
        .order_by(RiskEvent.created_at.desc())
    )).scalars().first()
    if event is None:
        return
    for batch in batches:
        candidate = batch.resident_response_candidate
        if candidate is None or candidate.intent.value == "UNCERTAIN":
            continue
        timestamp = batch.completed_at
        payload = InterventionResultCreate(
            schema_version="1.0",
            result_id=f"result-language-{task.task_id}-{candidate.transcript_observation_id}",
            event_id=event.event_id,
            started_at=timestamp,
            completed_at=timestamp,
            action_type="resident_response",
            tool_name="language_adapter",
            delivery_status="SUCCESS",
            resident_response=candidate.intent.value.lower(),
            family_feedback=None,
            risk_after=None,
            resolved=False,
            resolution_reason=None,
            operator="system",
            source_mode=event.source_mode,
            simulated=event.simulated,
        )
        await create_intervention_result(db, event.event_id, payload)


async def process_algorithm_task(
    db: AsyncSession,
    task: AlarmProcessingTask,
    *,
    registry: AdapterRegistry = adapter_registry,
) -> AlarmProcessingTask:
    task_id = task.id
    summaries: list[dict[str, Any]] = []
    retryable_failures = 0
    try:
        asset = (await db.execute(
            select(Asset).where(Asset.asset_id == task.capture_asset_id)
        )).scalar_one_or_none()
        if asset is None or not asset.storage_key:
            raise ValueError("ASSET_PRIVATE_MEDIA_REQUIRED")
        path = resolve_private_asset_path(asset.storage_key)
        if not path.is_file():
            raise ValueError("ASSET_PRIVATE_MEDIA_MISSING")
        media_type, modules = _media_plan(asset, path)
        job = AlgorithmJob(
            schema_version="algorithm-job/1.0",
            job_id=f"job-{task.task_id}",
            correlation_id=task.task_id,
            resident_id=task.resident_id,
            asset_id=asset.asset_id,
            media_type=media_type,
            media_locator=str(path),
            captured_at=aware(asset.captured_at),
            source_mode=asset.source_mode,
            simulated=asset.simulated,
            location=YINGMU_LOCATION,
            camera_position_id=asset.camera_position_id or "unconfigured-camera-position",
            scene_config_id=YINGMU_SCENE_CONFIG_ID,
            requested_modules=modules,
            deadline_ms=8000,
        )
        registry.load_configured()
        missing = [module for module in modules if registry.get(module) is None]
        for module in missing:
            summaries.append(_module_summary(
                module, status="FAILED", elapsed_ms=0, error_code="ADAPTER_NOT_REGISTERED"
            ))
        configured = [module for module in modules if module not in missing]
        gateway = AlgorithmGateway(timeout_seconds=job.deadline_ms / 1000, max_retries=2)

        async def run_module(module: AlgorithmModule) -> AdapterBatch:
            return await registry.invoke(module, job)

        results = await gateway.run_many({
            module.value: (lambda module=module: run_module(module))
            for module in configured
        }) if configured else {}
        valid_batches: list[AdapterBatch] = []
        for module in configured:
            result = results[module.value]
            if not result.ok:
                code = "ALGORITHM_TIMEOUT" if "timed out" in (result.error or "") else "ADAPTER_EXECUTION_FAILED"
                summaries.append(_module_summary(
                    module, status="FAILED", elapsed_ms=result.elapsed_ms, error_code=code
                ))
                retryable_failures += 1
                continue
            batch = validate_batch_for_job(AdapterBatch.model_validate(result.output), job)
            summaries.append(_module_summary(
                module,
                status=batch.status.value,
                elapsed_ms=result.elapsed_ms,
                adapter_version=batch.adapter_version,
                error_code=batch.error.code if batch.error else None,
            ))
            if batch.status == AdapterStatus.FAILED:
                retryable_failures += int(bool(batch.error and batch.error.retryable))
            else:
                valid_batches.append(batch)

        observation_count, evidence_count = await _persist_batches(db, task, valid_batches)
        await _persist_resident_responses(db, task, valid_batches)
        all_failed = not valid_batches
        if all_failed and retryable_failures and task.algorithm_attempt_count < task.max_attempts:
            task.status = "RETRY"
            task.available_at = _now() + timedelta(seconds=2 ** task.algorithm_attempt_count)
            task.error_stage = "ALGORITHM"
            task.error_code = "ALGORITHM_RETRY"
            task.error_message = "All configured algorithm modules failed temporarily"
        elif all_failed:
            task.status = "FAILED"
            task.finished_at = _now()
            task.algorithm_completed_at = task.finished_at
            task.error_stage = "ALGORITHM"
            task.error_code = "ADAPTER_NOT_REGISTERED" if missing and len(missing) == len(modules) else "ALGORITHM_FAILED"
            task.error_message = "No algorithm module produced a valid batch"
        else:
            task.status = "COMPLETED" if evidence_count else "NO_EVIDENCE"
            task.finished_at = _now()
            task.algorithm_completed_at = task.finished_at
            task.error_stage = None
            task.error_code = "PARTIAL_ALGORITHM_FAILURE" if len(valid_batches) < len(modules) else None
            task.error_message = None
        task.algorithm_summary = dumps({
            "modules": summaries,
            "observation_count": observation_count,
            "evidence_count": evidence_count,
        })
    except (AdapterRegistryError, ValueError, TypeError) as exc:
        task.status = "FAILED"
        task.finished_at = _now()
        task.algorithm_completed_at = task.finished_at
        task.error_stage = "ALGORITHM"
        message = str(exc)
        task.error_code = message.split(":", 1)[0][:64] or "ADAPTER_OUTPUT_INVALID"
        task.error_message = "Algorithm handoff failed contract or availability checks"
        task.algorithm_summary = dumps({"modules": summaries})
    except Exception as exc:
        await db.rollback()
        task = await db.get(AlarmProcessingTask, task_id)
        if task is None:
            raise
        if task.algorithm_attempt_count < task.max_attempts:
            task.status = "RETRY"
            task.available_at = _now() + timedelta(seconds=2 ** task.algorithm_attempt_count)
            task.error_code = "ALGORITHM_RETRY"
        else:
            task.status = "FAILED"
            task.finished_at = _now()
            task.algorithm_completed_at = task.finished_at
            task.error_code = "ALGORITHM_FAILED"
        task.error_stage = "ALGORITHM"
        task.error_message = f"Algorithm processing failed: {type(exc).__name__}"
        task.algorithm_summary = dumps({"modules": summaries})
    await db.commit()
    await db.refresh(task)
    return task
