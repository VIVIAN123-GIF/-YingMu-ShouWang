"""Validate that the GitHub Pages artifact is static, labeled, and privacy-safe."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


FORBIDDEN_SUFFIXES = {".avi", ".docx", ".mkv", ".mov", ".mp4", ".pdf", ".zip"}
FORBIDDEN_PATTERNS = {
    "unmasked_mobile": re.compile(r"(?<![0-9A-Za-z])1[3-9]\d{9}(?![0-9A-Za-z])"),
    "private_windows_path": re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
    "private_input_path": re.compile(r"private-input|signed-consent", re.IGNORECASE),
    "private_key": re.compile(r"BEGIN (?:RSA |EC )?PRIVATE KEY"),
    "assigned_secret": re.compile(r"(?:AppSecret|AccessToken)\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
}
REQUIRED_LABELS = ("脱敏演示数据", "MOCK / RECORDED_REPLAY", "非实时设备", "非老年人实测")


def validate(dist: Path) -> dict[str, object]:
    errors: list[str] = []
    if not (dist / "index.html").is_file():
        errors.append("missing index.html")
        return {"status": "FAIL", "errors": errors}

    files = sorted(path for path in dist.rglob("*") if path.is_file())
    combined_text: list[str] = []
    for path in files:
        relative = path.relative_to(dist).as_posix()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"forbidden public artifact: {relative}")
        if path.suffix.lower() == ".map":
            errors.append(f"source map must not be published: {relative}")
        if path.suffix.lower() not in {".css", ".html", ".js", ".json", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        combined_text.append(text)
        for name, pattern in FORBIDDEN_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{relative}: {name}")

    joined = "\n".join(combined_text)
    for label in REQUIRED_LABELS:
        if label not in joined:
            errors.append(f"missing public source label: {label}")
    index_text = (dist / "index.html").read_text(encoding="utf-8")
    if "/-YingMu-ShouWang/assets/" not in index_text:
        errors.append("index.html does not use the GitHub Pages base path")

    return {
        "status": "PASS" if not errors else "FAIL",
        "files": len(files),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("frontend/dist"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = validate(args.dist)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
