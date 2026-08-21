"""Validate a batch algorithm sample file against the backend's frozen API schemas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.schemas.evidence import EvidenceCreate
from backend.schemas.observation import ObservationCreate


def load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON 文件 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("批量样例必须是一个 JSON 对象")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="校验算法批量样例中的所有 Observation/Evidence 场景。")
    parser.add_argument("--samples", required=True, type=Path, help="包含 scenarios 数组的 JSON 文件")
    args = parser.parse_args()

    try:
        payload = load_json(args.samples)
        scenarios = payload.get("scenarios")
        if not isinstance(scenarios, list) or not scenarios:
            raise ValueError("samples.scenarios 必须是非空数组")
        for item in scenarios:
            if not isinstance(item, dict) or not isinstance(item.get("scenario"), str):
                raise ValueError("每个场景必须包含 scenario 名称")
            observation = ObservationCreate.model_validate(item.get("observation"))
            evidence = EvidenceCreate.model_validate(item.get("evidence"))
            if observation.observation_id not in evidence.observation_ids:
                raise ValueError(
                    f"{item['scenario']}: Evidence 必须关联本场景 Observation"
                )
            if (
                observation.resident_id != evidence.resident_id
                or observation.source_mode != evidence.source_mode
                or observation.simulated != evidence.simulated
            ):
                raise ValueError(
                    f"{item['scenario']}: Observation/Evidence 的 resident_id、source_mode、simulated 必须一致"
                )
            print(f"PASS {item['scenario']}: {evidence.risk_domain.value}/{evidence.evidence_type}")
    except ValueError as exc:
        raise SystemExit(f"VALIDATION_FAILED: {exc}") from exc


if __name__ == "__main__":
    main()
