import argparse
import importlib.metadata
import importlib.util
import json
import shutil
import sys
import time
from pathlib import Path


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
