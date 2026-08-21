"""Orchestration, fallback, and bounded idempotence for agent explanations."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from contracts.v1.agent import AgentExplanationRequest, AgentExplanationResponse

from .agent_fallback import TemplateFallback
from .agent_provider import LLMProvider, OpenAICompatibleLLMProvider


class ExplanationRequestConflict(ValueError):
    """The same request ID was reused with different structured input."""


@dataclass
class _CacheEntry:
    fingerprint: str
    response: AgentExplanationResponse
    expires_at: float


class AgentExplanationService:
    def __init__(
        self,
        provider: LLMProvider | None = None,
        fallback: TemplateFallback | None = None,
        *,
        max_cache_entries: int = 512,
        cache_ttl_seconds: float = 900.0,
    ) -> None:
        if max_cache_entries <= 0 or cache_ttl_seconds <= 0:
            raise ValueError("cache limits must be positive")
        self.provider = provider
        self.fallback = fallback or TemplateFallback()
        self.max_cache_entries = max_cache_entries
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()

    @staticmethod
    def request_id_for_event(event_id: str, version: str) -> str:
        digest = hashlib.sha256(f"{event_id}:{version}".encode()).hexdigest()[:24]
        safe_event_id = re.sub(r"[^A-Za-z0-9_-]", "-", event_id)[:64]
        return f"agent-{safe_event_id}-{digest}"

    @staticmethod
    def _fingerprint(request: AgentExplanationRequest) -> str:
        return json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _get_cached(self, request: AgentExplanationRequest, fingerprint: str) -> AgentExplanationResponse | None:
        entry = self._cache.get(request.request_id)
        if entry is None:
            return None
        if entry.expires_at <= time.monotonic():
            del self._cache[request.request_id]
            return None
        if entry.fingerprint != fingerprint:
            raise ExplanationRequestConflict(
                f"request_id {request.request_id} was reused with different input"
            )
        self._cache.move_to_end(request.request_id)
        return entry.response

    def _store(
        self,
        request: AgentExplanationRequest,
        fingerprint: str,
        response: AgentExplanationResponse,
    ) -> AgentExplanationResponse:
        self._cache[request.request_id] = _CacheEntry(
            fingerprint=fingerprint,
            response=response,
            expires_at=time.monotonic() + self.cache_ttl_seconds,
        )
        self._cache.move_to_end(request.request_id)
        while len(self._cache) > self.max_cache_entries:
            self._cache.popitem(last=False)
        return response

    async def explain(self, request: AgentExplanationRequest) -> AgentExplanationResponse:
        fingerprint = self._fingerprint(request)
        cached = self._get_cached(request, fingerprint)
        if cached is not None:
            return cached
        if self.provider is not None:
            try:
                response = await self.provider.generate(request)
                response = AgentExplanationResponse.model_validate(response)
                if (
                    response.request_id != request.request_id
                    or response.event_id != request.event_id
                    or response.fallback_used
                ):
                    raise ValueError("provider response identity or fallback flag is invalid")
                return self._store(request, fingerprint, response)
            except Exception:
                pass
        response = self.fallback.generate(request)
        return self._store(request, fingerprint, response)

    async def explain_payload(self, payload: dict[str, Any]) -> AgentExplanationResponse:
        return await self.explain(AgentExplanationRequest.model_validate(payload))


def build_default_agent_explanation_service() -> AgentExplanationService:
    """Build a configured provider when present, otherwise use safe fallback only."""
    from backend.config import (
        AGENT_LLM_API_KEY,
        AGENT_LLM_BASE_URL,
        AGENT_LLM_MAX_OUTPUT_TOKENS,
        AGENT_LLM_MODEL,
        AGENT_LLM_TIMEOUT_SECONDS,
    )

    provider = None
    if AGENT_LLM_BASE_URL and AGENT_LLM_MODEL:
        provider = OpenAICompatibleLLMProvider(
            base_url=AGENT_LLM_BASE_URL,
            api_key=AGENT_LLM_API_KEY,
            model=AGENT_LLM_MODEL,
            timeout_seconds=AGENT_LLM_TIMEOUT_SECONDS,
            max_output_tokens=AGENT_LLM_MAX_OUTPUT_TOKENS,
        )
    return AgentExplanationService(provider=provider)
