from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path


def main(path: Path) -> None:
    root = "3人96段-最终可用版/"
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        videos = [name for name in names if name.lower().endswith(".mp4")]
        manifest = json.loads(archive.read(root + "capture-manifest.json").decode("utf-8"))
        records = manifest["records"]
        expected = {root + row["package_relpath"]: row["sha256"] for row in records}
        bad_hashes = [name for name in videos if hashlib.sha256(archive.read(name)).hexdigest() != expected.get(name)]
    participant_role = Counter((row["participant_id"], row["record_role"]) for row in records)
    evaluation_scenarios = Counter(
        (row["participant_id"], row["scenario_id"])
        for row in records
        if row["record_role"] == "EVALUATION"
    )
    golden = [row for row in records if row["protocol_variant"] == "GOLDEN_115S"]
    result = {
        "videos": len(videos),
        "records": len(records),
        "unique_candidates": len({row["candidate_id"] for row in records}),
        "participant_role_counts": {f"{p}/{r}": count for (p, r), count in participant_role.items()},
        "evaluation_scenario_counts": {f"{p}/{s}": count for (p, s), count in evaluation_scenarios.items()},
        "golden_durations_ms": {row["participant_id"]: row["duration_ms"] for row in golden},
        "excluded_p02_extra_present": any(row["candidate_id"] == "P02-DAY2-023" for row in records),
        "p02_stop_present": any(row["candidate_id"] == "P02-DAY2-025" for row in records),
        "bad_hashes": bad_hashes,
        "zip_bytes": path.stat().st_size,
        "zip_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    expected_role = {(p, "BASELINE"): 8 for p in ("P01", "P02", "P03")}
    expected_role.update({(p, "EVALUATION"): 24 for p in ("P01", "P02", "P03")})
    if not (
        len(videos) == len(records) == len({row["candidate_id"] for row in records}) == 96
        and participant_role == Counter(expected_role)
        and len(evaluation_scenarios) == 18
        and all(count == 4 for count in evaluation_scenarios.values())
        and len(golden) == 3
        and all(int(row["duration_ms"]) >= 115_000 for row in golden)
        and not result["excluded_p02_extra_present"]
        and result["p02_stop_present"]
        and not bad_hashes
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
