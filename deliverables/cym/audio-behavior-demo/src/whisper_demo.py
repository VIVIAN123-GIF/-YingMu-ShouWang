import argparse
import importlib.metadata
import importlib.util
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from observation import build_observation, validate_observation_collection


FRAUD_PHRASE_GROUPS = {
    "guaranteed_return": ("保证收益", "保證收益"),
    "verification_code_like": ("验证码", "驗證碼", "验证马", "驗證馬"),
    "immediate_transfer": (
        "马上转账",
        "馬上轉帳",
        "马上完成转账",
        "馬上完成轉帳",
    ),
    "safe_account": ("安全账户", "安全賬戶", "安全帳戶"),
    "keep_secret_from_family": ("不要告诉家人", "不要告訴家人"),
}


def parse_args():
    parser = argparse.ArgumentParser(description="运行本地Whisper中文转写")
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help="经过授权的本地音频文件",
    )
    parser.add_argument("--model", default="tiny", help="Whisper模型名称")
    parser.add_argument("--language", default="Chinese", help="音频语言")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="转写文本和元数据输出目录",
    )
    parser.add_argument(
        "--observation-output",
        type=Path,
        help="可选的Freeze v1.0 Observation JSON输出路径",
    )
    parser.add_argument(
        "--resident-id",
        default="resident-001",
        help="Observation中的脱敏老人标识",
    )
    parser.add_argument(
        "--location",
        default=None,
        help="可选区域标识，例如living_room",
    )
    parser.add_argument(
        "--asset-id",
        default=None,
        help="可选脱敏素材标识，不得填写绝对路径或访问密钥",
    )
    parser.add_argument(
        "--source-mode",
        choices=(
            "LIVE_DEVICE",
            "RECORDED_REPLAY",
            "PUBLIC_DATASET",
            "MOCK",
        ),
        default="RECORDED_REPLAY",
        help="输入来源，默认本地录音回放",
    )
    parser.add_argument(
        "--simulated",
        action="store_true",
        help="将本次音频标记为模拟实验",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检查Whisper和FFmpeg环境，不执行转写",
    )
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
        "ffmpeg_command": "ffmpeg" if ffmpeg_path else None,
    }


def print_install_help(status):
    if not status["whisper_installed"]:
        print("未安装openai-whisper，请先运行：pip install -r requirements.txt")
    if not status["ffmpeg_available"]:
        print("未找到FFmpeg。Whisper读取音频前必须安装FFmpeg。")
        print("Windows可尝试：winget install --id Gyan.FFmpeg -e")
        print("安装后请重新打开PowerShell，并运行：ffmpeg -version")


def find_fraud_phrase_labels(transcript):
    return [
        label
        for label, variants in FRAUD_PHRASE_GROUPS.items()
        if any(variant in transcript for variant in variants)
    ]


def build_audio_observations(
    transcript,
    *,
    resident_id,
    model,
    language,
    source_mode="RECORDED_REPLAY",
    location=None,
    asset_id=None,
    simulated=False,
):
    """把Whisper转写转换为直接观测，不在此处判断诈骗。"""
    phrase_labels = find_fraud_phrase_labels(transcript)
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    common = {
        "resident_id": resident_id,
        "timestamp": timestamp,
        "source": "audio",
        "location": location,
        "confidence": 0.50,
        "data_quality": 0.60,
        "source_mode": source_mode,
        "asset_id": asset_id,
        "simulated": simulated,
        "metadata": {
            "adapter_version": "speech-adapter-v1",
            "model": model,
            "language": language,
            "score_status": "DEMO_UNCALIBRATED",
            "interpretation": "HIGH_RISK_INTERACTION_FEATURE_ONLY",
        },
    }

    feature_specs = [
        ("audio_transcript_available", bool(transcript), None),
        ("fraud_keyword_match_count", len(phrase_labels), "count"),
    ]
    if transcript:
        feature_specs.append(("audio_transcript", transcript, None))
    if phrase_labels:
        feature_specs.append(
            ("fraud_keyword_labels", ",".join(phrase_labels), None)
        )

    observations = [
        build_observation(
            observation_id=f"obs-audio-{uuid4().hex}",
            feature_name=feature_name,
            feature_value=feature_value,
            unit=unit,
            **common,
        )
        for feature_name, feature_value, unit in feature_specs
    ]
    return validate_observation_collection(observations)


def write_observations(path, observations):
    output_path = path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(observations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Observation输出：{output_path}")


def main():
    parser, args = parse_args()
    status = environment_status()

    if args.check:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        print_install_help(status)
        return 0 if status["whisper_installed"] and status["ffmpeg_available"] else 2

    if args.input is None:
        parser.error("执行转写时必须提供音频文件；只检查环境请使用--check")

    if not status["whisper_installed"] or not status["ffmpeg_available"]:
        print_install_help(status)
        return 2

    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        print(f"音频文件不存在：{input_path}")
        return 2

    # 通过环境检查后再导入，避免--check无故加载Torch。
    import whisper

    started_at = time.perf_counter()
    try:
        model = whisper.load_model(args.model)
        result = model.transcribe(
            str(input_path),
            language=args.language,
            fp16=False,
        )
    except Exception as error:
        print(f"Whisper转写失败：{error}")
        return 1

    elapsed_seconds = time.perf_counter() - started_at
    transcript = result["text"].strip()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = output_dir / f"{input_path.stem}.txt"
    metadata_path = output_dir / f"{input_path.stem}.json"

    transcript_path.write_text(transcript + "\n", encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "input_name": input_path.name,
                "model": args.model,
                "language": args.language,
                "elapsed_seconds": round(elapsed_seconds, 3),
                "transcript": transcript,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Transcript: {transcript}")
    print(f"Elapsed: {elapsed_seconds:.3f} seconds")
    print(f"Text output: {transcript_path}")
    print(f"Metadata output: {metadata_path}")
    if args.observation_output:
        observations = build_audio_observations(
            transcript,
            resident_id=args.resident_id,
            model=args.model,
            language=args.language,
            source_mode=args.source_mode,
            location=args.location,
            asset_id=args.asset_id,
            simulated=args.simulated,
        )
        write_observations(args.observation_output, observations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
