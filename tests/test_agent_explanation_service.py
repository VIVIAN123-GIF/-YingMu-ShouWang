from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from backend.service.agent_explanation_service import (
    AgentExplanationService,
    ExplanationRequestConflict,
)
from backend.service.agent_provider import OpenAICompatibleLLMProvider
from contracts.v1.agent import (
    AgentBaselineStatus,
    AgentEvidenceItem,
    AgentExplanationRequest,
    AgentInterventionStatus,
    PlatformCapability,
)
from contracts.v1.models import RiskLevel, TimeHorizon


def request(request_id: str = "agent-event-001-v1") -> AgentExplanationRequest:
    return AgentExplanationRequest(
        schema_version="agent-explanation/1.0",
        request_id=request_id,
        event_id="event-001",
        resident_id="resident-001",
        risk_level=RiskLevel.ORANGE,
        risk_score=0.82,
        time_horizon=TimeHorizon.IMMINENT,
        evidence=[
            AgentEvidenceItem(
                evidence_type="rapid_rise",
                explanation="起身时长1.1秒，短于个人基线2.4秒",
            ),
            AgentEvidenceItem(
                evidence_type="trunk_sway",
                explanation="躯干摆幅高于个人基线",
            ),
        ],
        baseline_status=AgentBaselineStatus.STABLE,
        intervention_status=AgentInterventionStatus.NOT_STARTED,
        verified_capabilities=[PlatformCapability.EZVIZ_CAPTURE],
        unverified_capabilities=[PlatformCapability.EZVIZ_SERVER_VOICE],
    )


class Provider:
    def __init__(self, value=None, error: Exception | None = None):
        self.calls = 0
        self.value = value
        self.error = error

    async def generate(self, payload):
        self.calls += 1
        if self.error:
            raise self.error
        return self.value


def llm_response_payload(req: AgentExplanationRequest) -> dict:
    return {
        "summary": "老人快速起身后出现持续摇摆",
        "reasoning_points": ["起身速度偏离个人基线", "摇摆证据需要继续观察"],
        "recommended_action_text": "建议提醒老人坐稳并继续观察",
        "capability_notice": "设备服务端语音尚未验证",
    }


def test_provider_success_uses_validated_json_without_sensitive_media():
    req = request()
    captured = {}

    async def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {"content": json.dumps(llm_response_payload(req), ensure_ascii=False)},
                }],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider(
        base_url="https://llm.example.test/v1",
        api_key="test-key",
        model="test-model",
        client=client,
    )
    result = asyncio.run(provider.generate(req))
    asyncio.run(client.aclose())

    assert result.fallback_used is False
    assert result.request_id == req.request_id
    assert result.generated_by == "test-model"
    assert captured["temperature"] == 0
    assert "image" not in json.dumps(captured).lower()
    assert "video" not in json.dumps(captured).lower()


@pytest.mark.parametrize("error", [TimeoutError("timeout"), RuntimeError("429"), ValueError("bad json")])
def test_provider_failures_use_template_fallback(error):
    provider = Provider(error=error)
    service = AgentExplanationService(provider=provider)

    result = asyncio.run(service.explain(request()))

    assert result.fallback_used is True
    assert result.generated_by == "template-fallback-v1"
    assert result.event_id == "event-001"
    assert provider.calls == 1


def test_same_request_id_is_idempotent_and_changed_payload_conflicts():
    req = request()
    provider = Provider(error=RuntimeError("unavailable"))
    service = AgentExplanationService(provider=provider)

    first = asyncio.run(service.explain(req))
    second = asyncio.run(service.explain(req))
    assert first == second
    assert provider.calls == 1

    changed = req.model_copy(update={"risk_score": 0.91})
    with pytest.raises(ExplanationRequestConflict):
        asyncio.run(service.explain(changed))


def test_invalid_provider_response_is_degraded_by_service():
    req = request()
    invalid = req.model_copy(update={"event_id": "different-event"})
    service = AgentExplanationService(provider=Provider(value=invalid))

    result = asyncio.run(service.explain(req))
    assert result.fallback_used is True


def test_request_id_is_stable_for_event_version():
    first = AgentExplanationService.request_id_for_event("event-1", "ORANGE-v1")
    second = AgentExplanationService.request_id_for_event("event-1", "ORANGE-v1")
    third = AgentExplanationService.request_id_for_event("event-1", "ORANGE-v2")
    assert first == second
    assert first != third
    assert len(AgentExplanationService.request_id_for_event("x" * 300, "v1")) <= 128
