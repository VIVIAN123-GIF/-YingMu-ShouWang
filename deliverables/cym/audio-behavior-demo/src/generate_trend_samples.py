import argparse
import json
from pathlib import Path
from trend_analysis import build_trend_bundle


def main():
    parser = argparse.ArgumentParser(description="生成昼夜节律与多日活动趋势Evidence")
    parser.add_argument("--input", type=Path, required=True, help="日活动汇总JSON")
    parser.add_argument("--output", type=Path, required=True, help="趋势联调包JSON")
    args = parser.parse_args()

    payload = json.loads(args.input.expanduser().read_text(encoding="utf-8"))
    bundle = build_trend_bundle(payload)
    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"已生成{len(bundle['observations'])}条Observation和"
        f"{len(bundle['evidence'])}条Evidence，"
        f"基线状态：{bundle['baseline_status']}：{output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
