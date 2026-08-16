"""Run one redacted live validation against the configured explanation model."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import AGENT_LLM_API_KEY, AGENT_LLM_BASE_URL, AGENT_LLM_MODEL
from backend.service.agent_explanation_service import build_default_agent_explanation_service


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUEST = ROOT / "contracts" / "v1" / "examples" / "agent_explanation_request.json"
DEFAULT_OUTPUT = ROOT / "deliverables" / "zhang-d3-agent-llm" / "ezviz-qwen-live-validation.json"
TZ = timezone(timedelta(hours=8))


async def validate(request_path: Path) -> dict:
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    service = build_default_agent_explanation_service()
    started = time.perf_counter()
    response = await service.explain_payload(payload)
    latency_ms = round((time.perf_counter() - started) * 1000)
    return {
        "schema_version": "1.0",
        "test_kind": "EZVIZ_TOKEN_SWITCH_AGENT_LIVE_VALIDATION",
        "generated_at": datetime.now(TZ).isoformat(timespec="milliseconds"),
        "provider": "EZVIZ_TOKEN_SWITCH_OPENAI_COMPATIBLE",
        "model": AGENT_LLM_MODEL,
        "request_id": response.request_id,
        "event_id": response.event_id,
        "latency_ms": latency_ms,
        "fallback_used": response.fallback_used,
        "generated_by": response.generated_by,
        "result": "SUCCESS" if not response.fallback_used else "FALLBACK",
        "response": response.model_dump(mode="json"),
        "contains_api_key": False,
        "contains_media": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the configured Ezviz text-model API once.")
    parser.add_argument("--request", type=Path, default=DEFAULT_REQUEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not AGENT_LLM_BASE_URL or not AGENT_LLM_MODEL or not AGENT_LLM_API_KEY:
        print("configuration incomplete: set AGENT_LLM_BASE_URL, AGENT_LLM_MODEL and AGENT_LLM_API_KEY")
        return 2
    request_path = args.request if args.request.is_absolute() else ROOT / args.request
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    report = asyncio.run(validate(request_path))
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if AGENT_LLM_API_KEY in serialized:
        raise RuntimeError("validation report contains API key")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialized, encoding="utf-8")
    print(
        f"result={report['result']} model={report['model']} "
        f"latency_ms={report['latency_ms']} report={output_path}"
    )
    return 0 if report["result"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
