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
    thresholds: dict[str, Any] | None = None
    baseline_snapshot: dict[str, Any] | None = None
    quality_snapshot: dict[str, Any] | None = None
    context_snapshot: dict[str, Any] | None = None
    score_components: dict[str, Any] | None = None

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
            "thresholds": self.thresholds or {},
            "baseline_snapshot": self.baseline_snapshot or {},
            "quality_snapshot": self.quality_snapshot or {},
            "context_snapshot": self.context_snapshot or {},
            "score_components": self.score_components or {},
        }


@dataclass(frozen=True)
class Ruleset:
    version: str
    context_policy_version: str
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
            context_policy_version=payload.get("context_policy_version", "env-context-v1.0"),
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
        return self.score_details(evidences, context_score)["final_score"]

    def score_details(self, evidences: list[Any], context_score: float = 0.0) -> dict[str, Any]:
        if not evidences:
            return {
                "severity": 0.0,
                "confidence": 0.0,
                "data_quality": 0.0,
                "context": round(min(max(context_score, 0.0), 1.0), 4),
                "weights": dict(self.risk_weights),
                "raw_score": 0.0,
                "final_score": 0.0,
            }
        severity = max(float(item.severity) for item in evidences)
        confidence = max(float(item.confidence) for item in evidences)
        quality = min(float(item.data_quality) for item in evidences)
        bounded_context = min(max(context_score, 0.0), 1.0)
        score = (
            self.risk_weights["severity"] * severity
            + self.risk_weights["confidence"] * confidence
            + self.risk_weights["data_quality"] * quality
            + self.risk_weights["context"] * bounded_context
        )
        return {
            "severity": round(severity, 4),
            "confidence": round(confidence, 4),
            "data_quality": round(quality, 4),
            "context": round(bounded_context, 4),
            "weights": dict(self.risk_weights),
            "raw_score": round(score, 6),
            "final_score": round(min(max(score, 0.0), 1.0), 2),
        }


def load_ruleset() -> Ruleset:
    return Ruleset.load()
