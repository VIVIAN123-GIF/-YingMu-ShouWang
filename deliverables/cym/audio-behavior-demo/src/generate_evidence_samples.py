import argparse
import json
from pathlib import Path

from evidence import build_evidence, validate_evidence_collection


def build_samples():
    return validate_evidence_collection(
        [
            build_evidence(
                evidence_id="evi-mental-activity-range-20260724-0001",
                observation_ids=[
                    "obs-tracking-baseline-range-20260724-0001",
                    "obs-tracking-current-range-20260724-0002",
                ],
                resident_id="resident-001",
                timestamp="2026-07-24T10:00:00+08:00",
                risk_domain="MENTAL",
                evidence_type="activity_range_decline",
                severity=0.62,
                confidence=0.78,
                data_quality=0.82,
                baseline_value=4.0,
                current_value=2.0,
                baseline_deviation=-1.8,
                time_scale="LONG",
                location=None,
                explanation=(
                    "模拟近7日平均活动区域数由个人基线4个降至2个，"
                    "仅提示长期活动范围缩小，建议结合外出、生病和家属反馈复核"
                ),
                adapter_version="behavior-adapter-v1",
                source_mode="MOCK",
                simulated=True,
            ),
            build_evidence(
                evidence_id="evi-fraud-visitor-20260724-0001",
                observation_ids=[
                    "obs-visitor-detection-20260724-0001",
                    "obs-visitor-authorization-check-20260724-0002",
                ],
                resident_id="resident-001",
                timestamp="2026-07-24T14:20:00+08:00",
                risk_domain="FRAUD",
                evidence_type="unauthorized_visitor",
                severity=0.55,
                confidence=0.74,
                data_quality=0.80,
                baseline_value=None,
                current_value=1.0,
                baseline_deviation=None,
                time_scale="SHORT",
                location="living_room",
                explanation=(
                    "模拟检测到1名未匹配授权名单的访客，"
                    "身份尚未确认，建议家属核验"
                ),
                adapter_version="behavior-adapter-v1",
                source_mode="MOCK",
                simulated=True,
            ),
            build_evidence(
                evidence_id="evi-fraud-keyword-20260724-0001",
                observation_ids=[
                    "obs-audio-transcript-20260724-0001",
                    "obs-fraud-keyword-match-20260724-0002",
                ],
                resident_id="resident-001",
                timestamp="2026-07-24T15:10:00+08:00",
                risk_domain="FRAUD",
                evidence_type="fraud_keyword",
                severity=0.72,
                confidence=0.84,
                data_quality=0.78,
                baseline_value=None,
                current_value=3.0,
                baseline_deviation=None,
                time_scale="SHORT",
                location="living_room",
                explanation=(
                    "模拟录音转写命中‘保证收益’，并出现与‘验证码’‘马上转账’"
                    "近音的高风险交互片段，需要结合访客与停留证据核验"
                ),
                adapter_version="speech-adapter-v1",
                source_mode="RECORDED_REPLAY",
                simulated=True,
            ),
        ]
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="生成并校验Freeze v1.0 Evidence样例"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/evidence_samples.json"),
        help="输出JSON路径",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    evidence_items = build_samples()
    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence_items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已生成并校验{len(evidence_items)}条Evidence：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
