"""Run contracts/v1/gait_adapter.run against all 23 samples in the integration zip.

Outputs artifacts/gait_preflight/preflight_report.json with actual adapter output
for each MP4 — used as ground truth to rebuild manifest.csv.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.v1.gait_adapter import AlgorithmJob, run  # noqa: E402


NORMAL_DIR = ROOT / "修改后视频" / "视频"
RISK_DIR = ROOT / "新视频"

# (relpath in zip, source path, group, scene, resident, device_ref, camera, auth, captured_at)
SAMPLES = []
for day in ("D1", "D2", "D3"):
    for scene, base in (
        ("WALK", f"{day}_WALK_01_left_to_right"),
        ("WALK", f"{day}_WALK_02_right_to_left"),
        ("WALK", f"{day}_WALK_03_left_to_right"),
        ("RISE", f"{day}_RISE_01_chair_C"),
        ("RISE", f"{day}_RISE_02_chair_C"),
        ("STABLE", f"{day}_STABLE_01_stable_S"),
    ):
        mp4 = NORMAL_DIR / f"{base}.mp4"
        if not mp4.exists():
            mp4 = NORMAL_DIR / f"{base}(1).mp4"
        SAMPLES.append({
            "file_relpath": f"normal/{day}/{mp4.name}",
            "source_path": mp4,
            "group": "normal",
            "scene": scene,
            "resident_id": "resident-modified-video-001",
            "device_ref": "device-ref-c6c-modified-video-001",
            "camera_position_id": "camera-position-modified-video-001",
            "authorization_record_id": "auth-modified-video-local-20260822",
        })

for label, num, scene in (
    ("golden", 4, "GOLDEN"),
    ("rapid_rise", 5, "RAPID_RISE"),
    ("under15", 6, "UNDER15"),
    ("rapid_rise", 7, "RAPID_RISE"),
    ("trunk_sway", 8, "TRUNK_SWAY"),
):
    SAMPLES.append({
        "file_relpath": f"controlled_risk/{num}_{label}.mp4",
        "source_path": RISK_DIR / f"{num}.mp4",
        "group": "controlled_risk",
        "scene": scene,
        "resident_id": "resident-new-video-001",
        "device_ref": "device-ref-c6c-new-video-001",
        "camera_position_id": "camera-position-new-video-001",
        "authorization_record_id": "auth-new-video-local-20260816",
    })


async def run_one(sample: dict) -> dict:
    job = AlgorithmJob(
        job_id=f"preflight-{sample['file_relpath'].replace('/', '-').replace('.mp4', '')}",
        resident_id=sample["resident_id"],
        asset_id=f"asset-preflight-{sample['scene'].lower()}-{sample['file_relpath'].replace('/', '-').replace('.mp4', '')}",
        media_type="video/mp4",
        media_locator=str(sample["source_path"]),
        model_path=str(ROOT / "models" / "pose_landmarker_heavy.task"),
        captured_at="2026-08-24T09:00:00+08:00",
        source_mode="RECORDED_REPLAY",
        simulated=True,
        location="living_room",
        camera_position_id=sample["camera_position_id"],
        scene_config_id="preflight",
    )
    batch = await run(job)
    return {
        "file_relpath": sample["file_relpath"],
        "group": sample["group"],
        "scene": sample["scene"],
        "status": batch.status,
        "evidence_types": [e.evidence_type for e in batch.evidences],
        "feature_names": [o.feature_name for o in batch.observations],
        "diagnostics": {
            k: v for k, v in batch.diagnostics.items()
            if k in ("fps", "total_frames", "detected_frames", "valid_frame_ratio",
                     "quality_reason", "error_code", "module_status", "quality_threshold")
        },
        "feature_values": {
            o.feature_name: o.feature_value
            for o in batch.observations
        },
        "error": batch.error,
    }


async def main() -> None:
    print(f"preflight on {len(SAMPLES)} samples ...")
    results = []
    for index, sample in enumerate(SAMPLES, start=1):
        if not sample["source_path"].exists():
            results.append({
                "file_relpath": sample["file_relpath"],
                "status": "SOURCE_MISSING",
                "source_path": str(sample["source_path"]),
            })
            continue
        print(f"[{index}/{len(SAMPLES)}] {sample['file_relpath']}", flush=True)
        result = await run_one(sample)
        results.append(result)
        print(
            f"    status={result['status']} "
            f"evidence={','.join(result['evidence_types']) or '<none>'} "
            f"valid_frame_ratio={result['diagnostics'].get('valid_frame_ratio')}",
            flush=True,
        )

    out_dir = ROOT / "artifacts" / "gait_preflight"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "preflight_report.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}")

    normal_success = [r for r in results if r.get("group") == "normal" and r["status"] == "SUCCESS"]
    normal_ne = [r for r in results if r.get("group") == "normal" and r["status"] == "NO_EVIDENCE"]
    risk_success = [r for r in results if r.get("group") == "controlled_risk" and r["status"] == "SUCCESS"]
    print(f"normal: SUCCESS={len(normal_success)}  NO_EVIDENCE={len(normal_ne)}")
    print(f"controlled_risk: SUCCESS={len(risk_success)}")


if __name__ == "__main__":
    asyncio.run(main())
