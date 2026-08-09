from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local fall Evidence adapter and print JSON for integration.")
    parser.add_argument("--sequence-id", default="", help="Optional processed sequence id.")
    parser.add_argument("--frames-csv", default="deliverables/zy/pose-demo/processed/urfd_pose_cleaned_frames.csv")
    parser.add_argument("--features-csv", default="deliverables/zy/pose-demo/processed/urfd_gait_features.csv")
    parser.add_argument("--baseline-profile", default="deliverables/zy/pose-demo/baseline/baseline_profile.json")
    parser.add_argument("--evidence-dir", default="deliverables/zy/pose-demo/evidence")
    parser.add_argument("--integration-dir", default="deliverables/zy/pose-demo/integration")
    args = parser.parse_args()

    command = [
        sys.executable,
        "deliverables/zy/pose-demo/scripts/build_fall_evidence_package.py",
        "--frames-csv",
        args.frames_csv,
        "--features-csv",
        args.features_csv,
        "--baseline-profile",
        args.baseline_profile,
        "--evidence-dir",
        args.evidence_dir,
        "--integration-dir",
        args.integration_dir,
    ]
    if args.sequence_id:
        command.extend(["--sequence-id", args.sequence_id])
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    batch_path = Path(args.evidence_dir) / "fall_evidence_batch.json"
    with batch_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
