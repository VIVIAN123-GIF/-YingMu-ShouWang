from __future__ import annotations

import math
import asyncio
import json
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from pathlib import Path

import pytest

from contracts.v1.algorithm import AlgorithmJob, AlgorithmModule, MediaType
from contracts.v1.gait_adapter_v15 import infer_activity_context, run_with_config
from contracts.v1.gait_video import _gait_cycle_metrics
from contracts.v1.ruleset import load_ruleset_version
from contracts.v1.models import Observation
from backend.service import personal_gait_service
from scripts.exploratory_reanalysis_v15 import _v15_baseline, safe_output


def _job(tmp_path: Path) -> AlgorithmJob:
    media = tmp_path / "clip.json"
    media.write_text("{}", encoding="utf-8")
    return AlgorithmJob(
        schema_version="algorithm-job/1.0", job_id="v15-test", correlation_id="v15-test",
        resident_id="resident-1", asset_id="asset-1", media_type=MediaType.VIDEO,
        media_locator=str(media), captured_at="2026-08-29T12:00:00+08:00",
        source_mode="RECORDED_REPLAY", simulated=True, location="living_room",
        camera_position_id="camera-1", scene_config_id="scene-1",
        requested_modules=[AlgorithmModule.GAIT], deadline_ms=120000,
    )


def test_v15_ruleset_is_version_isolated():
    assert load_ruleset_version("ruleset-v1.4").version == "ruleset-v1.4"
    v15 = load_ruleset_version("ruleset-v1.5")
    assert v15.version == "ruleset-v1.5"
    assert v15.windows["trend_persistence_windows"] == 2
    assert v15.thresholds["gait_min_complete_cycles"] == 2


@pytest.mark.parametrize(
    ("features", "expected"),
    [
        ({"locomotion_duration_s": 4, "gait_cycle_count": 2, "sit_to_stand_transition_confirmed": True}, "POST_RISE_LOCOMOTION"),
        ({"locomotion_duration_s": 0, "sit_to_stand_transition_confirmed": True}, "RISE_ONLY"),
        ({"locomotion_duration_s": 4, "gait_cycle_count": 2, "sit_to_stand_transition_confirmed": False}, "WALK"),
        ({"locomotion_duration_s": 4, "gait_cycle_count": 1, "sit_to_stand_transition_confirmed": False}, "STATIC_OR_UNKNOWN"),
        ({"locomotion_duration_s": 0, "sit_to_stand_transition_confirmed": False}, "STATIC_OR_UNKNOWN"),
    ],
)
def test_activity_context_is_derived_from_features(features, expected):
    assert infer_activity_context(features) == expected


def test_cycle_asymmetry_requires_and_uses_bilateral_cycles():
    rows = []
    for index in range(240):
        phase = index * 2 * math.pi / 30
        rows.append({
            "left_ankle_x": 0.5 + 0.30 * math.sin(phase),
            "right_ankle_x": 0.5 + 0.14 * math.sin(phase + math.pi),
            "pelvis_x_smooth": 0.5, "body_scale": 1.0,
        })
    result = _gait_cycle_metrics(rows)
    assert result["gait_cycle_count"] >= 2
    assert result["gait_cycle_assessment_valid"] == 1.0
    assert result["stride_length_asymmetry_ratio"] > 0.35


def test_cycle_asymmetry_degrades_partial_step():
    rows = [
        {"left_ankle_x": index / 100, "right_ankle_x": index / 100,
         "pelvis_x_smooth": 0.0, "body_scale": 1.0}
        for index in range(7)
    ]
    result = _gait_cycle_metrics(rows)
    assert result["gait_cycle_count"] == 0
    assert result["gait_cycle_assessment_valid"] == 0


def test_context_baseline_has_no_cross_context_fallback():
    source = {
        "baseline_status": "PROVISIONAL",
        "baselines": {"relative_gait_speed": {
            "median": 0.5, "mad": 0.05, "sample_count": 8,
            "distinct_days": 3, "status": "PROVISIONAL",
        }},
    }
    result = _v15_baseline(source)
    assert set(result["baselines_by_context"]) == {"WALK"}
    assert "POST_RISE_LOCOMOTION" in result["unavailable_contexts"]


def test_runtime_personal_speed_refuses_cross_context_fallback(monkeypatch):
    async def baseline(*_args):
        return {
            "baselines": {"relative_gait_speed": {
                "median": 0.5, "mad": 0.05, "status": "PROVISIONAL",
            }},
            "baselines_by_context": {"WALK": {"relative_gait_speed": {
                "median": 0.5, "mad": 0.05, "status": "PROVISIONAL",
            }}},
        }
    observation = Observation(
        schema_version="1.0", observation_id="obs-v15-context", resident_id="r",
        timestamp="2026-08-29T12:00:00+08:00", source="gait_adapter_v15",
        feature_name="step_speed_norm_s", feature_value=0.2, unit="norm_per_second",
        location="living_room", confidence=0.9, data_quality=0.9,
        source_mode="RECORDED_REPLAY", asset_id="a", simulated=True,
        metadata={
            "activity_context": "POST_RISE_LOCOMOTION",
            "locomotion_duration_s": 4.0, "gait_cycle_count": 2,
        },
    )
    monkeypatch.setattr(personal_gait_service, "RULESET_VERSION", "ruleset-v1.5")
    monkeypatch.setattr(personal_gait_service.memory_store, "baseline", baseline)
    evidences, summary = asyncio.run(
        personal_gait_service.relative_speed_evidence(None, [observation])
    )
    assert evidences == []
    assert summary["decisions"][0]["reason"] == "ACTIVITY_CONTEXT_BASELINE_UNAVAILABLE"


def test_v15_runtime_requires_two_abnormal_activity_windows():
    class Scalars:
        def __init__(self, rows): self.rows = rows
        def all(self): return self.rows
    class Result:
        def __init__(self, rows): self.rows = rows
        def scalars(self): return Scalars(self.rows)
    class Db:
        def __init__(self, rows): self.rows = rows
        async def execute(self, _statement): return Result(self.rows)

    current = Observation(
        schema_version="1.0", observation_id="current", resident_id="r",
        timestamp="2026-08-29T12:00:00+08:00", source="gait_adapter_v15",
        feature_name="step_speed_norm_s", feature_value=0.2, unit="norm_per_second",
        location="living_room", confidence=0.9, data_quality=0.9,
        source_mode="RECORDED_REPLAY", asset_id="current-asset", simulated=True,
        metadata={
            "activity_context": "WALK", "locomotion_duration_s": 4.0,
            "gait_cycle_count": 2,
        },
    )
    prior = SimpleNamespace(
        extra_metadata=json.dumps({"activity_context": "WALK"}),
        feature_value="0.2", asset_id="prior-asset",
        timestamp=datetime(2026, 8, 29, 11, 59, tzinfo=timezone(timedelta(hours=8))),
    )
    stats = {"median": 0.5, "mad": 0.02, "status": "PROVISIONAL"}
    ruleset = load_ruleset_version("ruleset-v1.5")
    assert asyncio.run(personal_gait_service._has_persistent_v15_deviation(
        Db([]), current, stats, ruleset,
    )) == (False, 1)
    assert asyncio.run(personal_gait_service._has_persistent_v15_deviation(
        Db([prior]), current, stats, ruleset,
    )) == (True, 2)


def test_exploratory_output_refuses_overwrite_and_p03(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="overwrite"):
        safe_output(existing)


def test_v15_adapter_records_context_and_filters_partial_cycle_gait(monkeypatch, tmp_path):
    features = {
        "valid_frame_ratio": 1.0, "assessment_status": "GAIT_ONLY",
        "assessment_reason_code": "POST_RISE_UNUSABLE_GAIT_WINDOW_VALID",
        "sit_to_stand_transition_confirmed": False, "locomotion_duration_s": 4.0,
        "step_speed_norm_s": 0.2, "step_asymmetry_ratio": 0.8,
        "gait_cycle_count": 1.0, "gait_cycle_assessment_valid": 0.0,
        "stable_posture_duration": 0.0, "stable_trunk_angle_deg": 0.0,
    }
    monkeypatch.setattr(
        "contracts.v1.gait_adapter_v15._read_v15",
        lambda job: (features, {"quality_gate_status": "PASS"}),
    )
    batch = asyncio.run(run_with_config(_job(tmp_path)))
    assert batch.adapter_version == "gait-adapter-v1.5-exploratory"
    assert batch.diagnostics["activity_context"] == "STATIC_OR_UNKNOWN"
    assert "gait_instability" not in {item.evidence_type for item in batch.evidences}
    speed = next(item for item in batch.observations if item.feature_name == "step_speed_norm_s")
    assert speed.source == "gait_adapter_v15"
    assert speed.metadata["activity_context"] == "STATIC_OR_UNKNOWN"
