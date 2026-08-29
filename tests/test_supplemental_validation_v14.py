from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.service import forewarning_service, personal_gait_service
from backend.service.baseline_service import BaselineStore
from contracts.v1 import gait_video
from contracts.v1.algorithm import AlgorithmJob, AlgorithmModule, MediaType
from contracts.v1.decision import FallDecisionPolicy
from contracts.v1.gait_adapter_v14 import _severity, run_with_config
from contracts.v1.gait_video import _active_gait_metrics, _derive_gait_features_v14
from contracts.v1.models import Observation
from contracts.v1.ruleset import load_ruleset_version
from scripts import build_v14_baseline
from scripts import reanalyze_p01_p02_v14 as legacy_reanalysis
from scripts import supplemental_validation_v14 as supplemental


CN = timezone(timedelta(hours=8))


def _rows(*, feet_visibility: float = 0.95) -> list[dict[str, float]]:
    rows = []
    for index in range(20):
        rows.append({
            "timestamp_ms": float(index * 100),
            "pelvis_x": 0.5,
            "pelvis_y": 0.7,
            "trunk_angle_deg": 0.0,
            "left_stride_extent": 0.1,
            "right_stride_extent": 0.1,
            "support_distance": 0.2,
            "core_visibility_mean": 0.95,
            "torso_visibility_mean": 0.95,
            "feet_visibility_mean": feet_visibility,
            "body_scale": 0.2,
            "orientation_quality": 1.0,
            "left_ankle_x": 0.4,
            "left_ankle_y": 0.9,
            "right_ankle_x": 0.6,
            "right_ankle_y": 0.9,
            "left_knee_angle_deg": 170.0,
            "right_knee_angle_deg": 170.0,
        })
    return rows


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"occlusion_max_frames": 16}, "HUMAN_TRACKING_OR_OCCLUSION"),
        ({"feet_visibility": 0.4}, "FEET_OUT_OF_FRAME"),
        ({"illumination_norm": 0.1}, "LOW_ILLUMINATION"),
        ({"multi_person_frames": 6, "multi_person_max_frames": 6}, "MULTIPLE_PEOPLE"),
    ],
)
def test_v14_four_quality_gates_force_indeterminate(kwargs, reason):
    rows = _rows(feet_visibility=kwargs.pop("feet_visibility", 0.95))
    features, diagnostics = _derive_gait_features_v14(
        rows,
        total_frames=20,
        fps=10.0,
        duration_s=2.0,
        illumination_norm=kwargs.pop("illumination_norm", 0.8),
        multi_person_frames=kwargs.pop("multi_person_frames", 0),
        multi_person_max_frames=kwargs.pop("multi_person_max_frames", 0),
        occlusion_max_frames=kwargs.pop("occlusion_max_frames", 0),
    )

    assert features["assessment_status"] == "INDETERMINATE"
    assert reason in diagnostics["quality_gate_reasons"]
    assert diagnostics["quality_gate_status"] == "FAILED"


def test_active_gait_speed_excludes_long_static_period():
    rows = []
    pelvis_x = 0.5
    for index in range(111):
        if index > 100:
            pelvis_x += 0.02
        rows.append({
            "timestamp_ms": float(index * 100),
            "pelvis_x_smooth": pelvis_x,
            "pelvis_y_smooth": 0.7,
            "body_scale": 0.2,
            "left_ankle_x": pelvis_x - 0.1,
            "right_ankle_x": pelvis_x + 0.1,
            "left_stride_extent": 0.5,
            "right_stride_extent": 0.5,
        })

    metrics = _active_gait_metrics(rows)

    assert metrics["step_speed_norm_s"] == pytest.approx(1.0)
    assert metrics["locomotion_frame_ratio"] < 0.2
    assert metrics["locomotion_duration_s"] == pytest.approx(1.0)


def test_valid_gait_window_survives_indeterminate_post_rise_assessment(monkeypatch):
    rows = _rows()
    for index, row in enumerate(rows):
        row["pelvis_x_smooth"] = 0.4 + index * 0.01
        row["pelvis_y_smooth"] = 0.7
        row["left_ankle_x"] = row["pelvis_x_smooth"] - 0.1
        row["right_ankle_x"] = row["pelvis_x_smooth"] + 0.1
    monkeypatch.setattr(
        gait_video,
        "_derive_gait_features",
        lambda *_args, **_kwargs: ({
            "assessment_status": "INDETERMINATE",
            "assessment_reason_code": "CAMERA_ORIENTATION_UNSUITABLE",
            "sit_to_stand_transition_confirmed": True,
            "valid_frame_ratio": 1.0,
        }, {}),
    )
    features, diagnostics = gait_video._derive_gait_features_v14(
        rows,
        total_frames=20,
        fps=10.0,
        duration_s=2.0,
        illumination_norm=0.8,
        multi_person_frames=0,
        multi_person_max_frames=0,
        occlusion_max_frames=0,
    )
    assert features["assessment_status"] == "GAIT_ONLY"
    assert features["sit_to_stand_transition_confirmed"] is False
    assert diagnostics["quality_gate_status"] == "PASS"


def _job(path: Path) -> AlgorithmJob:
    return AlgorithmJob(
        schema_version="algorithm-job/1.0",
        job_id="job-v14-test",
        correlation_id="corr-v14-test",
        resident_id="resident-v14",
        asset_id="asset-v14",
        media_type=MediaType.VIDEO,
        media_locator=str(path),
        captured_at="2026-08-28T12:00:00+08:00",
        source_mode="RECORDED_REPLAY",
        simulated=True,
        location="living_room",
        camera_position_id="position-v14",
        scene_config_id="scene-v14",
        requested_modules=[AlgorithmModule.GAIT],
        deadline_ms=120000,
    )


def test_quality_gate_bypass_requires_explicit_offline_ablation(tmp_path):
    path = tmp_path / "features.json"
    path.write_text(json.dumps({"features": {
        "assessment_status": "INDETERMINATE",
        "assessment_reason_code": "LOW_ILLUMINATION",
        "pre_quality_assessment_status": "NO_TRANSITION",
        "pre_quality_assessment_reason_code": "NO_SIT_TO_STAND_TRANSITION",
        "valid_frame_ratio": 0.95,
    }}), encoding="utf-8")

    with pytest.raises(ValueError, match="OFFLINE_ONLY"):
        asyncio.run(run_with_config(_job(path), quality_gate=False))

    batch = asyncio.run(
        run_with_config(_job(path), quality_gate=False, offline_ablation=True)
    )
    assert batch.status == "NO_EVIDENCE"
    assert batch.diagnostics["quality_gate_enabled"] is False


def _personal_observation(value: float) -> Observation:
    return Observation(
        schema_version="1.0",
        observation_id=f"obs-speed-{value}",
        resident_id="resident-v14",
        timestamp="2026-08-28T12:00:00+08:00",
        source="gait_adapter_v14",
        feature_name="step_speed_norm_s",
        feature_value=value,
        unit="norm_per_second",
        location="living_room",
        confidence=0.9,
        data_quality=0.9,
        source_mode="RECORDED_REPLAY",
        asset_id="asset-v14",
        simulated=True,
    )


def test_relative_speed_is_suppressed_when_personal_baseline_is_insufficient(monkeypatch):
    async def baseline(*_args):
        return {"baselines": {"relative_gait_speed": {
            "status": "INSUFFICIENT", "median": None, "mad": None,
        }}}

    monkeypatch.setattr(personal_gait_service, "RULESET_VERSION", "ruleset-v1.4")
    monkeypatch.setattr(personal_gait_service.memory_store, "baseline", baseline)
    evidences, summary = asyncio.run(
        personal_gait_service.relative_speed_evidence(None, [_personal_observation(0.5)])
    )

    assert evidences == []
    assert summary["decisions"][0]["reason"] == "PERSONAL_BASELINE_INSUFFICIENT"


def test_relative_speed_uses_personal_median_and_real_deviation(monkeypatch):
    async def baseline(*_args):
        return {"baselines": {"relative_gait_speed": {
            "status": "PROVISIONAL", "median": 1.0, "mad": 0.1,
        }}}

    monkeypatch.setattr(personal_gait_service, "RULESET_VERSION", "ruleset-v1.4")
    monkeypatch.setattr(personal_gait_service.memory_store, "baseline", baseline)
    evidences, summary = asyncio.run(
        personal_gait_service.relative_speed_evidence(None, [_personal_observation(0.5)])
    )

    assert len(evidences) == 1
    assert evidences[0].baseline_value == 1.0
    assert evidences[0].current_value == 0.5
    assert evidences[0].baseline_deviation == -0.5
    assert 0 < evidences[0].severity < 1
    assert summary["decisions"][0]["baseline_mad"] == 0.1
    assert summary["decisions"][0]["baseline_status"] == "PROVISIONAL"


def test_relative_speed_uses_mad_as_a_conservative_noise_floor(monkeypatch):
    async def baseline(*_args):
        return {"baselines": {"relative_gait_speed": {
            "status": "PROVISIONAL", "median": 1.0, "mad": 0.2,
        }}}

    monkeypatch.setattr(personal_gait_service, "RULESET_VERSION", "ruleset-v1.4")
    monkeypatch.setattr(personal_gait_service.memory_store, "baseline", baseline)
    evidences, summary = asyncio.run(
        personal_gait_service.relative_speed_evidence(None, [_personal_observation(0.5)])
    )

    assert evidences == []
    decision = summary["decisions"][0]
    assert decision["status"] == "WITHIN_BASELINE"
    assert decision["relative_threshold"] == 0.35
    assert decision["mad_threshold"] == 0.6
    assert decision["effective_threshold"] == 0.6

    offline = supplemental._personal_speed_evidence(
        _personal_observation(0.5),
        {"baselines": {"relative_gait_speed": {
            "status": "PROVISIONAL", "median": 1.0, "mad": 0.2,
        }}},
        load_ruleset_version("ruleset-v1.4"),
    )
    assert offline is None


def _decision_evidence(evidence_id: str, evidence_type: str, observation_ids: list[str]):
    return SimpleNamespace(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        observation_ids=observation_ids,
        timestamp=datetime(2026, 8, 28, 12, tzinfo=CN),
        confidence=0.9,
        data_quality=0.9,
        severity=0.6,
        source_mode="RECORDED_REPLAY",
        simulated=True,
    )


def test_v14_trend_evidence_is_yellow_and_never_orange_by_itself():
    policy = FallDecisionPolicy(load_ruleset_version("ruleset-v1.4"))
    trend = _decision_evidence("evi-trend", "gait_instability", ["obs-gait"])

    decision = policy.evaluate(
        now=trend.timestamp,
        previous_state="GREEN",
        active_status=None,
        active_created_at=None,
        recovery_started_at=None,
        recent=[trend],
        trigger=trend,
        context_score=0.0,
    )

    assert decision.matched_rule == "R-FALL-13"
    assert decision.risk_level == "YELLOW"
    assert decision.action == "REVIEW"


def test_v14_requires_two_immediate_signal_families_for_orange():
    policy = FallDecisionPolicy(load_ruleset_version("ruleset-v1.4"))
    transition = _decision_evidence("evi-transition", "sit_to_stand_transition", ["obs-transition"])
    trunk = _decision_evidence("evi-trunk", "trunk_sway", ["obs-trunk", "obs-transition"])
    drift = _decision_evidence("evi-drift", "post_rise_lateral_drift", ["obs-drift", "obs-transition"])

    decision = policy.evaluate(
        now=drift.timestamp,
        previous_state="GREEN",
        active_status=None,
        active_created_at=None,
        recovery_started_at=None,
        recent=[transition, trunk, drift],
        trigger=drift,
        context_score=0.0,
    )

    assert decision.matched_rule == "R-FALL-02"
    assert decision.risk_level == "ORANGE"
    assert decision.action == "CREATE_EVENT"


def test_forewarning_counts_independent_families_not_evidence_types():
    ruleset = load_ruleset_version("ruleset-v1.4")
    same_family = [
        SimpleNamespace(evidence_type="support_base_change"),
        SimpleNamespace(evidence_type="compensatory_step"),
    ]
    independent = [
        *same_family,
        SimpleNamespace(evidence_type="trunk_sway"),
    ]

    assert forewarning_service._independent_signal_families(same_family, ruleset) == {"feet"}
    assert forewarning_service._independent_signal_families(independent, ruleset) == {"feet", "trunk"}


def test_v14_severity_is_excess_over_threshold_not_immediate_saturation():
    assert _severity(12.1, 12.0, 30.0) < 0.01
    assert _severity(30.0, 12.0, 30.0) == 1.0


class _ScalarResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class _FakeSession:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return _ScalarResult(self.results.pop(0))


def test_v14_live_device_baseline_is_admitted_and_content_hash_is_deduplicated():
    resident_id = "resident-live-v14"
    metrics = {
        "rise_duration_s": "rise_duration",
        "trunk_sway_angle_deg": "trunk_sway",
        "step_speed_norm_s": "relative_gait_speed",
    }
    evidences = []
    observations = []
    assets = []
    for day in (1, 2, 3, 4):
        asset_id = f"asset-live-{day}"
        content_hash = f"{day if day < 4 else 3:064x}"
        assets.append(SimpleNamespace(
            asset_id=asset_id,
            device_ref="device-01",
            device_model="EZVIZ_C6C",
            camera_position_id="position-01",
            source_mode="LIVE_DEVICE",
            simulated=False,
            verification_status="VERIFIED_LIVE_CAPTURE",
            authorization_status="AUTHORIZED",
            authorization_record_id="auth-01",
            retention_until=datetime(2027, 1, 1, tzinfo=CN),
            content_sha256=content_hash,
        ))
        timestamp = datetime(2026, 8, day, 9, tzinfo=CN)
        for index, (feature, metric) in enumerate(metrics.items()):
            observation_id = f"obs-{day}-{index}"
            observations.append(SimpleNamespace(
                observation_id=observation_id,
                resident_id=resident_id,
                timestamp=timestamp,
                source="baseline-importer-v1.4",
                feature_name=feature,
                feature_value=json.dumps(1.0 + day / 10),
                unit="ratio",
                location="living_room",
                confidence=0.9,
                data_quality=0.9,
                source_mode="LIVE_DEVICE",
                asset_id=asset_id,
                simulated=False,
                extra_metadata="{}",
                schema_version="1.0",
            ))
            evidences.append(SimpleNamespace(
                evidence_id=f"evi-{day}-{index}",
                resident_id=resident_id,
                timestamp=timestamp,
                risk_domain="FALL",
                evidence_type="normal_baseline_sample",
                severity=0.0,
                confidence=0.9,
                data_quality=0.9,
                baseline_value=None,
                current_value=1.0 + day / 10,
                baseline_deviation=None,
                time_scale="LONG",
                location="living_room",
                explanation=metric,
                adapter_version="baseline-importer-v1.4",
                source_mode="LIVE_DEVICE",
                simulated=False,
                observation_ids=json.dumps([observation_id]),
                schema_version="1.0",
            ))
    session = _FakeSession(evidences, observations, assets, [], [])
    store = BaselineStore()
    store.ruleset = load_ruleset_version("ruleset-v1.4")

    result = asyncio.run(store.baseline(
        session, resident_id, datetime(2026, 8, 5, 9, tzinfo=CN)
    ))

    assert result["overall_status"] == "PROVISIONAL"
    assert result["source_mode"] == "LIVE_DEVICE"
    assert result["simulated"] is False
    assert all(item["sample_count"] == 3 for item in result["baselines"].values())
    assert all(item["distinct_days"] == 3 for item in result["baselines"].values())

    assets[0].content_sha256 = None
    without_hash = asyncio.run(store.baseline(
        _FakeSession(evidences, observations, assets, [], []),
        resident_id,
        datetime(2026, 8, 5, 9, tzinfo=CN),
    ))
    assert without_hash["overall_status"] == "INSUFFICIENT"
    assert all(
        item["sample_count"] == 2
        for item in without_hash["baselines"].values()
    )


def test_supplemental_outputs_cannot_target_p03_or_overwrite(tmp_path):
    with pytest.raises(ValueError, match="P03_FROZEN_OUTPUT_PROTECTED"):
        supplemental.safe_output(supplemental.P03_PROTECTED / "new-v14-output")

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="refusing to overwrite"):
        supplemental.safe_output(existing)

    protected_manifest = supplemental.P03_PROTECTED / "v14-baseline-manifest.json"
    with pytest.raises(ValueError, match="P03_FROZEN_OUTPUT_PROTECTED"):
        supplemental.template(
            supplemental.P03_PROTECTED / "v14-capture-manifest.json"
        )

    with pytest.raises(ValueError, match="P03_FROZEN_OUTPUT_PROTECTED"):
        build_v14_baseline.create_manifest(
            tmp_path,
            protected_manifest,
            participant_id="SV01",
            authorization_record_id="AUTH-TEST",
            retention_until="2027-08-31T23:59:59+08:00",
        )

    with pytest.raises(ValueError, match="P03_FROZEN_OUTPUT_PROTECTED"):
        build_v14_baseline.extract(
            tmp_path / "manifest.json",
            tmp_path,
            supplemental.P03_PROTECTED / "v14-baseline-results",
        )


def test_locked_run_rejects_a_different_baseline_snapshot(tmp_path):
    locked = tmp_path / "locked-baseline.json"
    supplied = tmp_path / "supplied-baseline.json"
    locked.write_text('{"snapshot":"locked"}', encoding="utf-8")
    supplied.write_text('{"snapshot":"different"}', encoding="utf-8")
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps({
        "bindings": {
            "baseline_results": {
                "path": str(locked),
                "sha256": supplemental.sha256_file(locked),
            },
        },
        "media": [],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="LOCKED_BASELINE_RESULTS_MISMATCH"):
        supplemental.run_locked(
            lock_path, tmp_path, supplied, tmp_path / "run-output"
        )


def test_v14_metrics_include_wilson_intervals_for_binomial_rates():
    records = [
        {"positive": True, "negative": False, "prediction": True},
        {"positive": True, "negative": False, "prediction": False},
        {"positive": False, "negative": True, "prediction": True},
        {"positive": False, "negative": True, "prediction": False},
    ]
    result = supplemental.confusion(
        records,
        lambda item: item["positive"],
        lambda item: item["negative"],
        "prediction",
    )

    assert (result["tp"], result["tn"], result["fp"], result["fn"]) == (1, 1, 1, 1)
    assert result["precision_wilson_95"] is not None
    assert result["recall_wilson_95"] is not None
    assert result["specificity_wilson_95"] is not None
    assert result["false_positive_rate_wilson_95"] is not None


def test_ablation_configuration_is_fixed_and_d_is_offline_only():
    configs = load_ruleset_version("ruleset-v1.4").ablation_configs

    assert configs["A"] == {
        "personal_baseline": True,
        "medium_memory": True,
        "long_memory": True,
        "quality_gate": True,
        "context": True,
        "offline_only": False,
    }
    assert configs["B"]["personal_baseline"] is False
    assert configs["C"]["medium_memory"] is False
    assert configs["C"]["long_memory"] is False
    assert configs["D"]["quality_gate"] is False
    assert configs["D"]["context"] is False
    assert configs["D"]["offline_only"] is True

    evidences = [
        SimpleNamespace(evidence_id="short", time_scale="SHORT"),
        SimpleNamespace(evidence_id="medium", time_scale="MEDIUM"),
        SimpleNamespace(evidence_id="long", time_scale="LONG"),
    ]
    assert [item.evidence_id for item in supplemental._memory_filtered_evidence(
        evidences, configs["C"]
    )] == ["short"]
    assert [item.evidence_id for item in supplemental._memory_filtered_evidence(
        evidences, configs["A"]
    )] == ["short", "medium", "long"]


def test_golden_loop_runs_mock_tool_and_state_machine_with_recorded_coverage():
    record = {
        "clip_id": "SV01-GOLDEN_CONTINUOUS_LOOP-01",
        "captured_at": "2026-08-28T12:00:00+08:00",
        "orange": True,
        "evidence_types": ["trunk_sway", "post_rise_lateral_drift", "posture_recovered"],
        "feature_values": {"stable_posture_duration": 80.0},
        "diagnostics": {"duration_s": 100.0},
    }

    result = supplemental.golden_loop_acceptance(
        record, load_ruleset_version("ruleset-v1.4")
    )

    assert result["status"] == "PASS"
    assert result["observed_sequence"] == ["ORANGE", "INTERVENING", "OBSERVING", "RESOLVED"]
    assert result["intervention"] == {
        "tool": "mock_voice", "delivery_status": "SUCCESS", "simulated": True,
    }
    assert [item["matched_rule"] for item in result["state_machine_transitions"]] == [
        "R-FALL-04", "R-FALL-05",
    ]

    record["feature_values"]["stable_posture_duration"] = 60.0
    insufficient = supplemental.golden_loop_acceptance(
        record, load_ruleset_version("ruleset-v1.4")
    )
    assert insufficient["status"] == "FAIL"
    assert insufficient["recorded_temporal_coverage"] is False


def test_legacy_reanalysis_record_returns_auditable_payload(tmp_path, monkeypatch):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"test")

    async def fake_run(_job):
        return SimpleNamespace(
            observations=[SimpleNamespace(
                feature_name="step_speed_norm_s", feature_value=0.5,
            )],
            evidences=[],
            diagnostics={"quality_gate_status": "PASS"},
            status=SimpleNamespace(value="SUCCESS"),
        )

    monkeypatch.setattr(legacy_reanalysis, "run_gait", fake_run)
    row = {
        "clip_id": "P01-TEST-01", "participant_id": "P01",
        "dataset_split": "CALIBRATION", "record_role": "BASELINE",
        "scenario_id": "BASE_NORMAL", "capture_date": "2026-08-24",
        "camera_position_id": "C6c-pos01", "video_relpath": media.name,
    }

    result = asyncio.run(legacy_reanalysis._run_one(row, tmp_path))

    assert result["status"] == "SUCCESS"
    assert result["features"]["step_speed_norm_s"] == 0.5
    assert result["quality_gate_status"] == "PASS"
