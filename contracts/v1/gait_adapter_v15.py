"""Version-isolated exploratory v1.5 gait adapter."""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import Any

from contracts.v1.algorithm import (
    AdapterBatch, AdapterError, AdapterStatus, AlgorithmJob, AlgorithmModule,
    MediaType, validate_batch_for_job,
)
from contracts.v1.gait_adapter_v14 import (
    FEATURES, _build, _observation, _quality, _read,
)
from contracts.v1.gait_video import VIDEO_SUFFIXES, extract_gait_features_v15
from contracts.v1.ruleset import load_ruleset_version


ADAPTER_VERSION = "gait-adapter-v1.5-exploratory"
RULESET = load_ruleset_version("ruleset-v1.5")


def infer_activity_context(features: dict[str, Any]) -> str:
    locomotion = float(features.get("locomotion_duration_s") or 0.0)
    cycles = int(float(features.get("gait_cycle_count") or 0.0))
    transition = bool(features.get("sit_to_stand_transition_confirmed"))
    minimum = float(RULESET.thresholds["relative_speed_min_locomotion_seconds"])
    minimum_cycles = int(RULESET.thresholds["gait_min_complete_cycles"])
    if transition and locomotion >= minimum and cycles >= minimum_cycles:
        return "POST_RISE_LOCOMOTION"
    if transition:
        return "RISE_ONLY"
    if locomotion >= minimum and cycles >= minimum_cycles:
        return "WALK"
    return "STATIC_OR_UNKNOWN"


def _read_v15(job: AlgorithmJob) -> tuple[dict[str, Any], dict[str, Any]]:
    locator = job.media_locator[7:] if job.media_locator.startswith("file://") else job.media_locator
    path = Path(locator).expanduser()
    if path.suffix.lower() in VIDEO_SUFFIXES:
        return extract_gait_features_v15(path)
    return _read(job)


def _v15_evidence(evidences: list[Any], features: dict[str, Any]) -> list[Any]:
    minimum_cycles = int(RULESET.thresholds["gait_min_complete_cycles"])
    cycles = int(float(features.get("gait_cycle_count") or 0.0))
    retained = [
        item for item in evidences
        if item.evidence_type != "gait_instability" or cycles >= minimum_cycles
    ]
    return [item.model_copy(update={"adapter_version": ADAPTER_VERSION}) for item in retained]


async def run_with_config(
    job: AlgorithmJob, *, quality_gate: bool = True, offline_ablation: bool = False,
) -> AdapterBatch:
    if not quality_gate and not offline_ablation:
        raise ValueError("QUALITY_GATE_BYPASS_IS_OFFLINE_ONLY")
    from contracts.v1.gait_adapter_v14 import _now
    started_at = _now()
    try:
        features, diagnostics = await asyncio.to_thread(_read_v15, job)
        quality = _quality(features)
        if not quality_gate and features.get("pre_quality_assessment_status"):
            features["assessment_status"] = features["pre_quality_assessment_status"]
            features["assessment_reason_code"] = features.get(
                "pre_quality_assessment_reason_code", "NO_SIT_TO_STAND_TRANSITION"
            )
            quality = max(quality, 0.7)
        context = infer_activity_context(features)
        observations = []
        for name in FEATURES:
            if name not in features:
                continue
            item = _observation(job, name, features[name], quality)
            metadata = dict(item.metadata or {})
            metadata.update({
                "adapter_version": ADAPTER_VERSION,
                "activity_context": context,
                "context_policy_version": RULESET.context_policy_version,
                "locomotion_duration_s": float(features.get("locomotion_duration_s") or 0.0),
                "gait_cycle_count": int(float(features.get("gait_cycle_count") or 0.0)),
            })
            observations.append(item.model_copy(update={
                "source": "gait_adapter_v15", "metadata": metadata,
            }))
        evidences = _v15_evidence(
            _build(job, observations, quality_gate=quality_gate, ruleset=RULESET), features,
        )
        indeterminate = quality_gate and any(
            item.evidence_type == "assessment_indeterminate" for item in evidences
        )
        if job.media_type == MediaType.IMAGE:
            evidences, status = [], AdapterStatus.NO_EVIDENCE
        elif indeterminate:
            status = AdapterStatus.LOW_QUALITY
        elif evidences:
            status = AdapterStatus.SUCCESS
        else:
            status = AdapterStatus.NO_EVIDENCE
        diagnostics.update({
            "ruleset_version": RULESET.version,
            "activity_context": context,
            "quality_gate_status": "FAILED" if indeterminate else diagnostics.get("quality_gate_status", "PASS"),
            "relative_speed_evidence_deferred_to_backend": True,
            "quality_gate_enabled": quality_gate,
            "trend_persistence_required": int(RULESET.windows["trend_persistence_windows"]),
            "gait_cycle_requirement": int(RULESET.thresholds["gait_min_complete_cycles"]),
            "feature_names": [item.feature_name for item in observations],
            "claim_boundary": RULESET.version + " exploratory reanalysis; not blind validation",
        })
        return validate_batch_for_job(AdapterBatch(
            schema_version="adapter-batch/1.0", job_id=job.job_id,
            module=AlgorithmModule.GAIT, adapter_version=ADAPTER_VERSION,
            status=status, started_at=started_at, completed_at=_now(),
            observations=observations, evidences=evidences, diagnostics=diagnostics,
        ), job)
    except (OSError, ValueError, json.JSONDecodeError, csv.Error):
        return validate_batch_for_job(AdapterBatch(
            schema_version="adapter-batch/1.0", job_id=job.job_id,
            module=AlgorithmModule.GAIT, adapter_version=ADAPTER_VERSION,
            status=AdapterStatus.FAILED, started_at=started_at, completed_at=_now(),
            observations=[], evidences=[],
            error=AdapterError(
                code="FEATURE_INPUT_INVALID",
                message="v1.5 gait input could not be analyzed.", retryable=False,
            ),
        ), job)


async def run(job: AlgorithmJob) -> AdapterBatch:
    return await run_with_config(job, quality_gate=True)
