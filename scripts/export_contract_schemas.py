"""Export canonical JSON Schema and validated examples from Pydantic models."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.v1.mock_data import sequence  # noqa: E402
from contracts.v1.models import Evidence, InterventionResult, Observation, RiskEvent  # noqa: E402
from contracts.v1.rehearsal import run_fixed_sequence  # noqa: E402


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    schema_dir = ROOT / "contracts" / "v1" / "schemas"
    example_dir = ROOT / "contracts" / "v1" / "examples"
    models = {
        "observation": Observation,
        "evidence": Evidence,
        "risk_event": RiskEvent,
        "intervention_result": InterventionResult,
    }
    for name, model in models.items():
        write_json(schema_dir / f"{name}.schema.json", model.model_json_schema())

    data = sequence()
    engine, steps = run_fixed_sequence()
    snapshot = engine.snapshot()
    examples = {
        "observation": Observation.model_validate(data["observations"][1]).model_dump(mode="json"),
        "evidence": Evidence.model_validate(data["evidence"][1]).model_dump(mode="json"),
        "risk_event": snapshot["events"][0],
        "intervention_result": snapshot["interventions"][0],
    }
    for name, payload in examples.items():
        write_json(example_dir / f"{name}.json", payload)
    write_json(example_dir / "four_objects.json", examples)
    write_json(example_dir / "mock_fall_sequence.json", {**data, "expected_steps": steps})
    print(f"Exported {len(models)} schemas and {len(examples) + 2} example files")


if __name__ == "__main__":
    main()
