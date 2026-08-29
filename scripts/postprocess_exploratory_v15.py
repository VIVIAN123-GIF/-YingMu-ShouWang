"""Apply the completed v1.5 cycle admission policy to immutable r1 features."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.v1.gait_adapter_v15 import infer_activity_context  # noqa: E402
from contracts.v1.memory import assess_relative_gait_speed  # noqa: E402
from contracts.v1.ruleset import load_ruleset_version  # noqa: E402
from scripts.exploratory_reanalysis_v15 import safe_output  # noqa: E402
from scripts.supplemental_validation_v14 import confusion, percentile, sha256_file, write_new  # noqa: E402


RULESET = load_ruleset_version("ruleset-v1.5")
EXECUTOR = Path(__file__).resolve()
RULESET_PATH = ROOT / "contracts/v1/rulesets/ruleset-v1.5.json"
ADAPTER_PATH = ROOT / "contracts/v1/gait_adapter_v15.py"


def _eligible_speed(features: dict[str, Any], context: str, baseline: dict[str, Any]) -> bool:
    if context != "WALK":
        return False
    if float(features.get("locomotion_duration_s") or 0.0) < RULESET.thresholds["relative_speed_min_locomotion_seconds"]:
        return False
    if int(float(features.get("gait_cycle_count") or 0.0)) < int(RULESET.thresholds["gait_min_complete_cycles"]):
        return False
    stats = baseline["baselines_by_context"]["WALK"]["relative_gait_speed"]
    return assess_relative_gait_speed(float(features["step_speed_norm_s"]), stats, RULESET)["status"] == "EVIDENCE"


def run(r1_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir = safe_output(output_dir)
    r1 = json.loads(r1_path.read_text(encoding="utf-8"))
    if r1.get("classification") != "EXPLORATORY_REANALYSIS" or len(r1.get("records", [])) != 29:
        raise ValueError("invalid v1.5 r1 feature source")
    records = []
    for source in r1["records"]:
        row = json.loads(json.dumps(source))
        features = row["feature_values"]
        context = infer_activity_context(features)
        speed_evidence = _eligible_speed(features, context, r1["baseline"])
        existing = list(row["evidence_types"])
        without_speed = [item for item in existing if item != "relative_speed_change"]
        row["evidence_types"] = [*without_speed, *(["relative_speed_change"] if speed_evidence else [])]
        if not speed_evidence:
            row["decisions"] = [
                item for item in row["decisions"]
                if not str(item.get("evidence_id", "")).startswith("evi-v15-personal-")
            ]
        row["activity_context"] = context
        row["trend_candidate"] = any(
            item in {"relative_speed_change", "gait_instability"}
            for item in row["evidence_types"]
        )
        row["persistent_trend_alert"] = False
        row["trend_persistence_reason"] = "ONE_CLIP_IS_ONE_ACTIVITY_WINDOW; TWO_INDEPENDENT_WINDOWS_REQUIRED"
        row["postprocessing_revision"] = "V15_CYCLE_ADMISSION_R2"
        records.append(row)
    performance = [item for item in records if item["record_role"] != "GOLDEN"]
    test = lambda item: item["record_role"] == "TEST"
    negative = lambda item: item["scenario_id"].startswith("NEG_")
    metrics = {
        "immediate_orange": confusion(
            performance, lambda item: item["scenario_id"] == "POS_RAPID_RISE_SWAY",
            lambda item: test(item) and item["scenario_id"] != "POS_RAPID_RISE_SWAY", "orange",
        ),
        "single_window_trend_candidate": confusion(
            performance,
            lambda item: item["scenario_id"] in {"POS_SLOW_SMALL_STEP_SWAY", "POS_ASYMMETRIC_STEP"},
            negative, "trend_candidate",
        ),
        "persistent_trend_alert": confusion(
            performance,
            lambda item: item["scenario_id"] in {"POS_SLOW_SMALL_STEP_SWAY", "POS_ASYMMETRIC_STEP"},
            negative, "persistent_trend_alert",
        ),
        "quality_gate": confusion(
            performance, lambda item: item["record_role"] == "QUALITY", test, "quality_gate",
        ),
        "offline_processing_latency_ms": {
            "median": percentile([item["processing_latency_ms"] for item in performance], 0.5),
            "p95": percentile([item["processing_latency_ms"] for item in performance], 0.95),
            "max": max(item["processing_latency_ms"] for item in performance),
            "source": "r1 video inference; r2 postprocessing time excluded",
        },
    }
    golden = next(item for item in records if item["record_role"] == "GOLDEN")
    payload = {
        **{key: value for key, value in r1.items() if key not in {"records", "metrics", "golden_loop", "inputs"}},
        "schema_version": "exploratory-v15-reanalysis/1.1",
        "revision": "R2_CYCLE_ADMISSION_COMPLETED",
        "feature_source_sha256": sha256_file(r1_path),
        "postprocessing_only": True,
        "inputs": {
            **r1["inputs"], "r1_feature_source_sha256": sha256_file(r1_path),
            "ruleset_sha256": sha256_file(RULESET_PATH),
            "adapter_sha256": sha256_file(ADAPTER_PATH),
            "postprocessor_sha256": sha256_file(EXECUTOR),
        },
        "records": records, "metrics": metrics,
        "golden_loop": {
            "status": "PASS" if golden["orange"] else "FAIL", "orange": golden["orange"],
            "included_in_metrics": False,
            "claim_boundary": "Exploratory recorded replay; no real device audio claim.",
        },
        "r1_retained": True,
    }
    output_dir.mkdir(parents=True)
    write_new(output_dir / "exploratory-results.json", payload)
    lines = [
        ("exploratory-results.json", sha256_file(output_dir / "exploratory-results.json")),
        (str(r1_path), sha256_file(r1_path)),
        (str(RULESET_PATH), sha256_file(RULESET_PATH)),
        (str(ADAPTER_PATH), sha256_file(ADAPTER_PATH)),
        (str(EXECUTOR), sha256_file(EXECUTOR)),
    ]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(f"{digest}  {name}" for name, digest in lines) + "\n", encoding="utf-8"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r1", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.r1.resolve(), args.output_dir.resolve())
    print(json.dumps({
        "status": result["status"], "classification": result["classification"],
        "revision": result["revision"], "records": len(result["records"]),
        "golden": result["golden_loop"]["status"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
