import argparse
import json
from pathlib import Path

from behavior_evidence import build_behavior_evidence_bundle


def parse_args():
    parser = argparse.ArgumentParser(description="生成行为统计MOCK Observation/Evidence联调包")
    parser.add_argument("--input", type=Path, required=True, help="脱敏模拟统计JSON")
    parser.add_argument("--output", type=Path, required=True, help="联调包JSON输出路径")
    return parser.parse_args()


def main():
    args = parse_args()
    settings = json.loads(args.input.expanduser().read_text(encoding="utf-8"))
    bundle = build_behavior_evidence_bundle(settings)
    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"已生成{len(bundle['observations'])}条Observation和"
        f"{len(bundle['evidence'])}条Evidence：{output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
