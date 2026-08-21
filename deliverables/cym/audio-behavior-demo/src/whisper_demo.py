"""Local Whisper demo with backend-safe redacted outputs."""

import argparse
import importlib.metadata
import importlib.util
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from audio_evidence import _build_audio_items, build_audio_bundle


def parse_args():
    parser = argparse.ArgumentParser(description="Run local Whisper transcription")
    parser.add_argument("input", nargs="?", type=Path, help="authorized local audio file")
    parser.add_argument("--model", default="tiny")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--observation-output", type=Path)
    parser.add_argument("--bundle-output", type=Path)
    parser.add_argument("--quality-metrics", type=Path)
    parser.add_argument("--resident-id", default="resident-001")
    parser.add_argument("--location", default=None)
    parser.add_argument("--asset-id", default=None)
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--captured-at", default=None)
    parser.add_argument(
        "--source-mode",
        choices=("LIVE_DEVICE", "RECORDED_REPLAY", "PUBLIC_DATASET", "MOCK"),
        default="RECORDED_REPLAY",
    )
    parser.add_argument("--simulated", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser, parser.parse_args()


def environment_status():
    whisper_installed = importlib.util.find_spec("whisper") is not None
    try:
        whisper_version = importlib.metadata.version("openai-whisper")
    except importlib.metadata.PackageNotFoundError:
        whisper_version = None
    ffmpeg_path = shutil.which("ffmpeg")
    return {
        "python_version": sys.version.split()[0],
        "whisper_installed": whisper_installed,
        "whisper_version": whisper_version,
        "ffmpeg_available": ffmpeg_path is not None,
        "ffmpeg_command": ffmpeg_path,
    }


def print_install_help(status):
    if not status["whisper_installed"]:
        print("未安装 openai-whisper，请先安装 requirements.txt 中的依赖。")
    if not status["ffmpeg_available"]:
        print("未找到FFmpeg，Whisper读取音频前必须安装FFmpeg。")
        print("Windows 可运行：winget install --id Gyan.FFmpeg -e")
        print("安装后重新打开 PowerShell，并运行 ffmpeg -version。")


def build_audio_observations(transcript, *, resident_id, model, language, source_mode="RECORDED_REPLAY", location=None, asset_id=None, simulated=False, timestamp=None, job_id=None, run_id=None):
    """Compatibility helper returning redacted observations only."""
    observations, _ = _build_audio_items(
        transcript,
        resident_id=resident_id,
        model=model,
        language=language,
        source_mode=source_mode,
        location=location,
        asset_id=asset_id,
        simulated=simulated,
        timestamp=timestamp,
        job_id=job_id,
        run_id=run_id,
    )
    if job_id is None:
        observations[0]["feature_name"] = "audio_transcript_available"
        observations[0]["feature_value"] = bool(transcript.strip())
        observations[0]["observation_id"] = observations[0]["observation_id"].replace(
            "audio-asr-transcript-redacted", "audio-transcript-available"
        )
    return observations


def _write_json(path, payload):
    output = path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main():
    parser, args = parse_args()
    status = environment_status()
    if args.check:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        print_install_help(status)
        return 0 if status["whisper_installed"] and status["ffmpeg_available"] else 2
    if args.input is None:
        parser.error("转写时必须提供音频文件；只检查环境请使用 --check")
    if not status["whisper_installed"] or not status["ffmpeg_available"]:
        print_install_help(status)
        return 2
    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        print(f"音频文件不存在：{input_path.name}")
        return 2
    import whisper

    started_at = time.perf_counter()
    captured_at = args.captured_at or datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        model = whisper.load_model(args.model)
        result = model.transcribe(str(input_path), language=args.language, fp16=False)
    except Exception as error:
        print(f"Whisper 转写失败：{error}")
        return 1
    elapsed_seconds = time.perf_counter() - started_at
    transcript = result.get("text", "").strip()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = build_audio_bundle(
        transcript,
        resident_id=args.resident_id,
        model=args.model,
        language=args.language,
        source_mode=args.source_mode,
        location=args.location,
        asset_id=args.asset_id,
        simulated=args.simulated,
        timestamp=captured_at,
        job_id=args.job_id,
    )
    redacted = bundle["observations"][0]["feature_value"]
    transcript_path = output_dir / f"{input_path.stem}.redacted.txt"
    metadata_path = output_dir / f"{input_path.stem}.json"
    transcript_path.write_text(redacted + "\n", encoding="utf-8")
    _write_json(metadata_path, {
        "input_name": input_path.name,
        "model": args.model,
        "language": args.language,
        "captured_at": captured_at,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "transcript_redacted": redacted,
    })
    print(f"Redacted transcript: {redacted}")
    print(f"Elapsed: {elapsed_seconds:.3f} seconds")
    print(f"Text output: {transcript_path}")
    print(f"Metadata output: {metadata_path}")
    if args.observation_output:
        _write_json(args.observation_output, bundle["observations"])
    if args.bundle_output:
        if args.quality_metrics:
            try:
                metrics = json.loads(args.quality_metrics.expanduser().read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                print(f"音频质量指标读取失败：{error}")
                return 2
            bundle = build_audio_bundle(
                transcript,
                resident_id=args.resident_id,
                model=args.model,
                language=args.language,
                source_mode=args.source_mode,
                location=args.location,
                asset_id=args.asset_id,
                simulated=args.simulated,
                quality_metrics=metrics,
                timestamp=captured_at,
                job_id=args.job_id,
            )
        _write_json(args.bundle_output, bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
