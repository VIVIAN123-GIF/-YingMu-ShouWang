"""Build v4.2 GAIT integration supplement zip.

v4.2 extends v4.1 with a third controlled_risk segment that triggers both
`rapid_rise` and `trunk_sway` inside a single AdapterBatch — the condition
R-FALL-02 needs to CREATE_EVENT in the backend combination layer. Reviewer
feedback on 2026-08-24: v4.1 verified adapter + Worker ingest + idempotency,
but the risk-combination rule blocks on a missing trunk_sway pair; without a
sample that satisfies R-FALL-02 the pipeline cannot produce RiskEvent /
AgentJob evidence.

Content vs v4.1:
  * `normal/D1_WALK_02_right_to_left.mp4` — unchanged (720p hvc1 source).
  * `controlled_risk/5_rapid_rise_720p.mp4` — unchanged (720p H.264 transcode).
  * `controlled_risk/golden_20s_720p_h264.mp4` — NEW.
      * Source: `视频/视频/完整黄金闭环视频.mp4` (960x544, avc1, 127.43s).
      * Window: 10s..30s (20.0 seconds) chosen because it contains both the
        rapid-rise event (rise_duration_s = 0.4s) and the trunk-sway peak
        (trunk_sway_angle_deg ≈ 17.18°, above the 12° gate).
      * Encoded to 1280x720 (via -2:720 scaler, output 1270x720) H.264 avc1,
        yuv420p, +faststart, 15 fps, no audio.
      * Expected adapter output (regenerated on run): SUCCESS with evidence
        {rapid_rise, trunk_sway, relative_speed_change} — the rapid_rise +
        trunk_sway pair satisfies R-FALL-02's short-window condition (both
        Evidence timestamps use job.captured_at, so their delta is 0s, well
        under short_seconds=30).

Run:
    .venv/Scripts/python.exe scripts/build_gait_10min_v4_2_supplement.py
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import platform
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.v1.algorithm import AlgorithmJob, AlgorithmModule, MediaType  # noqa: E402
from contracts.v1.gait_adapter import run as gait_run  # noqa: E402
import contracts.v1.gait_adapter as gait_adapter_mod  # noqa: E402
import contracts.v1.gait_video as gait_video_mod  # noqa: E402

TZ = timezone(timedelta(hours=8))

NORMAL_SOURCE = ROOT / "修改后视频" / "视频" / "D1_WALK_02_right_to_left.mp4"
NORMAL_RELPATH = "normal/D1_WALK_02_right_to_left.mp4"
NORMAL_CAPTURED_AT = datetime(2026, 8, 18, 15, 7, 35, tzinfo=TZ)

RISK_SOURCE = ROOT / "新视频" / "5.mp4"
RISK_DEST_RELPATH = "controlled_risk/5_rapid_rise_720p.mp4"
RISK_CAPTURED_AT = datetime(2026, 8, 15, 20, 25, 9, tzinfo=TZ)  # overridden in main() from file mtime

GOLDEN_SOURCE = ROOT / "视频" / "视频" / "完整黄金闭环视频.mp4"
GOLDEN_DEST_RELPATH = "controlled_risk/golden_20s_720p_h264.mp4"
GOLDEN_WINDOW_START = 10.0
GOLDEN_WINDOW_DURATION = 20.0
GOLDEN_CAPTURED_AT = datetime(2026, 8, 3, 15, 20, 0, tzinfo=TZ)

OUT_ZIP = ROOT / "deliverables" / "zy" / "GAIT_联调_v4_2_supplement.zip"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def probe_video(ffmpeg_bin: str, path: Path) -> dict:
    ffprobe = ffmpeg_bin.replace("ffmpeg", "ffprobe")
    if not Path(ffprobe).exists():
        proc = subprocess.run([ffmpeg_bin, "-i", str(path), "-hide_banner"], capture_output=True, text=True)
        import re

        text = proc.stderr
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
        dur = float(m.group(1)) * 3600 + float(m.group(2)) * 60 + float(m.group(3)) if m else None
        m = re.search(r"Video:\s+([^,]+),.*?\b(\d{2,5})x(\d{2,5})\b", text)
        codec, w, h = (m.group(1).strip(), int(m.group(2)), int(m.group(3))) if m else (None, None, None)
        m = re.search(r"(\d+(?:\.\d+)?)\s*fps", text)
        fps = float(m.group(1)) if m else None
        return {"codec": codec, "width": w, "height": h, "fps": fps, "duration_s": dur, "nb_frames": None}

    proc = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,r_frame_rate,nb_frames:format=duration",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    info = json.loads(proc.stdout)
    stream = info["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) != 0 else None
    return {
        "codec": stream.get("codec_name"),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": fps,
        "duration_s": float(info["format"]["duration"]),
        "nb_frames": int(stream["nb_frames"]) if stream.get("nb_frames", "").isdigit() else None,
    }


def transcode(ffmpeg_bin: str, src: Path, dst: Path, *, ss: float | None = None, t: float | None = None) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    probe_src = probe_video(ffmpeg_bin, src)

    cmd = [ffmpeg_bin, "-y"]
    if ss is not None:
        cmd += ["-ss", f"{ss}"]
    cmd += ["-i", str(src)]
    if t is not None:
        cmd += ["-t", f"{t}"]
    cmd += [
        "-vf", "scale=-2:720:flags=lanczos",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg failed for {src}: {proc.stderr[-2000:]}")

    probe_dst = probe_video(ffmpeg_bin, dst)
    return {
        "source": probe_src,
        "output": probe_dst,
        "ffmpeg": ffmpeg_bin,
        "window": None if ss is None else {"start_s": ss, "duration_s": t},
    }


async def adapter_run(name: str, media_path: Path, captured_at: datetime, resident_id: str, camera_position_id: str) -> dict:
    job = AlgorithmJob(
        schema_version="algorithm-job/1.0",
        job_id=f"v42-preflight-{name}",
        correlation_id=f"corr-v42-preflight-{name}",
        resident_id=resident_id,
        asset_id=f"asset-v42-{name}",
        media_type=MediaType.VIDEO,
        media_locator=str(media_path),
        captured_at=captured_at,
        source_mode="RECORDED_REPLAY",
        simulated=True,
        location="living_room",
        camera_position_id=camera_position_id,
        scene_config_id=f"v42-preflight-{name}",
        requested_modules=[AlgorithmModule.GAIT],
    )
    batch = await gait_run(job)
    return {
        "job_id": job.job_id,
        "correlation_id": job.correlation_id,
        "asset_id": job.asset_id,
        "resident_id": resident_id,
        "captured_at": captured_at.isoformat(timespec="seconds"),
        "status": batch.status.value if hasattr(batch.status, "value") else batch.status,
        "evidence": [e.evidence_type for e in batch.evidences],
        "evidence_timestamps": [e.timestamp.isoformat(timespec="seconds") if hasattr(e.timestamp, 'isoformat') else str(e.timestamp) for e in batch.evidences],
        "observations": {o.feature_name: o.feature_value for o in batch.observations},
        "diagnostics": {k: batch.diagnostics.get(k) for k in ("fps", "duration_s", "frames_processed", "pose_frames", "feature_source_type", "video_format", "pose_model", "quality_threshold")},
        "error": batch.error.model_dump() if batch.error is not None else None,
    }


def git_head() -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()


def git_last_commit(relpath: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "log", "-1", "--format=%h %s", "--", relpath],
        text=True,
    ).strip()


MANIFEST_FIELDS = [
    "group", "file_relpath", "scene", "captured_at", "captured_at_source",
    "resident_id", "device_model", "device_ref", "camera_position_id",
    "authorization_status", "authorization_record_id", "source_mode", "simulated",
    "module_scope", "resolution", "codec", "fps", "duration_s", "sha256",
    "expected_status", "expected_evidence", "expected_backend_risk", "expected_rule_id",
]


def build_manifest_rows(probes: dict, shas: dict, snapshot: list[dict]) -> list[dict]:
    normal_row = {
        "group": "normal",
        "file_relpath": NORMAL_RELPATH,
        "scene": "WALK",
        "captured_at": NORMAL_CAPTURED_AT.isoformat(timespec="seconds"),
        "captured_at_source": "docx_or_source_metadata",
        "resident_id": "resident-modified-video-001",
        "device_model": "EZVIZ_C6C",
        "device_ref": "device-ref-c6c-modified-video-001",
        "camera_position_id": "camera-position-modified-video-001",
        "authorization_status": "AUTHORIZED",
        "authorization_record_id": "auth-modified-video-local-20260822",
        "source_mode": "RECORDED_REPLAY",
        "simulated": "true",
        "module_scope": "GAIT",
        "resolution": f"{probes['normal']['width']}x{probes['normal']['height']}",
        "codec": probes["normal"]["codec"],
        "fps": f"{probes['normal']['fps']:.3f}" if probes["normal"]["fps"] else "",
        "duration_s": f"{probes['normal']['duration_s']:.3f}" if probes["normal"]["duration_s"] else "",
        "sha256": shas["normal"],
        "expected_status": snapshot[0]["status"],
        "expected_evidence": "; ".join(snapshot[0]["evidence"]),
        "expected_backend_risk": "GREEN",
        "expected_rule_id": "NO_MATCH",
    }
    risk_row = {
        "group": "controlled_risk",
        "file_relpath": RISK_DEST_RELPATH,
        "scene": "RAPID_RISE",
        "captured_at": RISK_CAPTURED_AT.isoformat(timespec="seconds"),
        "captured_at_source": "file_mtime",
        "resident_id": "resident-new-video-001",
        "device_model": "EZVIZ_C6C",
        "device_ref": "device-ref-c6c-new-video-001",
        "camera_position_id": "camera-position-new-video-001",
        "authorization_status": "AUTHORIZED",
        "authorization_record_id": "auth-new-video-local-20260816",
        "source_mode": "RECORDED_REPLAY",
        "simulated": "true",
        "module_scope": "GAIT",
        "resolution": f"{probes['risk']['width']}x{probes['risk']['height']}",
        "codec": probes["risk"]["codec"],
        "fps": f"{probes['risk']['fps']:.3f}" if probes["risk"]["fps"] else "",
        "duration_s": f"{probes['risk']['duration_s']:.3f}" if probes["risk"]["duration_s"] else "",
        "sha256": shas["risk"],
        "expected_status": snapshot[1]["status"],
        "expected_evidence": "; ".join(snapshot[1]["evidence"]),
        "expected_backend_risk": "GREEN",
        "expected_rule_id": "R-FALL-01",
    }
    golden_row = {
        "group": "controlled_risk_golden",
        "file_relpath": GOLDEN_DEST_RELPATH,
        "scene": "RAPID_RISE_AND_TRUNK_SWAY",
        "captured_at": GOLDEN_CAPTURED_AT.isoformat(timespec="seconds"),
        "captured_at_source": "field_capture_metadata",
        "resident_id": "resident-golden-loop-001",
        "device_model": "EZVIZ_C6C",
        "device_ref": "device-ref-c6c-golden-loop-001",
        "camera_position_id": "camera-position-golden-loop-001",
        "authorization_status": "AUTHORIZED",
        "authorization_record_id": "auth-golden-loop-local-20260803",
        "source_mode": "RECORDED_REPLAY",
        "simulated": "true",
        "module_scope": "GAIT",
        "resolution": f"{probes['golden']['width']}x{probes['golden']['height']}",
        "codec": probes["golden"]["codec"],
        "fps": f"{probes['golden']['fps']:.3f}" if probes["golden"]["fps"] else "",
        "duration_s": f"{probes['golden']['duration_s']:.3f}" if probes["golden"]["duration_s"] else "",
        "sha256": shas["golden"],
        "expected_status": snapshot[2]["status"],
        "expected_evidence": "; ".join(snapshot[2]["evidence"]),
        "expected_backend_risk": "ORANGE",
        "expected_rule_id": "R-FALL-02",
    }
    return [normal_row, risk_row, golden_row]


ALGORITHM_JOB_TEMPLATE = {
    "normal": {
        "schema_version": "algorithm-job/1.0",
        "job_id": "job-2026-08-24-gait-v42-normal",
        "correlation_id": "corr-2026-08-24-gait-v42-normal",
        "resident_id": "resident-modified-video-001",
        "asset_id": "asset-v42-normal-walk",
        "media_type": "VIDEO",
        "media_locator": NORMAL_RELPATH,
        "captured_at": None,
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "location": "living_room",
        "camera_position_id": "camera-position-modified-video-001",
        "scene_config_id": "scene-v42-normal",
        "requested_modules": ["GAIT"],
    },
    "risk": {
        "schema_version": "algorithm-job/1.0",
        "job_id": "job-2026-08-24-gait-v42-risk",
        "correlation_id": "corr-2026-08-24-gait-v42-risk",
        "resident_id": "resident-new-video-001",
        "asset_id": "asset-v42-risk-rapid-rise",
        "media_type": "VIDEO",
        "media_locator": RISK_DEST_RELPATH,
        "captured_at": None,
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "location": "living_room",
        "camera_position_id": "camera-position-new-video-001",
        "scene_config_id": "scene-v42-risk",
        "requested_modules": ["GAIT"],
    },
    "golden": {
        "schema_version": "algorithm-job/1.0",
        "job_id": "job-2026-08-24-gait-v42-golden",
        "correlation_id": "corr-2026-08-24-gait-v42-golden",
        "resident_id": "resident-golden-loop-001",
        "asset_id": "asset-v42-golden-rise-and-sway",
        "media_type": "VIDEO",
        "media_locator": GOLDEN_DEST_RELPATH,
        "captured_at": None,
        "source_mode": "RECORDED_REPLAY",
        "simulated": True,
        "location": "living_room",
        "camera_position_id": "camera-position-golden-loop-001",
        "scene_config_id": "scene-v42-golden",
        "requested_modules": ["GAIT"],
    },
    "_notes": [
        "本批次 module_scope=GAIT，仅执行 GAIT adapter",
        "media_locator 是相对 zip 解压后根目录的路径",
        "captured_at 已带 +08:00 时区",
        "source_mode 固定 RECORDED_REPLAY, simulated 固定 true",
        "controlled_risk_golden 段用于验证后端 R-FALL-02 组合层",
    ],
}


def build_readme(identity: dict, manifest_rows: list[dict], snapshot: list[dict]) -> str:
    lines = [
        "# GAIT 10 分钟联调 v4.2 补充包（2026-08-24）",
        "",
        "## 相对 v4.1 的差异",
        "",
        "冷同学 v4.1 反馈：GAIT adapter、Worker 入库、幂等性均已通过，但**后端组合层**",
        "R-FALL-02（`rapid_rise + trunk_sway` 短窗口配对）未跑通——v4.1 的风险段仅",
        "触发 `rapid_rise`，缺 `trunk_sway`，规则引擎命中 R-FALL-01 保持 GREEN，不",
        "CREATE_EVENT。v4.2 补充了 `controlled_risk_golden` 段，adapter 层同时输出",
        "`rapid_rise` 和 `trunk_sway`，用于打通完整链路。",
        "",
        "## 本批次范围",
        "",
        "**仅执行 GAIT 模块**。TRAJECTORY / LANG / 抓拍 均不在本批次。",
        "",
        "- `source_mode=RECORDED_REPLAY`",
        "- `simulated=true`",
        "- `module_scope=GAIT`",
        "",
        "## 复跑身份信息（用于确认两侧使用同一 adapter）",
        "",
        f"- git HEAD: `{identity['git']['head']}`",
        f"- adapter 最新提交: `{identity['git']['adapter_last_commit']}`",
        f"- gait_video 最新提交: `{identity['git']['gait_video_last_commit']}`",
        f"- adapter 文件路径: `{identity['adapter']['file']}`",
        f"- adapter SHA-256: `{identity['adapter']['sha256']}`",
        f"- gait_video SHA-256: `{identity['gait_video']['sha256']}`",
        f"- Python: `{identity['python']['executable']}` ({identity['python']['version']})",
        f"- 平台: `{identity['python']['platform']}`",
        "",
        "详细机器可读版本见 `IDENTITY.json`。",
        "",
        "## 内容清单",
        "",
        "```",
        "GAIT_联调_v4_2_supplement.zip",
        "├── README.md",
        "├── IDENTITY.json                身份元数据（commit / Python / SHA-256）",
        "├── manifest.csv                 三段视频索引 + SHA-256 + 期望 rule id",
        "├── AlgorithmJob.template.json   与 origin/main AlgorithmJob 契约对齐的入参模板",
        "├── preflight_snapshot.json      当前 adapter 实测输出（用于对比后端复跑）",
        "├── SHA256SUMS.txt               三段 MP4 的 SHA-256",
        "├── transcode_log.json           风险段 + 黄金段 ffmpeg 参数与前后对比",
        "├── normal/D1_WALK_02_right_to_left.mp4",
        "├── controlled_risk/5_rapid_rise_720p.mp4",
        "└── controlled_risk/golden_20s_720p_h264.mp4",
        "```",
        "",
        "## adapter 层期望（本包 preflight 现场生成）",
        "",
        "| 样本 | status | evidence | 期望规则 | 关键特征 |",
        "|---|---|---|---|---|",
    ]
    for row, snap in zip(manifest_rows, snapshot):
        obs = snap.get("observations", {})
        highlights = ", ".join(
            f"{k}={obs[k]}"
            for k in ("rise_duration_s", "trunk_sway_angle_deg", "step_asymmetry_ratio", "stable_posture_duration")
            if k in obs
        )
        lines.append(
            f"| {row['group']} `{Path(row['file_relpath']).name}` | {snap['status']} | "
            f"{', '.join(snap['evidence']) or '<none>'} | {row['expected_rule_id']} | {highlights} |"
        )
    lines += [
        "",
        "## 后端 R-FALL-02 判定说明",
        "",
        "- `contracts/v1/decision.py` 中 R-FALL-02 命中条件：",
        "  同一 resident_id 在 `windows.short_seconds`(=30) 内同时收到 `rapid_rise` 与",
        "  `trunk_sway`，且都满足 usable + high_confidence。",
        "- gait_adapter 生成的 Evidence.timestamp 均取自 `job.captured_at`，同一 job",
        "  内的 Evidence 时间差为 0，因此上述短窗口条件自动满足。",
        "- 期望 backend 判定：`R-FALL-02` → previous=GREEN, active=INTERVENING,",
        "  action=CREATE_EVENT, next_state=ORANGE。",
        "",
        "## controlled_risk_golden 段来源",
        "",
        f"- 源片：`视频/视频/完整黄金闭环视频.mp4`（avc1 / 960x544 / 15fps / 127.43s）",
        f"- 截取窗口：`ss={GOLDEN_WINDOW_START:.1f}s, t={GOLDEN_WINDOW_DURATION:.1f}s`",
        f"- 编码：libx264 (preset=medium, crf=20)，yuv420p，+faststart",
        f"- 输出：1280x720（scale=-2:720 保比例，宽度对偶）",
        "",
        "## 授权",
        "",
        "- 三段均标记 `source_mode=RECORDED_REPLAY`, `simulated=true`, `authorization_status=AUTHORIZED`；",
        "- **不得**标记为 `LIVE_DEVICE` 实时闭环；",
        "- 联调完成请从本地删除本目录副本。",
        "",
        "## 现场联系人",
        "",
        "- 赵勇（步态算法侧，可实时改 `contracts/v1/gait_adapter.py` 或 `gait_video.py`）",
    ]
    return "\n".join(lines) + "\n"


async def main() -> None:
    global RISK_CAPTURED_AT

    for src in (NORMAL_SOURCE, RISK_SOURCE, GOLDEN_SOURCE):
        if not src.exists():
            raise SystemExit(f"source missing: {src}")

    ffmpeg_bin = resolve_ffmpeg()
    print(f"ffmpeg: {ffmpeg_bin}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="gait_v42_"))
    try:
        risk_720p = tmp_dir / "5_rapid_rise_720p.mp4"
        print(f"transcoding risk segment → {risk_720p}")
        risk_meta = transcode(ffmpeg_bin, RISK_SOURCE, risk_720p)

        golden_cut = tmp_dir / "golden_20s_720p_h264.mp4"
        print(f"cutting + transcoding golden segment → {golden_cut}")
        golden_meta = transcode(
            ffmpeg_bin, GOLDEN_SOURCE, golden_cut,
            ss=GOLDEN_WINDOW_START, t=GOLDEN_WINDOW_DURATION,
        )

        normal_probe = probe_video(ffmpeg_bin, NORMAL_SOURCE)
        risk_probe = risk_meta["output"]
        golden_probe = golden_meta["output"]

        normal_sha = sha256_file(NORMAL_SOURCE)
        risk_sha = sha256_file(risk_720p)
        golden_sha = sha256_file(golden_cut)

        RISK_CAPTURED_AT = datetime.fromtimestamp(RISK_SOURCE.stat().st_mtime, tz=TZ)

        print("\nrunning adapter preflight (normal) ...")
        normal_run = await adapter_run(
            "normal", NORMAL_SOURCE, NORMAL_CAPTURED_AT,
            "resident-modified-video-001", "camera-position-modified-video-001",
        )
        print(f"  status={normal_run['status']} evidence={normal_run['evidence']}")

        print("running adapter preflight (risk) ...")
        risk_run = await adapter_run(
            "risk", risk_720p, RISK_CAPTURED_AT,
            "resident-new-video-001", "camera-position-new-video-001",
        )
        print(f"  status={risk_run['status']} evidence={risk_run['evidence']}")

        print("running adapter preflight (golden) ...")
        golden_run = await adapter_run(
            "golden", golden_cut, GOLDEN_CAPTURED_AT,
            "resident-golden-loop-001", "camera-position-golden-loop-001",
        )
        print(f"  status={golden_run['status']} evidence={golden_run['evidence']}")

        # Hard sanity check: golden segment must satisfy the R-FALL-02 pair.
        golden_evs = set(golden_run["evidence"])
        if not {"rapid_rise", "trunk_sway"}.issubset(golden_evs):
            raise SystemExit(
                f"golden segment failed to satisfy R-FALL-02 combination: evidence={sorted(golden_evs)}"
            )

        snapshot = [
            {
                "file_relpath": NORMAL_RELPATH,
                "group": "normal",
                "scene": "WALK",
                "status": normal_run["status"],
                "evidence": normal_run["evidence"],
                "evidence_timestamps": normal_run["evidence_timestamps"],
                "observations": normal_run["observations"],
                "sha256": normal_sha,
                "captured_at": NORMAL_CAPTURED_AT.isoformat(timespec="seconds"),
                "diagnostics": normal_run["diagnostics"],
                "expected_rule_id": "NO_MATCH",
            },
            {
                "file_relpath": RISK_DEST_RELPATH,
                "group": "controlled_risk",
                "scene": "RAPID_RISE",
                "status": risk_run["status"],
                "evidence": risk_run["evidence"],
                "evidence_timestamps": risk_run["evidence_timestamps"],
                "observations": risk_run["observations"],
                "sha256": risk_sha,
                "captured_at": RISK_CAPTURED_AT.isoformat(timespec="seconds"),
                "diagnostics": risk_run["diagnostics"],
                "expected_rule_id": "R-FALL-01",
                "note": "5.mp4 (2560x1440, hvc1) → 1280x720 H.264 via ffmpeg libx264",
            },
            {
                "file_relpath": GOLDEN_DEST_RELPATH,
                "group": "controlled_risk_golden",
                "scene": "RAPID_RISE_AND_TRUNK_SWAY",
                "status": golden_run["status"],
                "evidence": golden_run["evidence"],
                "evidence_timestamps": golden_run["evidence_timestamps"],
                "observations": golden_run["observations"],
                "sha256": golden_sha,
                "captured_at": GOLDEN_CAPTURED_AT.isoformat(timespec="seconds"),
                "diagnostics": golden_run["diagnostics"],
                "expected_rule_id": "R-FALL-02",
                "note": f"完整黄金闭环视频.mp4 ss={GOLDEN_WINDOW_START}s t={GOLDEN_WINDOW_DURATION}s → 720p H.264 via ffmpeg libx264",
            },
        ]

        adapter_path = Path(gait_adapter_mod.__file__).resolve()
        gait_video_path = Path(gait_video_mod.__file__).resolve()
        identity = {
            "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
            "git": {
                "head": git_head(),
                "adapter_last_commit": git_last_commit("contracts/v1/gait_adapter.py"),
                "gait_video_last_commit": git_last_commit("contracts/v1/gait_video.py"),
                "decision_last_commit": git_last_commit("contracts/v1/decision.py"),
                "repo_root": str(ROOT),
            },
            "python": {
                "executable": sys.executable,
                "version": platform.python_version(),
                "platform": platform.platform(),
            },
            "adapter": {"file": str(adapter_path), "sha256": sha256_file(adapter_path)},
            "gait_video": {"file": str(gait_video_path), "sha256": sha256_file(gait_video_path)},
            "ffmpeg": ffmpeg_bin,
            "media": {
                NORMAL_RELPATH: {"sha256": normal_sha, "source_path": str(NORMAL_SOURCE), "transcoded": False},
                RISK_DEST_RELPATH: {"sha256": risk_sha, "source_path": str(RISK_SOURCE), "transcoded": True},
                GOLDEN_DEST_RELPATH: {
                    "sha256": golden_sha,
                    "source_path": str(GOLDEN_SOURCE),
                    "transcoded": True,
                    "window": {"start_s": GOLDEN_WINDOW_START, "duration_s": GOLDEN_WINDOW_DURATION},
                },
            },
        }

        probes = {"normal": normal_probe, "risk": risk_probe, "golden": golden_probe}
        shas = {"normal": normal_sha, "risk": risk_sha, "golden": golden_sha}
        manifest_rows = build_manifest_rows(probes, shas, snapshot)

        job_template = json.loads(json.dumps(ALGORITHM_JOB_TEMPLATE))
        job_template["normal"]["captured_at"] = NORMAL_CAPTURED_AT.isoformat(timespec="seconds")
        job_template["risk"]["captured_at"] = RISK_CAPTURED_AT.isoformat(timespec="seconds")
        job_template["golden"]["captured_at"] = GOLDEN_CAPTURED_AT.isoformat(timespec="seconds")

        csv_buf = io.StringIO()
        writer = csv.DictWriter(csv_buf, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in manifest_rows:
            writer.writerow(row)
        csv_bytes = csv_buf.getvalue().encode("utf-8")

        sha_lines = [
            f"{normal_sha}  {NORMAL_RELPATH}\n",
            f"{risk_sha}  {RISK_DEST_RELPATH}\n",
            f"{golden_sha}  {GOLDEN_DEST_RELPATH}\n",
        ]

        readme = build_readme(identity, manifest_rows, snapshot)

        transcode_log = {
            "risk": risk_meta,
            "golden": golden_meta,
        }

        OUT_ZIP.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr("README.md", readme.encode("utf-8"))
            zf.writestr("IDENTITY.json", (json.dumps(identity, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            zf.writestr("manifest.csv", csv_bytes)
            zf.writestr("AlgorithmJob.template.json", (json.dumps(job_template, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            zf.writestr("preflight_snapshot.json", (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            zf.writestr("SHA256SUMS.txt", "".join(sha_lines).encode("utf-8"))
            zf.writestr("transcode_log.json", (json.dumps(transcode_log, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            zf.write(NORMAL_SOURCE, NORMAL_RELPATH)
            zf.write(risk_720p, RISK_DEST_RELPATH)
            zf.write(golden_cut, GOLDEN_DEST_RELPATH)

        size_mb = OUT_ZIP.stat().st_size / (1024 * 1024)
        entries = zipfile.ZipFile(OUT_ZIP).namelist()
        print(f"\nwrote {OUT_ZIP}  ({size_mb:.2f} MB, {len(entries)} entries)")
        for name in entries:
            print(f"  - {name}")

        rerun_out = ROOT / "rerun_evidence_v4_2.json"
        rerun_out.write_text(
            json.dumps(
                {
                    "schema_version": "gait-rerun-evidence/1.2",
                    "generated_at": identity["generated_at"],
                    "source_archive": OUT_ZIP.name,
                    "scope": "GAIT_ONLY",
                    "execution_mode": "DIRECT_ADAPTER_RERUN_ON_TREE",
                    "identity": identity,
                    "snapshot": snapshot,
                    "manifest": manifest_rows,
                    "transcode_log": transcode_log,
                    "r_fall_02_readiness": {
                        "expected": True,
                        "reason": "golden segment yields both rapid_rise and trunk_sway in the same AdapterBatch (evidence timestamps == job.captured_at, delta=0s, within short_seconds=30)",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"wrote {rerun_out}")

    finally:
        for entry in tmp_dir.glob("*"):
            entry.unlink()
        tmp_dir.rmdir()


if __name__ == "__main__":
    asyncio.run(main())
