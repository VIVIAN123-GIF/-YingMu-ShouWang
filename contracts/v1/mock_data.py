"""The fixed simulated post-rise-instability sequence used for rehearsal."""

from __future__ import annotations

from copy import deepcopy


RESIDENT_ID = "resident-mock-001"
ASSET_ID = "asset-mock-fall-001"


def _observation(observation_id, timestamp, feature_name, feature_value, unit, confidence, quality):
    return {
        "schema_version": "1.0",
        "observation_id": observation_id,
        "resident_id": RESIDENT_ID,
        "timestamp": timestamp,
        "source": "pose",
        "feature_name": feature_name,
        "feature_value": feature_value,
        "unit": unit,
        "location": "bedroom",
        "confidence": confidence,
        "data_quality": quality,
        "source_mode": "MOCK",
        "asset_id": ASSET_ID,
        "simulated": True,
        "metadata": {"model_version": "mock-pose-v1"},
    }


def _evidence(evidence_id, observation_id, timestamp, evidence_type, severity, confidence, quality, baseline, current, deviation, explanation):
    return {
        "schema_version": "1.0",
        "evidence_id": evidence_id,
        "observation_ids": [observation_id],
        "resident_id": RESIDENT_ID,
        "timestamp": timestamp,
        "risk_domain": "FALL",
        "evidence_type": evidence_type,
        "severity": severity,
        "confidence": confidence,
        "data_quality": quality,
        "baseline_value": baseline,
        "current_value": current,
        "baseline_deviation": deviation,
        "time_scale": "SHORT",
        "location": "bedroom",
        "explanation": explanation,
        "adapter_version": "fall-adapter-mock-v1",
        "source_mode": "MOCK",
        "simulated": True,
    }


def observations():
    return [
        _observation("obs-mock-green-001", "2026-07-31T03:06:00+08:00", "sit_to_stand_duration", 3.4, "second", 0.95, 0.93),
        _observation("obs-mock-rapid-rise-001", "2026-07-31T03:07:01+08:00", "sit_to_stand_duration", 1.2, "second", 0.92, 0.88),
        _observation("obs-mock-trunk-sway-001", "2026-07-31T03:07:05+08:00", "trunk_sway_angle", 18.0, "degree", 0.90, 0.88),
        _observation("obs-mock-posture-recovered-001", "2026-07-31T03:07:29+08:00", "stable_posture_duration", 15.0, "second", 0.94, 0.90),
        _observation("obs-mock-stable-trunk-angle-001", "2026-07-31T03:07:29+08:00", "stable_trunk_angle_deg", 3.6, "degree", 0.94, 0.90),
        _observation("obs-mock-transition-001", "2026-07-31T03:07:00+08:00", "sit_to_stand_transition_confirmed", 1.0, "boolean", 0.94, 0.90),
        _observation("obs-mock-lateral-drift-001", "2026-07-31T03:07:06+08:00", "post_rise_pelvis_lateral_excursion_norm", 0.48, "body_scale", 0.91, 0.89),
    ]


def evidence():
    return [
        _evidence("evi-mock-green-001", "obs-mock-green-001", "2026-07-31T03:06:00+08:00", "normal_baseline_sample", 0.05, 0.95, 0.93, 3.5, 3.4, -0.1, "起身时长与个人基线基本一致"),
        _evidence("evi-mock-rapid-rise-001", "obs-mock-rapid-rise-001", "2026-07-31T03:07:01+08:00", "rapid_rise", 0.78, 0.92, 0.88, 3.5, 1.2, -2.1, "起身速度明显快于个人基线"),
        _evidence("evi-mock-trunk-sway-001", "obs-mock-trunk-sway-001", "2026-07-31T03:07:05+08:00", "trunk_sway", 0.86, 0.90, 0.88, 5.0, 18.0, 2.8, "起身后躯干出现连续摇晃"),
        _evidence("evi-mock-posture-recovered-001", "obs-mock-posture-recovered-001", "2026-07-31T03:07:29+08:00", "posture_recovered", 0.0, 0.94, 0.90, 15.0, 15.0, 0.0, "躯干最大偏角3.6度，连续稳定15秒，达到15秒恢复阈值"),
        _evidence("evi-mock-transition-001", "obs-mock-transition-001", "2026-07-31T03:07:00+08:00", "sit_to_stand_transition", 0.0, 0.94, 0.90, None, 1.0, None, "已确认有效坐站转换，进入起身后稳定性观察窗口"),
        _evidence("evi-mock-lateral-drift-001", "obs-mock-lateral-drift-001", "2026-07-31T03:07:06+08:00", "post_rise_lateral_drift", 0.82, 0.91, 0.89, None, 0.48, None, "起身后骨盆横向位移超过工程参考阈值"),
    ]


def sequence():
    payload = {"observations": deepcopy(observations()), "evidence": deepcopy(evidence())}
    payload["evidence"][3]["observation_ids"].append("obs-mock-stable-trunk-angle-001")
    payload["evidence"][2]["observation_ids"].append("obs-mock-transition-001")
    payload["evidence"][5]["observation_ids"].append("obs-mock-transition-001")
    return payload
