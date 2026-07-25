"""Deterministic v1.0 risk engine used by the Mock integration rehearsal."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

from pydantic import ValidationError

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
    QUALITY_THRESHOLD = 0.70
    CONFIDENCE_THRESHOLD = 0.70
    HIGH_CONFIDENCE_THRESHOLD = 0.80
    COMBINATION_WINDOW = timedelta(seconds=30)
    RECOVERY_OBSERVATION = timedelta(seconds=60)

    def __init__(self):
        self.observations: dict[str, Observation] = {}
        self.evidences: dict[str, Evidence] = {}
        self.events: dict[str, RiskEvent] = {}
        self.interventions: dict[str, InterventionResult] = {}
        self.recovery_at: dict[str, datetime] = {}
        self.tool_call_count = 0

    @staticmethod
    def _model_or_422(model, payload):
        return validate_contract(model, payload)

    @staticmethod
    def _same(existing, incoming) -> bool:
        return existing.model_dump(mode="json") == incoming.model_dump(mode="json")

    def ingest_observation(self, payload) -> Observation:
        incoming = self._model_or_422(Observation, payload)
        existing = self.observations.get(incoming.observation_id)
        if existing:
            if self._same(existing, incoming):
                return existing
            raise ConflictError(f"observation_id already exists: {incoming.observation_id}")
        self.observations[incoming.observation_id] = incoming
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
        existing = self.evidences.get(incoming.evidence_id)
        if existing:
            if self._same(existing, incoming):
                return existing
            raise ConflictError(f"evidence_id already exists: {incoming.evidence_id}")
        self.evidences[incoming.evidence_id] = incoming
        return incoming

    def evaluate(self, resident_id: str, now: datetime | None = None):
        if now is None:
            now = max((e.timestamp for e in self.evidences.values()), default=datetime.now().astimezone())
        matching = [e for e in self.evidences.values() if e.resident_id == resident_id]
        recent = [e for e in matching if now - e.timestamp <= self.COMBINATION_WINDOW and now >= e.timestamp]
        rapid = next((e for e in recent if e.evidence_type == "rapid_rise" and self._usable(e)), None)
        sway = next((e for e in recent if e.evidence_type == "trunk_sway" and self._usable(e)), None)
        active = next((event for event in self.events.values() if event.resident_id == resident_id and event.status not in {EventStatus.RESOLVED, EventStatus.ESCALATED, EventStatus.FALSE_ALARM}), None)
        recovered = next((e for e in recent if e.evidence_type == "posture_recovered" and self._usable(e)), None)
        recovery_duration_met = recovered and recovered.current_value is not None and recovered.current_value >= 15
        if active and recovery_duration_met and active.status in {EventStatus.INTERVENING, EventStatus.OPEN}:
            active.status = EventStatus.OBSERVING
            active.updated_at = recovered.timestamp
            self.recovery_at[active.event_id] = recovered.timestamp
            return active
        if active:
            return active
        if (
            rapid
            and sway
            and abs(sway.timestamp - rapid.timestamp) <= self.COMBINATION_WINDOW
            and max(rapid.confidence, sway.confidence) >= self.HIGH_CONFIDENCE_THRESHOLD
            and rapid.source_mode == sway.source_mode
            and rapid.simulated == sway.simulated
        ):
            created = max(rapid.timestamp, sway.timestamp)
            event = RiskEvent(
                schema_version="1.0",
                event_id="event-mock-fall-001",
                resident_id=resident_id,
                created_at=created,
                updated_at=created,
                primary_domain="FALL",
                related_domains=[],
                risk_level=RiskLevel.ORANGE,
                risk_score=0.82,
                evidence_ids=[rapid.evidence_id, sway.evidence_id],
                evidence_summary=[
                    EvidenceSummary(evidence_id=rapid.evidence_id, evidence_type=rapid.evidence_type, explanation=rapid.explanation),
                    EvidenceSummary(evidence_id=sway.evidence_id, evidence_type=sway.evidence_type, explanation=sway.explanation),
                ],
                time_horizon="IMMINENT",
                recommended_action="先坐稳，扶住固定物，再慢慢起身。",
                intervention_policy="fall-orange-gentle-v1",
                status=EventStatus.INTERVENING,
                ruleset_version="ruleset-v1.0",
                source_mode=rapid.source_mode,
                simulated=rapid.simulated or sway.simulated,
            )
            self.events[event.event_id] = event
            return event
        return None

    def intervene(self, event_id: str, now: datetime | None = None) -> InterventionResult:
        event = self.events.get(event_id)
        if event is None:
            raise ConflictError(f"unknown event_id: {event_id}")
        if event.status != EventStatus.INTERVENING:
            raise ConflictError(f"event is not INTERVENING: {event.status.value}")
        existing = self.interventions.get("result-mock-voice-001")
        if existing and existing.event_id == event_id:
            return existing
        if now is None:
            now = event.updated_at + timedelta(seconds=1)
        result = InterventionResult(
            schema_version="1.0",
            result_id="result-mock-voice-001",
            event_id=event_id,
            started_at=now,
            completed_at=now,
            action_type="voice",
            tool_name="mock_voice",
            delivery_status=DeliveryStatus.SUCCESS,
            resident_response=None,
            family_feedback=None,
            risk_after=0.62,
            resolved=False,
            resolution_reason=None,
            operator="system",
            source_mode="MOCK",
            simulated=True,
        )
        self.interventions[result.result_id] = result
        self.tool_call_count += 1
        event.updated_at = now
        return result

    def tick(self, event_id: str, now: datetime) -> RiskEvent:
        event = self.events.get(event_id)
        if event is None:
            raise ConflictError(f"unknown event_id: {event_id}")
        recovery_at = self.recovery_at.get(event_id)
        later_hazard = recovery_at and any(
            evidence.resident_id == event.resident_id
            and evidence.evidence_type in {"rapid_rise", "trunk_sway", "gait_instability"}
            and recovery_at < evidence.timestamp <= now
            and self._usable(evidence)
            for evidence in self.evidences.values()
        )
        if event.status == EventStatus.OBSERVING and later_hazard:
            event.status = EventStatus.INTERVENING
            event.updated_at = now
            return event
        if event.status == EventStatus.OBSERVING and recovery_at and now - recovery_at >= self.RECOVERY_OBSERVATION:
            event.status = EventStatus.RESOLVED
            event.updated_at = now
            result = next(iter(self.interventions.values()), None)
            if result and result.event_id == event_id:
                result.completed_at = now
                result.resident_response = "stable"
                result.risk_after = 0.24
                result.resolved = True
                result.resolution_reason = "姿态恢复且60秒观察期内无新风险证据"
        return event

    @staticmethod
    def _usable(evidence: Evidence) -> bool:
        return evidence.data_quality >= MockRiskEngine.QUALITY_THRESHOLD and evidence.confidence >= MockRiskEngine.CONFIDENCE_THRESHOLD

    def snapshot(self):
        return {
            "observations": [deepcopy(item.model_dump(mode="json")) for item in self.observations.values()],
            "evidence": [deepcopy(item.model_dump(mode="json")) for item in self.evidences.values()],
            "events": [deepcopy(item.model_dump(mode="json")) for item in self.events.values()],
            "interventions": [deepcopy(item.model_dump(mode="json")) for item in self.interventions.values()],
        }
