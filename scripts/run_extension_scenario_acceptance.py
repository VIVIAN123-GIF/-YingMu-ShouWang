"""Run isolated MENTAL/FRAUD structured-scenario engineering validation."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db.database import Base
from backend.db.models import Evidence, Observation, RiskEvent, RuleTrace
from backend.schemas.evidence import EvidenceCreate
from backend.schemas.observation import ObservationCreate
from backend.service.evidence_service import create_evidence
from backend.service.observation_service import create_observation
from backend.service.serialization import loads
from experiments.structured_scenarios.scenarios import (
    GENERATOR_VERSION,
    SCENARIO_KIND,
    build_payloads,
    scenario_catalog,
)


LEVEL_RANK = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}
DISCLAIMER = (
    "This is structured synthetic engineering validation. It is not clinical "
    "accuracy, real fraud-case accuracy, real elderly validation, visitor identity "
    "recognition, or real continuous multi-day monitoring."
)


def _percent(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 2) if denominator else 100.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


async def _run_case(db, scenario: dict[str, Any], index: int) -> dict[str, Any]:
    payloads = build_payloads(scenario, index)
    evaluations = []
    latencies_ms = []
    first_saved = []

    for step_index, pair in enumerate(payloads, start=1):
        observation = ObservationCreate.model_validate(pair["observation"])
        await create_observation(db, observation)
        if pair["evidence"] is None:
            continue
        evidence = EvidenceCreate.model_validate(pair["evidence"])
        started = time.perf_counter()
        _, saved, idempotent, evaluation = await create_evidence(
            db,
            evidence,
            request_id=f"accept-{scenario['scenario_id']}-{step_index}",
        )
        latencies_ms.append((time.perf_counter() - started) * 1000.0)
        first_saved.append(saved and not idempotent)
        evaluations.append({
            "evidence_id": evidence.evidence_id,
            "matched_rule": evaluation["matched_rule"],
            "risk_level": evaluation["risk_level"],
            "next_status": evaluation["next_status"],
            "event_created": evaluation["event_created"],
        })

    evidence_before = (await db.execute(select(func.count(Evidence.id)))).scalar_one()
    event_before = (await db.execute(select(func.count(RiskEvent.id)))).scalar_one()
    duplicate_results = []
    for step_index, pair in enumerate(payloads, start=1):
        if pair["evidence"] is None:
            continue
        evidence = EvidenceCreate.model_validate(pair["evidence"])
        _, saved, idempotent, evaluation = await create_evidence(
            db,
            evidence,
            request_id=f"accept-duplicate-{scenario['scenario_id']}-{step_index}",
        )
        duplicate_results.append({
            "evidence_id": evidence.evidence_id,
            "saved": saved,
            "idempotent": idempotent,
            "matched_rule": evaluation["matched_rule"],
        })
    evidence_after = (await db.execute(select(func.count(Evidence.id)))).scalar_one()
    event_after = (await db.execute(select(func.count(RiskEvent.id)))).scalar_one()

    evidence_rows = (await db.execute(
        select(Evidence).where(Evidence.resident_id == scenario["resident_id"])
    )).scalars().all()
    observation_rows = (await db.execute(
        select(Observation).where(Observation.resident_id == scenario["resident_id"])
    )).scalars().all()
    event = (await db.execute(
        select(RiskEvent).where(
            RiskEvent.resident_id == scenario["resident_id"],
            RiskEvent.primary_domain == scenario["risk_domain"],
        )
    )).scalars().first()
    traces = (await db.execute(
        select(RuleTrace).where(RuleTrace.resident_id == scenario["resident_id"])
    )).scalars().all()

    observation_ids = {row.observation_id for row in observation_rows}
    persisted_types = [row.evidence_type for row in evidence_rows]
    evidence_observation_complete = all(
        set(loads(row.observation_ids, [])).issubset(observation_ids)
        for row in evidence_rows
    )
    event_evidence_complete = event is None or set(loads(event.evidence_ids, [])).issubset(
        {row.evidence_id for row in evidence_rows}
    )
    traced_evidence_ids = {row.evidence_id for row in traces if row.evidence_id}
    trace_complete = all(row.evidence_id in traced_evidence_ids for row in evidence_rows)
    provenance_complete = all(
        row.source_mode == "MOCK"
        and bool(row.simulated)
        and row.adapter_version == GENERATOR_VERSION
        for row in evidence_rows
    ) and all(
        row.source_mode == "MOCK"
        and bool(row.simulated)
        and (metadata := loads(row.extra_metadata, {})).get("scenario_kind") == SCENARIO_KIND
        and metadata.get("generator_version") == GENERATOR_VERSION
        for row in observation_rows
    )

    actual_peak = max(
        (item["risk_level"] for item in evaluations),
        key=lambda level: LEVEL_RANK[level],
        default="GREEN",
    )
    expected = scenario["expected"]
    final_status = event.status if event else None
    event_created = event is not None
    evidence_match = persisted_types == expected["evidence_types"]
    state_match = (
        event_created == expected["event_created"]
        and actual_peak == expected["peak_risk_level"]
        and final_status == expected["final_status"]
    )
    false_escalation = (
        LEVEL_RANK[actual_peak] > LEVEL_RANK[expected["peak_risk_level"]]
    )
    false_trigger = event_created and not expected["event_created"]
    idempotent = (
        evidence_before == evidence_after
        and event_before == event_after
        and all(item["idempotent"] and not item["saved"] for item in duplicate_results)
    )
    traceability_complete = (
        evidence_observation_complete
        and event_evidence_complete
        and trace_complete
        and provenance_complete
    )
    passed = (
        evidence_match
        and state_match
        and not false_trigger
        and not false_escalation
        and idempotent
        and traceability_complete
    )
    return {
        "scenario_id": scenario["scenario_id"],
        "risk_domain": scenario["risk_domain"],
        "category": scenario["category"],
        "source_mode": "MOCK",
        "simulated": True,
        "scenario_kind": SCENARIO_KIND,
        "generator_version": GENERATOR_VERSION,
        "expected": expected,
        "actual": {
            "evidence_types": persisted_types,
            "event_created": event_created,
            "peak_risk_level": actual_peak,
            "final_status": final_status,
            "matched_rules": [item["matched_rule"] for item in evaluations],
        },
        "checks": {
            "evidence_match": evidence_match,
            "state_match": state_match,
            "false_trigger": false_trigger,
            "false_escalation": false_escalation,
            "traceability_complete": traceability_complete,
            "idempotent": idempotent,
        },
        "counts": {
            "observations": len(observation_rows),
            "evidence": len(evidence_rows),
            "events": int(event is not None),
            "rule_traces": len(traces),
        },
        "latency_ms": {
            "samples": len(latencies_ms),
            "p50": _percentile(latencies_ms, 0.50),
            "p95": _percentile(latencies_ms, 0.95),
        },
        "passed": passed,
    }


def _domain_summary(domain: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [case for case in cases if case["risk_domain"] == domain]
    expected_trigger = [case for case in selected if case["expected"]["event_created"]]
    correctly_triggered = sum(case["actual"]["event_created"] for case in expected_trigger)
    closures = [case for case in selected if case["expected"]["closure_required"]]
    closure_success = sum(
        case["actual"]["final_status"] == case["expected"]["final_status"]
        for case in closures
    )
    evidence_count = sum(case["counts"]["evidence"] for case in selected)
    complete_evidence = sum(
        case["counts"]["evidence"]
        for case in selected
        if case["checks"]["traceability_complete"]
    )
    expected_evidence = sum(len(case["expected"]["evidence_types"]) for case in selected)
    matched_evidence = sum(
        len(case["expected"]["evidence_types"])
        for case in selected
        if case["checks"]["evidence_match"]
    )
    return {
        "risk_domain": domain,
        "scenario_count": len(selected),
        "passed_scenarios": sum(case["passed"] for case in selected),
        "expected_evidence_match": {
            "matched": matched_evidence,
            "expected": expected_evidence,
            "percent": _percent(matched_evidence, expected_evidence),
        },
        "scenario_trigger_rate": {
            "triggered": correctly_triggered,
            "expected": len(expected_trigger),
            "percent": _percent(correctly_triggered, len(expected_trigger)),
        },
        "false_trigger_count": sum(case["checks"]["false_trigger"] for case in selected),
        "false_escalation_count": sum(case["checks"]["false_escalation"] for case in selected),
        "evidence_traceability": {
            "complete": complete_evidence,
            "total": evidence_count,
            "percent": _percent(complete_evidence, evidence_count),
        },
        "closure_success": {
            "successful": closure_success,
            "required": len(closures),
            "percent": _percent(closure_success, len(closures)),
        },
        "idempotent_scenarios": sum(case["checks"]["idempotent"] for case in selected),
        "processing_latency_ms": {
            "scenario_p50": _percentile(
                [case["latency_ms"]["p50"] for case in selected], 0.50
            ),
            "scenario_p95": _percentile(
                [case["latency_ms"]["p95"] for case in selected], 0.95
            ),
        },
    }


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# 心理趋势与诈骗核验结构化虚拟场景验证报告",
        "",
        f"> {DISCLAIMER}",
        "",
        f"- 生成器版本：`{GENERATOR_VERSION}`",
        "- 来源：`MOCK`，全部 `simulated=true`",
        f"- 总体结果：**{summary['verdict']}**（{summary['passed_scenarios']}/{summary['scenario_count']} 场景通过）",
        "",
        "| 领域 | 场景通过 | Evidence 匹配 | 场景触发率 | 误触发/误升级 | Evidence 可追溯 | 闭环 | 幂等 | 时延 P50/P95 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for domain in ("MENTAL", "FRAUD"):
        item = summary["domains"][domain]
        lines.append(
            f"| {domain} | {item['passed_scenarios']}/{item['scenario_count']} | "
            f"{item['expected_evidence_match']['matched']}/{item['expected_evidence_match']['expected']} | "
            f"{item['scenario_trigger_rate']['triggered']}/{item['scenario_trigger_rate']['expected']} "
            f"({item['scenario_trigger_rate']['percent']}%) | "
            f"{item['false_trigger_count']}/{item['false_escalation_count']} | "
            f"{item['evidence_traceability']['complete']}/{item['evidence_traceability']['total']} "
            f"({item['evidence_traceability']['percent']}%) | "
            f"{item['closure_success']['successful']}/{item['closure_success']['required']} | "
            f"{item['idempotent_scenarios']}/{item['scenario_count']} | "
            f"{item['processing_latency_ms']['scenario_p50']}/"
            f"{item['processing_latency_ms']['scenario_p95']} |"
        )
    lines.extend([
        "",
        "## 口径说明",
        "",
        "本报告只验证结构化输入下的 Evidence 契约、工程规则触发、事件状态闭环、可追溯性、幂等和处理时延。",
        "不报告心理疾病识别准确率、真实诈骗识别准确率，也不代表真实老人、真实访客或真实连续多日监测验证。",
        "真实视频与现场验证安排在初赛后执行。",
        "",
    ])
    return "\n".join(lines)


async def run_validation(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as db:
            cases = [
                await _run_case(db, scenario, index)
                for index, scenario in enumerate(scenario_catalog())
            ]
    finally:
        await engine.dispose()

    domain_summaries = {
        domain: _domain_summary(domain, cases) for domain in ("MENTAL", "FRAUD")
    }
    summary = {
        "validation_kind": "ENGINEERING_RULE_AND_CLOSURE",
        "source_mode": "MOCK",
        "simulated": True,
        "scenario_kind": SCENARIO_KIND,
        "generator_version": GENERATOR_VERSION,
        "disclaimer": DISCLAIMER,
        "scenario_count": len(cases),
        "passed_scenarios": sum(case["passed"] for case in cases),
        "verdict": "PASS" if all(case["passed"] for case in cases) else "FAIL",
        "domains": domain_summaries,
    }
    files = {
        "scenario-catalog.json": scenario_catalog(),
        "case-results.json": cases,
        "mental-summary.json": domain_summaries["MENTAL"],
        "fraud-summary.json": domain_summaries["FRAUD"],
        "summary.json": summary,
    }
    for filename, payload in files.items():
        (output_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (output_dir / "report.md").write_text(_markdown(summary), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "extension-scenario-acceptance",
    )
    args = parser.parse_args()
    summary = asyncio.run(run_validation(args.output.resolve()))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
