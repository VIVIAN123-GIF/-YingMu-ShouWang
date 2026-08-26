"""Deterministic risk engine used by the Mock integration rehearsal."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

from pydantic import ValidationError

from .memory import MemoryStore
from .decision import FallDecisionPolicy, quality_snapshot
from .models import (
    DeliveryStatus,
    EventStatus,
    Evidence,
    EvidenceSummary,
    InterventionResult,
    Observation,
    RiskEvent,
    RiskLevel,
)
from .ruleset import RuleTrace, Ruleset, load_ruleset
from .semantics import EvidenceSemanticError, validate_evidence_semantics


class ContractError(ValueError):
    status_code = 422


class ConflictError(ValueError):
    status_code = 409


def validate_contract(model, payload):
    """Validate an API payload and expose the planned HTTP 422 semantics."""
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        raise ContractError(str(error)) from error


class MockRiskEngine:
    """A small deterministic engine with explicit memory and explainable rules."""

    def __init__(self, ruleset: Ruleset | None = None):
        self.ruleset = ruleset or load_ruleset()
        self.policy = FallDecisionPolicy(self.ruleset)
        self.observations: dict[str, Observation] = {}
        self.evidences: dict[str, Evidence] = {}
        self.events: dict[str, RiskEvent] = {}
        self.interventions: dict[str, InterventionResult] = {}
        self.recovery_at: dict[str, datetime] = {}
        self.tool_call_count = 0
        self.intervention_attempts: dict[str, int] = {}
        self.traces: list[RuleTrace] = []
        self.memory = MemoryStore(self.ruleset)
        self._event_sequence = 0

    @staticmethod
    def _model_or_422(model, payload):
        return validate_contract(model, payload)

    @staticmethod
    def _same(existing, incoming) -> bool:
        return existing.model_dump(mode="json") == incoming.model_dump(mode="json")

    def _active_event(self, resident_id: str) -> RiskEvent | None:
        return next(
            (
                event for event in self.events.values()
                if event.resident_id == resident_id
                and event.status not in {EventStatus.RESOLVED, EventStatus.ESCALATED, EventStatus.FALSE_ALARM}
            ),
            None,
        )

    def _trace(
        self,
        *,
        resident_id: str,
        now: datetime,
        matched_rule: str,
        previous_state: RiskLevel,
        next_state: RiskLevel | str,
        reason: str,
        event_id: str | None = None,
        not_matched: dict[str, str] | None = None,
        context_snapshot: dict | None = None,
        score_components: dict | None = None,
    ) -> RuleTrace:
        snapshot = self.memory.snapshot(resident_id, now)
        trace = RuleTrace(
            evaluated_at=now,
            resident_id=resident_id,
            queried_windows={
                "short_seconds": snapshot["short"]["window_seconds"],
                "medium_hours": snapshot["medium"]["window_hours"],
                "long_days": snapshot["long"]["window_days"],
            },
            matched_rule=matched_rule,
            previous_state=previous_state.value,
            next_state=getattr(next_state, "value", next_state),
            reason=reason,
            not_matched=not_matched or {},
            event_id=event_id,
            ruleset_version=self.ruleset.version,
            thresholds=dict(self.ruleset.thresholds),
            baseline_snapshot=snapshot["long"]["baseline"],
            quality_snapshot=quality_snapshot(self.memory.query_short(resident_id, now), self.ruleset),
            context_snapshot=context_snapshot or {},
            score_components=score_components or {},
        )
        self.traces.append(trace)
        return trace

    def ingest_observation(self, payload) -> Observation:
        incoming = self._model_or_422(Observation, payload)
        existing = self.observations.get(incoming.observation_id)
        if existing:
            if self._same(existing, incoming):
                return existing
            raise ConflictError(f"observation_id already exists: {incoming.observation_id}")
        self.observations[incoming.observation_id] = incoming
        self.memory.add_observation(incoming)
        return incoming

    def ingest_evidence(self, payload) -> Evidence:
        incoming = self._model_or_422(Evidence, payload)
        linked = []
        for observation_id in incoming.observation_ids:
            observation = self.observations.get(observation_id)
            if observation is None:
                raise ConflictError(f"unknown observation_id: {observation_id}")
            linked.append(observation)
        if any(observation.resident_id != incoming.resident_id for observation in linked):
            raise ConflictError("resident_id does not match linked Observation")
        if any(observation.source_mode != incoming.source_mode or observation.simulated != incoming.simulated for observation in linked):
            raise ConflictError("source_mode/simulated does not match linked Observation")
        try:
            validate_evidence_semantics(incoming, linked, self.ruleset)
        except EvidenceSemanticError as error:
            raise ContractError(str(error)) from error
        existing = self.evidences.get(incoming.evidence_id)
        if existing:
            if self._same(existing, incoming):
                self._trace(
                    resident_id=incoming.resident_id,
                    now=incoming.timestamp,
                    matched_rule="R-SYSTEM-01",
                    previous_state=self.memory.state(incoming.resident_id),
                    next_state=self.memory.state(incoming.resident_id),
                    reason="same evidence_id and payload is idempotent",
                )
                return existing
            raise ConflictError(f"evidence_id already exists: {incoming.evidence_id}")
        self.evidences[incoming.evidence_id] = incoming
        self.memory.add_evidence(incoming)
        if incoming.data_quality < self.ruleset.thresholds["data_quality"]:
            self._record_quality_evidence(incoming)
            self._trace(
                resident_id=incoming.resident_id,
                now=incoming.timestamp,
                matched_rule="R-FALL-03",
                previous_state=self.memory.state(incoming.resident_id),
                next_state=self.memory.state(incoming.resident_id),
                reason="data_quality is below the engineering gate; no ORANGE upgrade",
            )
        return incoming

    def _record_quality_evidence(self, source: Evidence) -> None:
        evidence_id = f"sys-quality-{source.evidence_id}"
        if evidence_id in self.evidences:
            return
        system = Evidence(
            schema_version="1.0",
            evidence_id=evidence_id,
            observation_ids=source.observation_ids,
            resident_id=source.resident_id,
            timestamp=source.timestamp,
            risk_domain="SYSTEM",
            evidence_type="quality_gate_failed",
            severity=0.0,
            confidence=1.0,
            data_quality=source.data_quality,
            baseline_value=None,
            current_value=source.data_quality,
            baseline_deviation=None,
            time_scale=source.time_scale,
            location=source.location,
            explanation="数据质量低于工程门槛，本条证据不参与风险升级",
            adapter_version=self.ruleset.version,
            source_mode=source.source_mode,
            simulated=source.simulated,
        )
        self.evidences[evidence_id] = system
        self.memory.add_evidence(system)

    def _usable(self, evidence: Evidence) -> bool:
        return (
            evidence.risk_domain.value != "SYSTEM"
            and self.ruleset.usable(evidence.confidence, evidence.data_quality)
        )

    def _context_score(self, resident_id: str, now: datetime) -> float:
        snapshot = self.memory.snapshot(resident_id, now)
        score = 0.0
        if now.hour >= 22 or now.hour < 6:
            score += self.ruleset.context_factors["night"]
        if snapshot["medium"]["low_light_count"]:
            score += self.ruleset.context_factors["low_light"]
        if snapshot["medium"]["abnormal_rise_count"] >= 2:
            score += self.ruleset.context_factors["repeated_daily_abnormality"]
        if self.memory.state(resident_id) == RiskLevel.YELLOW:
            score += self.ruleset.context_factors["yellow_state"]
        if any(
            item.time_scale.value == "LONG"
            and item.baseline_deviation is not None
            and abs(float(item.baseline_deviation)) >= 2
            for item in self.memory.query_long(resident_id, now)
        ):
            score += self.ruleset.context_factors["long_term_deviation"]
        return min(score, 1.0)

    def _next_event_id(self, resident_id: str) -> str:
        if "event-mock-fall-001" not in self.events:
            return "event-mock-fall-001"
        self._event_sequence += 1
        return f"event-{resident_id}-fall-{self._event_sequence:03d}"

    def evaluate(self, resident_id: str, now: datetime | None = None):
        if now is None:
            now = max((e.timestamp for e in self.evidences.values()), default=datetime.now().astimezone())
        previous = self.memory.state(resident_id)
        active = self._active_event(resident_id)
        short = self.memory.query_short(resident_id, now)
        latest_intervention = max(
            (item for item in self.interventions.values() if active and item.event_id == active.event_id),
            key=lambda item: item.started_at,
            default=None,
        )
        trigger = max(
            (item for item in short if item.timestamp <= now),
            key=lambda item: item.timestamp,
            default=None,
        )
        context_score = self._context_score(resident_id, now)
        context_snapshot = {"context_score": context_score}
        decision = self.policy.evaluate(
            now=now,
            previous_state=previous.value,
            active_status=active.status.value if active else None,
            active_created_at=active.created_at if active else None,
            recovery_started_at=self.recovery_at.get(active.event_id) if active else None,
            recent=short,
            trigger=trigger,
            context_score=context_score,
            intervention_attempts=self.intervention_attempts.get(active.event_id, 0) if active else 0,
            latest_intervention_at=latest_intervention.started_at if latest_intervention else None,
        )
        next_state = decision.risk_level

        if decision.action == "CREATE_EVENT":
            selected = [self.evidences[item] for item in decision.evidence_ids]
            event_id = self._next_event_id(resident_id)
            created = max(item.timestamp for item in selected)
            event = RiskEvent(
                schema_version="1.0",
                event_id=event_id,
                resident_id=resident_id,
                created_at=created,
                updated_at=created,
                primary_domain="FALL",
                related_domains=[],
                risk_level=RiskLevel.ORANGE,
                risk_score=decision.score,
                evidence_ids=[item.evidence_id for item in selected],
                evidence_summary=[
                    EvidenceSummary(
                        evidence_id=item.evidence_id,
                        evidence_type=item.evidence_type,
                        explanation=item.explanation,
                    )
                    for item in selected
                ],
                time_horizon="IMMINENT",
                recommended_action="先坐稳，扶住固定物，再慢慢起身。",
                intervention_policy="fall-orange-gentle-v1",
                status=EventStatus.INTERVENING,
                ruleset_version=self.ruleset.version,
                source_mode=selected[-1].source_mode,
                simulated=any(item.simulated for item in selected),
            )
            self.events[event.event_id] = event
            self.memory.set_state(resident_id, RiskLevel.ORANGE)
            self._trace(resident_id=resident_id, now=now, matched_rule=decision.matched_rule,
                        previous_state=previous, next_state="ORANGE",
                        reason=decision.reason, event_id=event.event_id,
                        not_matched=decision.not_matched, context_snapshot=context_snapshot,
                        score_components=decision.score_components)
            return event

        if active and decision.action == "BEGIN_OBSERVING":
            active.status = EventStatus.OBSERVING
            active.updated_at = trigger.timestamp
            self.recovery_at[active.event_id] = trigger.timestamp
            self.memory.set_state(resident_id, RiskLevel.ORANGE)
        elif active and decision.action == "RESTART_INTERVENTION":
            hazard = self.evidences[decision.evidence_ids[0]]
            active.status = EventStatus.INTERVENING
            active.updated_at = hazard.timestamp
            self.recovery_at.pop(active.event_id, None)
            self.memory.set_state(resident_id, RiskLevel.ORANGE)
        elif active and decision.action == "ESCALATE":
            hazard = self.evidences[decision.evidence_ids[0]]
            active.risk_level = RiskLevel.RED
            active.risk_score = max(active.risk_score, decision.score or self.ruleset.thresholds["red_score"])
            active.status = EventStatus.ESCALATED
            active.updated_at = hazard.timestamp
            active.recommended_action = "通知家属并转人工接管，不自动拨打120。"
            active.intervention_policy = "fall-red-human-handoff-v1"
            self.memory.set_state(resident_id, RiskLevel.RED)
        elif active and decision.action == "RESOLVE":
            active.status = EventStatus.RESOLVED
            active.updated_at = now
            self.memory.set_state(resident_id, RiskLevel.GREEN)
            result = max(
                (item for item in self.interventions.values() if item.event_id == active.event_id),
                key=lambda item: item.started_at,
                default=None,
            )
            if result:
                result.completed_at = now
                result.resident_response = "stable"
                result.risk_after = 0.24
                result.resolved = True
                result.resolution_reason = "姿态恢复且60秒观察期内无新风险证据"

        self._trace(resident_id=resident_id, now=now, matched_rule=decision.matched_rule,
                    previous_state=previous, next_state=next_state, reason=decision.reason,
                    event_id=active.event_id if active else None,
                    not_matched=decision.not_matched, context_snapshot=context_snapshot,
                    score_components=decision.score_components)
        if active:
            return active
        return None

    def intervene(self, event_id: str, now: datetime | None = None) -> InterventionResult:
        event = self.events.get(event_id)
        if event is None:
            raise ConflictError(f"unknown event_id: {event_id}")
        if event.status != EventStatus.INTERVENING:
            raise ConflictError(f"event is not INTERVENING: {event.status.value}")
        existing = sorted((item for item in self.interventions.values() if item.event_id == event_id), key=lambda item: item.started_at)
        if existing and existing[-1].started_at >= event.updated_at:
            return existing[-1]
        if now is None:
            now = event.updated_at + timedelta(seconds=1)
        attempt = len(existing) + 1
        result_id = "result-mock-voice-001" if attempt == 1 and event_id == "event-mock-fall-001" else f"result-{event_id}-voice-{attempt:03d}"
        result = InterventionResult(
            schema_version="1.0",
            result_id=result_id,
            event_id=event_id,
            started_at=now,
            completed_at=now,
            action_type="voice",
            tool_name="mock_voice",
            delivery_status=DeliveryStatus.SUCCESS,
            resident_response=None,
            family_feedback=None,
            risk_after=0.62 if attempt == 1 else 0.55,
            resolved=False,
            resolution_reason=None,
            operator="system",
            source_mode="MOCK",
            simulated=True,
        )
        self.interventions[result.result_id] = result
        self.intervention_attempts[event_id] = attempt
        self.tool_call_count += 1
        event.updated_at = now
        return result

    def tick(self, event_id: str, now: datetime) -> RiskEvent:
        event = self.events.get(event_id)
        if event is None:
            raise ConflictError(f"unknown event_id: {event_id}")
        self.evaluate(event.resident_id, now)
        return self.events[event_id]

    def snapshot(self):
        return {
            "observations": [deepcopy(item.model_dump(mode="json")) for item in self.observations.values()],
            "evidence": [deepcopy(item.model_dump(mode="json")) for item in self.evidences.values()],
            "events": [deepcopy(item.model_dump(mode="json")) for item in self.events.values()],
            "interventions": [deepcopy(item.model_dump(mode="json")) for item in self.interventions.values()],
        }

    def decision_snapshot(self, resident_id: str, now: datetime) -> dict:
        return {
            "ruleset_version": self.ruleset.version,
            "memory": self.memory.snapshot(resident_id, now),
            "traces": [trace.as_dict() for trace in self.traces],
            "baseline_decisions": deepcopy(self.memory.baseline_decisions),
        }
