from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path


def main(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        videos = [name for name in names if name.lower().endswith(".mp4")]
        root = "3人96段-调整版/"
        manifest = json.loads(archive.read(root + "selection-manifest.json").decode("utf-8"))
        expected = {
            root + record["package_relpath"]: record["sha256"]
            for record in manifest["records"]
        }
        bad_hashes = [
            name
            for name in videos
            if hashlib.sha256(archive.read(name)).hexdigest() != expected.get(name)
        ]
        readme = archive.read(root + "README-重要说明.md").decode("utf-8")
    result = {
        "entries": len(names),
        "videos": len(videos),
        "records": len(manifest["records"]),
        "unique_candidates": len({record["candidate_id"] for record in manifest["records"]}),
        "participant_counts": manifest["participant_counts"],
        "baseline_count": sum(record["record_role"] == "BASELINE" for record in manifest["records"]),
        "evaluation_count": sum(record["record_role"] == "EVALUATION" for record in manifest["records"]),
        "bad_hashes": bad_hashes,
        "readme_ok": '\n"\n' not in readme,
        "zip_bytes": zip_path.stat().st_size,
        "zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not (
        result["videos"] == 96
        and result["records"] == 96
        and result["unique_candidates"] == 96
        and result["participant_counts"] == {"P01": 32, "P02": 32, "P03": 32}
        and result["baseline_count"] == 24
        and result["evaluation_count"] == 72
        and not result["bad_hashes"]
        and result["readme_ok"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
