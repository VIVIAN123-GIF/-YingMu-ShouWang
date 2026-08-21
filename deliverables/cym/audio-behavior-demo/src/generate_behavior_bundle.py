"""Generate a behavior bundle from a behavior_demo summary."""

import argparse
import json
from pathlib import Path

from behavior_adapter import build_behavior_batch, build_behavior_bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resident-id", default="resident-001")
    parser.add_argument("--asset-id", default=None)
    parser.add_argument("--location", default=None)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--captured-at", default=None)
    parser.add_argument("--started-at", default=None)
    parser.add_argument("--completed-at", default=None)
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--media-locator", default=None, help="local-only input; never serialized")
    parser.add_argument("--trend-input", type=Path)
    args = parser.parse_args()
    summary = json.loads(args.summary.expanduser().read_text(encoding="utf-8"))
    trend_payload = json.loads(args.trend_input.expanduser().read_text(encoding="utf-8")) if args.trend_input else None
    captured_at = args.captured_at or args.timestamp
    if args.job_id:
        if not all((args.asset_id, args.media_locator, captured_at, args.started_at, args.completed_at)):
            parser.error("--job-id requires --asset-id, --media-locator, --captured-at, --started-at and --completed-at")
        bundle = build_behavior_batch(
            {
                "job_id": args.job_id,
                "asset_id": args.asset_id,
                "media_locator": args.media_locator,
                "captured_at": captured_at,
                "source_mode": summary.get("source_mode"),
                "simulated": summary.get("simulated"),
            },
            summary,
            resident_id=args.resident_id,
            location=args.location,
            trend_payload=trend_payload,
            started_at=args.started_at,
            completed_at=args.completed_at,
        )
    else:
        bundle = build_behavior_bundle(
            summary,
            resident_id=args.resident_id,
            location=args.location,
            asset_id=args.asset_id,
            timestamp=captured_at,
            trend_payload=trend_payload,
        )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(bundle['observations'])} observations and {len(bundle['evidences'])} evidences: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
