"""Run and record the fixed 7/31 Mock integration sequence three times."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.v1.rehearsal import run_fixed_sequence  # noqa: E402


DEFAULT_GENERATED_AT = "2026-07-25T16:50:37+08:00"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the deterministic fall Mock sequence")
    parser.add_argument("--runs", type=int, default=3, help="number of complete reproductions")
    parser.add_argument("--log", default="artifacts/7月25日Mock联调运行日志.json", help="UTF-8 JSON log path")
    parser.add_argument(
        "--generated-at",
        default=DEFAULT_GENERATED_AT,
        help="fixed ISO 8601 timestamp for a reproducible tracked log",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    try:
        generated_at = datetime.fromisoformat(args.generated_at.replace("Z", "+00:00"))
    except ValueError:
        parser.error("--generated-at must be an ISO 8601 timestamp")
    if generated_at.utcoffset() is None:
        parser.error("--generated-at must include a timezone")

    runs = []
    expected_snapshot = None
    for number in range(1, args.runs + 1):
        engine, steps = run_fixed_sequence()
        snapshot = engine.snapshot()
        if expected_snapshot is None:
            expected_snapshot = snapshot
        assert snapshot == expected_snapshot, "run output changed between reproductions"
        runs.append({"run": number, "status": "PASSED", "tool_calls": engine.tool_call_count, "steps": steps})

    payload = {
        "schema_version": "1.0",
        "generated_at": args.generated_at,
        "simulated": True,
        "source_mode": "MOCK",
        "runs": runs,
        "final_event": expected_snapshot["events"][0],
        "final_intervention": expected_snapshot["interventions"][0],
    }
    log_path = ROOT / args.log
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {args.runs} identical runs; one tool call per run; log={log_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
