import argparse
import json
from datetime import datetime
from pathlib import Path


SCHEMA_VERSION = "1.0"
RUN_ID = "20260803-demo-0001"
RESIDENT_ID = "resident-interface-001"
TIMESTAMP = "2026-08-03T10:00:00+08:00"

OBSERVATION_FIELDS = {
    "schema_version", "observation_id", "resident_id", "timestamp",
    "source", "feature_name", "feature_value", "unit", "location",
    "confidence", "data_quality", "source_mode", "asset_id",
    "simulated", "metadata",
}
EVIDENCE_FIELDS = {
    "schema_version", "evidence_id", "observation_ids", "resident_id",
    "timestamp", "risk_domain", "evidence_type", "severity", "confidence",
    "data_quality", "baseline_value", "current_value", "baseline_deviation",
    "time_scale", "location", "explanation", "adapter_version",
    "source_mode", "simulated",
}


def observation(observation_id, source, feature_name, feature_value, unit,
                source_mode, asset_id, metadata, confidence, data_quality):
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_id": observation_id,
        "resident_id": RESIDENT_ID,
        "timestamp": TIMESTAMP,
        "source": source,
        "feature_name": feature_name,
        "feature_value": feature_value,
        "unit": unit,
        "location": "living_room",
        "confidence": confidence,
        "data_quality": data_quality,
        "source_mode": source_mode,
        "asset_id": asset_id,
        "simulated": True,
        "metadata": metadata,
    }


def build_samples():
    voice_observations = [
        observation(
            f"obs-audio-transcript-{RUN_ID}",
            "audio",
            "audio_transcript",
            "保证收益，请告诉我验证码并马上转账。",
            None,
            "RECORDED_REPLAY",
            "asset-synthetic-audio-20260803-0001",
            {
                "adapter_version": "speech-adapter-v1.1",
                "model": "interface-sample",
                "language": "Chinese",
                "interpretation": "HIGH_RISK_INTERACTION_FEATURE_ONLY",
            },
            0.82,
            0.85,
        ),
        observation(
            f"obs-audio-keyword-count-{RUN_ID}",
            "audio",
            "fraud_keyword_match_count",
            3,
            "count",
            "RECORDED_REPLAY",
            "asset-synthetic-audio-20260803-0001",
            {
                "adapter_version": "speech-adapter-v1.1",
                "matched_labels": [
                    "guaranteed_return",
                    "verification_code_like",
                    "immediate_transfer",
                ],
                "score_status": "DEMO_UNCALIBRATED",
                "interpretation": "HIGH_RISK_INTERACTION_FEATURE_ONLY",
            },
            0.82,
            0.85,
        ),
    ]
    voice_evidence = {
        "schema_version": SCHEMA_VERSION,
        "evidence_id": f"evi-fraud-keyword-{RUN_ID}",
        "observation_ids": [item["observation_id"] for item in voice_observations],
        "resident_id": RESIDENT_ID,
        "timestamp": TIMESTAMP,
        "risk_domain": "FRAUD",
        "evidence_type": "fraud_keyword",
        "severity": 0.72,
        "confidence": 0.82,
        "data_quality": 0.85,
        "baseline_value": None,
        "current_value": 3.0,
        "baseline_deviation": None,
        "time_scale": "SHORT",
        "location": "living_room",
        "explanation": (
            "模拟录音回放转写命中3类高风险交互话术；该结果只表示需要核验的"
            "交互特征，不直接判断诈骗"
        ),
        "adapter_version": "speech-adapter-v1.1",
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
    }

    behavior_metadata = {
        "adapter_version": "behavior-adapter-v1.1",
        "threshold_status": "DEMO_UNCALIBRATED",
        "purpose": "interface_rehearsal",
    }
    behavior_observations = [
        observation(
            f"obs-activity-baseline-{RUN_ID}",
            "behavior_statistics",
            "baseline_visited_region_count",
            4,
            "count",
            "MOCK",
            None,
            behavior_metadata,
            0.78,
            0.80,
        ),
        observation(
            f"obs-activity-current-{RUN_ID}",
            "behavior_statistics",
            "current_visited_region_count",
            2,
            "count",
            "MOCK",
            None,
            behavior_metadata,
            0.78,
            0.80,
        ),
    ]
    behavior_evidence = {
        "schema_version": SCHEMA_VERSION,
        "evidence_id": f"evi-activity-range-{RUN_ID}",
        "observation_ids": [item["observation_id"] for item in behavior_observations],
        "resident_id": RESIDENT_ID,
        "timestamp": TIMESTAMP,
        "risk_domain": "MENTAL",
        "evidence_type": "activity_range_decline",
        "severity": 0.50,
        "confidence": 0.78,
        "data_quality": 0.80,
        "baseline_value": 4.0,
        "current_value": 2.0,
        "baseline_deviation": -2.0,
        "time_scale": "LONG",
        "location": "living_room",
        "explanation": (
            "模拟多日统计显示当前访问区域数低于个人基线；仅表示活动范围变化，"
            "需要结合外出、生病和家属反馈复核，不作心理诊断"
        ),
        "adapter_version": "behavior-adapter-v1.1",
        "source_mode": "MOCK",
        "simulated": True,
    }
    return voice_observations, voice_evidence, behavior_observations, behavior_evidence


def validate_group(observations, evidence):
    timestamp = datetime.fromisoformat(evidence["timestamp"].replace("Z", "+00:00"))
    if timestamp.utcoffset() is None:
        raise ValueError("timestamp必须包含时区")
    if set(evidence) != EVIDENCE_FIELDS:
        raise ValueError("Evidence字段与Freeze v1.0不一致")
    for item in observations:
        if set(item) != OBSERVATION_FIELDS:
            raise ValueError("Observation字段与Freeze v1.0不一致")
        if any(not 0 <= item[name] <= 1 for name in ("confidence", "data_quality")):
            raise ValueError("Observation分数必须在0到1")
    if any(not 0 <= evidence[name] <= 1 for name in ("severity", "confidence", "data_quality")):
        raise ValueError("Evidence分数必须在0到1")
    observation_ids = {item["observation_id"] for item in observations}
    if not set(evidence["observation_ids"]).issubset(observation_ids):
        raise ValueError("Evidence引用了不存在的Observation")
    for item in observations:
        if (
            item["resident_id"] != evidence["resident_id"]
            or item["source_mode"] != evidence["source_mode"]
            or item["simulated"] != evidence["simulated"]
        ):
            raise ValueError("Evidence未继承Observation来源字段")


def write_json(path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description="生成Freeze v1.0语音与行为接口样例")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="交付包根目录",
    )
    args = parser.parse_args()
    root = args.output.expanduser().resolve()
    (root / "voice").mkdir(parents=True, exist_ok=True)
    (root / "behavior").mkdir(parents=True, exist_ok=True)

    voice_obs, voice_evi, behavior_obs, behavior_evi = build_samples()
    validate_group(voice_obs, voice_evi)
    validate_group(behavior_obs, behavior_evi)

    files = [
        ("voice/01-observation-transcript.json", voice_obs[0]),
        ("voice/02-observation-keyword-count.json", voice_obs[1]),
        ("voice/03-evidence-fraud-keyword.json", voice_evi),
        ("behavior/01-observation-baseline-range.json", behavior_obs[0]),
        ("behavior/02-observation-current-range.json", behavior_obs[1]),
        ("behavior/03-evidence-activity-range-decline.json", behavior_evi),
    ]
    for relative_path, payload in files:
        write_json(root / relative_path, payload)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "description": "Freeze v1.0语音与行为后端接口兼容样例",
        "request_order": [path for path, _ in files],
        "notes": [
            "每个JSON文件是一个独立POST请求体",
            "每组必须先提交Observation，再提交Evidence",
            "全部内容为模拟或合成回放，不包含真实个人数据",
        ],
    }
    write_json(root / "manifest.json", manifest)
    print(f"已生成并校验6个请求JSON：{root}")


if __name__ == "__main__":
    main()
