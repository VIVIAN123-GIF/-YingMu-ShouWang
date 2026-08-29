"""Verify that the frozen P03 result has not been overwritten or relabeled."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTEGRITY = ROOT / "experiments" / "three-participant" / "p03-frozen-integrity.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(path: Path = DEFAULT_INTEGRITY) -> dict[str, object]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for relative, expected in spec["files"].items():
        target = ROOT / relative
        if not target.is_file():
            errors.append(f"missing frozen P03 file: {relative}")
        elif sha256_file(target) != expected:
            errors.append(f"frozen P03 hash changed: {relative}")

    result_path = ROOT / "experiments" / "three-participant" / "results" / "final" / "experiment-results.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    instant = result.get("metrics", {}).get("instant_event", {})
    trend = result.get("metrics", {}).get("gait_trend", {})
    expected = spec["expected_metrics"]
    actual = {
        "transition_detection": _pair(instant.get("transition_detection_rate")),
        "instability_family_detection": _pair(instant.get("instability_family_detection_rate")),
        "multi_family_formation": _pair(instant.get("multi_family_formation_rate")),
        "orange_production": _pair(instant.get("orange_production")),
        "slow_small_step_target_evidence": _pair(
            trend.get("target_evidence_detection_by_scenario", {}).get("POS_SLOW_SMALL_STEP_SWAY", {}).get("any_target")
        ),
        "asymmetric_step_target_evidence": _pair(
            trend.get("target_evidence_detection_by_scenario", {}).get("POS_ASYMMETRIC_STEP", {}).get("any_target")
        ),
        "baseline_status_counts": trend.get("baseline_status_counts"),
    }
    for name, value in expected.items():
        if actual.get(name) != value:
            errors.append(f"frozen P03 metric changed: {name}")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "actual": actual}


def _pair(metric: object) -> list[int] | None:
    if not isinstance(metric, dict):
        return None
    numerator = metric.get("numerator")
    denominator = metric.get("denominator")
    return [numerator, denominator] if isinstance(numerator, int) and isinstance(denominator, int) else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--integrity", type=Path, default=DEFAULT_INTEGRITY)
    args = parser.parse_args()
    report = verify(args.integrity.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
