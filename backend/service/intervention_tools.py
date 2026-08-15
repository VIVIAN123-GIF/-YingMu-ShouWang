"""Explicit intervention tools with verified-capability boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.config import ENV_MODE, EZVIZ_DEVICE_SERIAL, EZVIZ_VOICE_VERIFIED
from backend.utils.ezviz_api import EzvizAPI


@dataclass(frozen=True)
class ToolExecution:
    delivery_status: str
    tool_name: str
    resolution_reason: str | None
    simulated: bool


class InterventionTool(Protocol):
    async def execute(self, event: object, action_text: str) -> ToolExecution:
        ...


class MockVoiceTool:
    async def execute(self, event: object, action_text: str) -> ToolExecution:
        return ToolExecution(
            delivery_status="SUCCESS",
            tool_name="mock_voice",
            resolution_reason=f"萤石服务端语音未验证，使用 Mock 语音降级；动作：{action_text}",
            simulated=True,
        )


class LocalTextTool:
    async def execute(self, event: object, action_text: str) -> ToolExecution:
        return ToolExecution(
            delivery_status="SUCCESS",
            tool_name="local_text",
            resolution_reason=f"使用前端文字提醒降级；动作：{action_text}",
            simulated=True,
        )


class EzvizVoiceTool:
    async def execute(self, event: object, action_text: str) -> ToolExecution:
        try:
            await EzvizAPI.voice_broadcast(EZVIZ_DEVICE_SERIAL, action_text)
        except Exception:
            return ToolExecution(
                delivery_status="FAILED",
                tool_name="ezviz_voice",
                resolution_reason=f"已验证的萤石语音调用失败，保留失败状态供重试；动作：{action_text}",
                simulated=False,
            )
        return ToolExecution(
            delivery_status="SUCCESS",
            tool_name="ezviz_voice",
            resolution_reason=None,
            simulated=False,
        )


def select_intervention_tool() -> InterventionTool:
    if ENV_MODE == "live" and EZVIZ_VOICE_VERIFIED:
        return EzvizVoiceTool()
    return MockVoiceTool()
