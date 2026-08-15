"""Deterministic explanations used when the text model is unavailable."""

from __future__ import annotations

from contracts.v1.agent import (
    AgentExplanationRequest,
    AgentExplanationResponse,
    PlatformCapability,
)


_EVIDENCE_TEXT = {
    "rapid_rise": "检测到起身速度偏快，超出当前风险评估关注范围",
    "trunk_sway": "检测到躯干持续摇摆，稳定性需要继续观察",
    "gait_instability": "检测到步态或重心稳定性异常",
    "relative_speed_change": "检测到活动速度相对个人基线发生变化",
    "tracking_lost": "当前画面跟踪质量不足，暂不能稳定判断姿态",
    "posture_recovered": "检测到姿态恢复迹象，仍需完成观察窗口",
    "high_risk_zone_entry": "检测到进入已标记的高风险区域",
}


class TemplateFallback:
    """Generate a bounded, auditable response without making a new decision."""

    generated_by = "template-fallback-v1"

    def generate(self, request: AgentExplanationRequest) -> AgentExplanationResponse:
        points: list[str] = []
        for item in request.evidence:
            text = _EVIDENCE_TEXT.get(
                item.evidence_type,
                item.explanation,
            )
            if text and text not in points:
                points.append(text[:160])
            if len(points) == 4:
                break
        if not points:
            points = ["当前结构化证据不足，建议继续观察"]

        if "posture_recovered" in {item.evidence_type for item in request.evidence}:
            summary = "检测到姿态恢复迹象，系统继续观察后续状态"
            action = "建议保持安全姿势并继续观察"
        elif request.intervention_status.value == "SUCCESS":
            summary = "风险事件已有干预记录，系统正在观察回应结果"
            action = "建议确认老人已回应并保持安全姿势"
        else:
            summary = "检测到跌倒风险前兆，需要继续关注老人状态"
            action = "建议提醒老人坐稳并继续观察"

        if PlatformCapability.EZVIZ_SERVER_VOICE in request.unverified_capabilities:
            notice = "萤石服务端语音尚未验证，将使用明确标记的文字或 Mock 提醒"
        else:
            notice = "解释基于结构化 Evidence 生成，不替代风险状态机裁决"

        return AgentExplanationResponse(
            schema_version="agent-explanation/1.0",
            request_id=request.request_id,
            event_id=request.event_id,
            summary=summary,
            reasoning_points=points,
            recommended_action_text=action,
            capability_notice=notice,
            generated_by=self.generated_by,
            fallback_used=True,
        )
