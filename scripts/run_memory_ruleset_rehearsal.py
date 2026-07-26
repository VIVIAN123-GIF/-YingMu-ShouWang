"""Run the deterministic seven-day memory and ruleset-v1.0 rehearsal."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.v1.mock_memory_data import RESIDENT_ID, safe_history  # noqa: E402
from contracts.v1.rehearsal import run_fixed_sequence  # noqa: E402


DEFAULT_LOG = "artifacts/7月26日记忆与规则验收日志.json"
GENERATED_AT = "2026-07-26T21:00:00+08:00"


def run_once() -> dict:
    engine, steps = run_fixed_sequence()
    history = safe_history()
    history_engine = type(engine)()
    for observation, evidence in zip(history["observations"], history["evidence"]):
        history_engine.ingest_observation(observation)
        history_engine.ingest_evidence(evidence)
    baseline_at = datetime.fromisoformat("2026-07-25T12:00:00+08:00")
    decision_at = datetime.fromisoformat("2026-07-31T03:08:30+08:00")
    return {
        "ruleset_version": engine.ruleset.version,
        "source_mode": "MOCK",
        "simulated": True,
        "steps": steps,
        "decision": engine.decision_snapshot(RESIDENT_ID, decision_at),
        "seven_day_baseline": history_engine.memory.snapshot(RESIDENT_ID, baseline_at)["long"]["baseline"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run memory and ruleset-v1.0 acceptance rehearsal")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--log", default=DEFAULT_LOG)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    runs = [run_once() for _ in range(args.runs)]
    if any(item != runs[0] for item in runs[1:]):
        raise SystemExit("FAIL: rehearsal runs are not deterministic")
    payload = {
        "schema_version": "1.0",
        "generated_at": GENERATED_AT,
        "runs_identical": True,
        "run_count": args.runs,
        "runs": runs,
    }
    path = ROOT / args.log
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {args.runs} identical memory/ruleset runs; log={path}")


if __name__ == "__main__":
    main()
