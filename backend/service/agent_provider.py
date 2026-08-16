"""Provider boundary for structured text-model explanations."""

from __future__ import annotations

import json
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from contracts.v1.agent import AgentExplanationRequest, AgentExplanationResponse


class LLMProvider(Protocol):
    async def generate(self, request: AgentExplanationRequest) -> AgentExplanationResponse:
        """Generate a validated explanation from structured event data only."""


class LLMProviderError(RuntimeError):
    """Raised when a provider response cannot be safely consumed."""


class _ProviderContent(BaseModel):
    """Only explanatory text is model-controlled; identity stays server-owned."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str = Field(min_length=1, max_length=200)
    reasoning_points: list[str] = Field(min_length=1, max_length=4)
    recommended_action_text: str = Field(min_length=1, max_length=200)
    capability_notice: str = Field(min_length=1, max_length=240)


class OpenAICompatibleLLMProvider:
    """Minimal OpenAI-compatible chat-completions adapter.

    The optional client injection keeps tests deterministic and avoids network calls.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 5.0,
        max_output_tokens: int = 400,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url or not model:
            raise ValueError("base_url and model are required")
        if timeout_seconds <= 0 or max_output_tokens <= 0:
            raise ValueError("provider limits must be positive")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self._client = client

    @staticmethod
    def _messages(request: AgentExplanationRequest) -> list[dict[str, str]]:
        payload = request.model_dump(mode="json")
        return [
            {
                "role": "system",
                "content": (
                    "你是居家养老安全系统的解释助手。只能解释输入的结构化风险事件和Evidence，"
                    "不能新增或修改risk_level、risk_score、resolved或规则结论。"
                    "只返回JSON对象，不要输出Markdown。JSON必须且只能包含："
                    '{"summary":"不超过200字",'
                    '"reasoning_points":["1至4条，每条不超过160字"],'
                    '"recommended_action_text":"不超过200字",'
                    '"capability_notice":"不超过240字"}。'
                    "不得返回request_id、event_id、generated_by、fallback_used或其他字段。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
        ]

    async def generate(self, request: AgentExplanationRequest) -> AgentExplanationResponse:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": self.model,
            "messages": self._messages(request),
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            try:
                envelope = response.json()
                content = envelope["choices"][0]["message"]["content"]
                decoded = json.loads(content) if isinstance(content, str) else content
                content_result = _ProviderContent.model_validate(decoded)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise LLMProviderError("provider returned invalid explanation JSON") from exc
            return AgentExplanationResponse(
                schema_version="agent-explanation/1.0",
                request_id=request.request_id,
                event_id=request.event_id,
                summary=content_result.summary,
                reasoning_points=content_result.reasoning_points,
                recommended_action_text=content_result.recommended_action_text,
                capability_notice=content_result.capability_notice,
                generated_by=self.model,
                fallback_used=False,
            )
        except LLMProviderError:
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            raise LLMProviderError("provider request failed") from exc
        finally:
            if owns_client:
                await client.aclose()
