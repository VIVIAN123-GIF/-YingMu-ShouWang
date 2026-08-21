"""Generate a speech bundle from a redacted/in-memory transcript source."""

import argparse
import json
from pathlib import Path

from audio_evidence import build_audio_batch, build_audio_bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", type=Path, required=True)
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
    parser.add_argument("--source-mode", choices=("LIVE_DEVICE", "RECORDED_REPLAY", "PUBLIC_DATASET", "MOCK"), default="RECORDED_REPLAY")
    parser.add_argument("--simulated", action="store_true")
    parser.add_argument("--quality-metrics", type=Path)
    args = parser.parse_args()
    transcript = args.transcript.expanduser().read_text(encoding="utf-8")
    metrics = json.loads(args.quality_metrics.expanduser().read_text(encoding="utf-8")) if args.quality_metrics else None
    captured_at = args.captured_at or args.timestamp
    if args.job_id:
        if not all((args.asset_id, args.media_locator, captured_at, args.started_at, args.completed_at)):
            parser.error("--job-id requires --asset-id, --media-locator, --captured-at, --started-at and --completed-at")
        bundle = build_audio_batch(
            {
                "job_id": args.job_id,
                "asset_id": args.asset_id,
                "media_locator": args.media_locator,
                "captured_at": captured_at,
                "source_mode": args.source_mode,
                "simulated": args.simulated,
            },
            transcript,
            resident_id=args.resident_id,
            source_mode=args.source_mode,
            location=args.location,
            simulated=args.simulated,
            quality_metrics=metrics,
            started_at=args.started_at,
            completed_at=args.completed_at,
        )
    else:
        bundle = build_audio_bundle(
            transcript,
            resident_id=args.resident_id,
            source_mode=args.source_mode,
            location=args.location,
            asset_id=args.asset_id,
            simulated=args.simulated,
            quality_metrics=metrics,
            timestamp=captured_at,
        )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(bundle['observations'])} observations and {len(bundle['evidences'])} evidences: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
