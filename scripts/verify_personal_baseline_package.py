from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path


def main(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        root = "3人个人基线-最终版/"
        videos = [name for name in names if name.lower().endswith(".mp4")]
        manifest = json.loads(archive.read(root + "baseline-manifest.json").decode("utf-8"))
        expected = {root + r["package_relpath"]: r["sha256"] for r in manifest["records"]}
        bad = [name for name in videos if hashlib.sha256(archive.read(name)).hexdigest() != expected.get(name)]
        result = {
            "entries": len(names),
            "videos": len(videos),
            "records": len(manifest["records"]),
            "unique_candidates": len({r["candidate_id"] for r in manifest["records"]}),
            "participant_counts": manifest["participant_counts"],
            "bad_hashes": bad,
            "zip_bytes": path.stat().st_size,
            "zip_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not (
        result["videos"] == result["records"] == result["unique_candidates"] == 24
        and result["participant_counts"] == {"P01": 8, "P02": 8, "P03": 8}
        and not result["bad_hashes"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
