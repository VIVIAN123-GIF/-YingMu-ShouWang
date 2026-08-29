"""Confirm visual review and populate the v1.4 capture manifest without inference."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new(path: Path, text: str, encoding: str = "utf-8") -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def confirm(
    review_path: Path,
    template_path: Path,
    media_root: Path,
    output_dir: Path,
    confirmation_date: str,
) -> dict[str, Any]:
    outputs = {
        "review_json": output_dir / "team-confirmed-visual-review.json",
        "review_csv": output_dir / "team-confirmed-visual-review.csv",
        "review_sums": output_dir / "team-confirmed-visual-review-SHA256SUMS.txt",
        "manifest": output_dir / "capture-manifest.json",
    }
    existing = [str(path) for path in outputs.values() if path.exists()]
    if existing:
        raise ValueError(f"refusing to overwrite confirmed capture outputs: {existing}")

    review = json.loads(review_path.read_text(encoding="utf-8"))
    template = json.loads(template_path.read_text(encoding="utf-8"))
    records = review.get("records", [])
    if review.get("record_count") != 29 or len(records) != 29:
        raise ValueError("visual review must contain 29 records")
    if review.get("status_counts") != {"VALID": 29, "ABORTED": 0, "REJECTED": 0}:
        raise ValueError("visual review status counts are not ready for confirmation")
    if any(row.get("algorithm_output_consulted") is not False for row in records):
        raise ValueError("visual review independence statement is not satisfied")

    by_clip: dict[str, dict[str, Any]] = {}
    media_root = media_root.resolve()
    for row in records:
        clip_id = row.get("clip_id")
        if not isinstance(clip_id, str) or clip_id in by_clip:
            raise ValueError(f"invalid or duplicate clip_id: {clip_id}")
        media = (media_root / str(row.get("media_relpath", ""))).resolve()
        try:
            media.relative_to(media_root)
        except ValueError as error:
            raise ValueError(f"media escapes root: {clip_id}") from error
        if not media.is_file():
            raise FileNotFoundError(media)
        actual_hash = sha256_file(media)
        if actual_hash.lower() != str(row.get("sha256", "")).lower():
            raise ValueError(f"media hash changed after visual review: {clip_id}")
        if media.stat().st_size != row.get("byte_size"):
            raise ValueError(f"media size changed after visual review: {clip_id}")
        by_clip[clip_id] = row

    confirmed = dict(review)
    confirmed["schema_version"] = "supplemental-visual-review/1.1"
    confirmed["human_signoff_status"] = "CONFIRMED_BY_CAPTURE_TEAM"
    confirmed["team_confirmation"] = {
        "status": "ACCEPTED",
        "date": confirmation_date,
        "authority": "CAPTURE_TEAM",
        "scope": "ALL_29_RECORDS",
        "source": "TEAM_DECLARATION_IN_PROJECT_WORKSPACE_SESSION",
    }
    confirmed_records = []
    for row in records:
        item = dict(row)
        item["human_signoff_status"] = "CONFIRMED_BY_CAPTURE_TEAM"
        confirmed_records.append(item)
    confirmed["records"] = confirmed_records

    manifest = dict(template)
    manifest["status"] = "CAPTURED"
    manifest_rows = []
    for row in template.get("records", []):
        clip_id = row["clip_id"]
        visual = by_clip.get(clip_id)
        if visual is None:
            raise ValueError(f"template record missing from visual review: {clip_id}")
        item = dict(row)
        item["capture_date"] = visual["capture_date_from_visible_watermark"]
        item["media_relpath"] = visual["media_relpath"]
        item["sha256"] = str(visual["sha256"]).lower()
        item["byte_size"] = visual["byte_size"]
        manifest_rows.append(item)
    if set(by_clip) != {row["clip_id"] for row in manifest_rows}:
        raise ValueError("visual review and manifest clip sets differ")
    manifest["records"] = manifest_rows

    write_new(outputs["review_json"], json.dumps(confirmed, ensure_ascii=False, indent=2) + "\n")
    fields = list(confirmed_records[0])
    if outputs["review_csv"].exists():
        raise ValueError(f"refusing to overwrite output: {outputs['review_csv']}")
    with outputs["review_csv"].open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(confirmed_records)
    write_new(outputs["manifest"], json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    sums = (
        f"{sha256_file(outputs['review_json']).upper()}  {outputs['review_json'].name}\n"
        f"{sha256_file(outputs['review_csv']).upper()}  {outputs['review_csv'].name}\n"
    )
    write_new(outputs["review_sums"], sums, encoding="ascii")
    return {
        "status": "PASS",
        "confirmed_records": len(confirmed_records),
        "manifest_records": len(manifest_rows),
        "human_signoff_status": confirmed["human_signoff_status"],
        "outputs": {name: str(path.resolve()) for name, path in outputs.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--confirmation-date", required=True)
    args = parser.parse_args()
    result = confirm(
        args.review.resolve(),
        args.template.resolve(),
        args.media_root.resolve(),
        args.output_dir.resolve(),
        args.confirmation_date,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
