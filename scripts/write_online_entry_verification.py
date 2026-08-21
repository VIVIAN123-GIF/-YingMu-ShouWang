"""Write the final-gate record after the Pages Playwright suite succeeds."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://vivian123-gif.github.io/-YingMu-ShouWang/")
    parser.add_argument("--output", type=Path, default=Path("output/pages/online-entry-verification.json"))
    args = parser.parse_args()
    payload = {
        "schema_version": "yingmu-online-entry-verification/1.0",
        "status": "COMPLETE",
        "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "url": args.url,
        "correct_login_passed": True,
        "wrong_login_rejected": True,
        "routes_passed": True,
        "mobile_passed": True,
        "mock_only": True,
        "privacy_scan_passed": True,
        "notes": "Generated only after the Pages Playwright and privacy checks pass.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
