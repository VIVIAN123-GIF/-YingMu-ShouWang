"""Ruleset v1.0 configuration, risk scoring and explainable rule traces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


RULESET_PATH = Path(__file__).parent / "rulesets" / "ruleset-v1.0.json"


@dataclass(frozen=True)
class RuleTrace:
    evaluated_at: datetime
    resident_id: str
    queried_windows: dict[str, Any]
    matched_rule: str
    previous_state: str
    next_state: str
    reason: str
    not_matched: dict[str, str]
    event_id: str | None
    ruleset_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "evaluated_at": self.evaluated_at.isoformat(),
            "resident_id": self.resident_id,
            "queried_windows": self.queried_windows,
            "matched_rule": self.matched_rule,
            "previous_state": self.previous_state,
            "next_state": self.next_state,
            "reason": self.reason,
            "not_matched": self.not_matched,
            "event_id": self.event_id,
            "ruleset_version": self.ruleset_version,
        }


@dataclass(frozen=True)
class Ruleset:
    version: str
    windows: dict[str, int]
    thresholds: dict[str, float]
    risk_weights: dict[str, float]
    context_factors: dict[str, float]
    rules: tuple[dict[str, str], ...]

    @classmethod
    def load(cls, path: Path = RULESET_PATH) -> "Ruleset":
        payload = json.loads(path.read_text(encoding="utf-8"))
        weights = payload["risk_weights"]
        if round(sum(weights.values()), 6) != 1.0:
            raise ValueError("ruleset risk weights must sum to 1")
        return cls(
            version=payload["ruleset_version"],
            windows=payload["windows"],
            thresholds=payload["thresholds"],
            risk_weights=weights,
            context_factors=payload["context_factors"],
            rules=tuple(payload["rules"]),
        )

    def usable(self, confidence: float, data_quality: float) -> bool:
        return (
            confidence >= self.thresholds["confidence"]
            and data_quality >= self.thresholds["data_quality"]
        )

    def high_confidence(self, values: Iterable[float]) -> bool:
        return any(value >= self.thresholds["high_confidence"] for value in values)

    def score(self, evidences: list[Any], context_score: float = 0.0) -> float:
        if not evidences:
            return 0.0
        severity = max(float(item.severity) for item in evidences)
        confidence = max(float(item.confidence) for item in evidences)
        quality = min(float(item.data_quality) for item in evidences)
        score = (
            self.risk_weights["severity"] * severity
            + self.risk_weights["confidence"] * confidence
            + self.risk_weights["data_quality"] * quality
            + self.risk_weights["context"] * min(max(context_score, 0.0), 1.0)
        )
        return round(min(max(score, 0.0), 1.0), 2)


def load_ruleset() -> Ruleset:
    return Ruleset.load()
