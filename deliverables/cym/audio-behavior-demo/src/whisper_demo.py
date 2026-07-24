import argparse
import json
import time
from pathlib import Path

import whisper


def parse_args():
    parser = argparse.ArgumentParser(description="Run local Whisper transcription.")
    parser.add_argument("input", type=Path, help="Authorized local audio file")
    parser.add_argument("--model", default="tiny", help="Whisper model name")
    parser.add_argument("--language", default="Chinese", help="Audio language")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for generated transcript and metadata",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_path = args.input.expanduser().resolve()

    if not input_path.is_file():
        raise SystemExit(f"Audio file not found: {input_path}")

    started_at = time.perf_counter()
    model = whisper.load_model(args.model)
    result = model.transcribe(
        str(input_path),
        language=args.language,
        fp16=False,
    )
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


if __name__ == "__main__":
    main()

