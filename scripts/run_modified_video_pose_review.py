"""Run pose analysis on all modified-video clips.

Reuses recorded_replay_adapter's extract_video + analyze_rows helpers so the
output shape matches artifacts/new_video_review/new_video_analysis.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "deliverables" / "zy" / "pose-demo" / "scripts"))

from recorded_replay_adapter import extract_video, sha256_file  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Pose analysis for the modified-video set.")
    parser.add_argument("--video-dir", type=Path, default=REPO_ROOT / "修改后视频" / "视频")
    parser.add_argument("--model", type=Path, default=REPO_ROOT / "models" / "pose_landmarker_heavy.task")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "artifacts" / "modified_video_review" / "modified_video_analysis.json")
    args = parser.parse_args()

    if not args.model.is_file():
        raise SystemExit(f"pose model not found: {args.model}")
    if not args.video_dir.is_dir():
        raise SystemExit(f"video dir not found: {args.video_dir}")

    videos = sorted(p for p in args.video_dir.glob("*.mp4"))
    if not videos:
        raise SystemExit(f"no mp4 videos under {args.video_dir}")

    results = []
    for index, video in enumerate(videos, start=1):
        print(f"[{index}/{len(videos)}] {video.name}", flush=True)
        started = time.time()
        _rows, _landmarks, analysis = extract_video(video, args.model)
        analysis["video"]["file"] = video.name
        analysis["video_sha256"] = sha256_file(video)
        analysis["elapsed_seconds"] = round(time.time() - started, 2)
        results.append(analysis)
        print(
            f"    fps={analysis['video']['fps']:.2f} "
            f"valid={analysis['video']['valid_frame_ratio']:.3f} "
            f"visibility={analysis['quality']['mean_core_visibility']:.3f} "
            f"rapid_rise={analysis['candidates']['rapid_rise']['detected']} "
            f"sway={analysis['candidates']['trunk_sway']['detected']} "
            f"recovery={analysis['candidates']['posture_recovered']['duration_s']:.2f}s",
            flush=True,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {args.output} ({len(results)} clips)")


if __name__ == "__main__":
    main()
