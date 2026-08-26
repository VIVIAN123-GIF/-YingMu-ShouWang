"""Deterministic explanations used when the text model is unavailable."""

from __future__ import annotations

from contracts.v1.agent import (
    AgentExplanationRequest,
    AgentExplanationResponse,
    PlatformCapability,
)


_EVIDENCE_TEXT = {
    "sit_to_stand_transition": "检测到一次有效坐站转换，已进入起身后观察窗口",
    "rapid_rise": "检测到起身速度偏快，该信号本身不代表起身后失稳",
    "slow_rise": "检测到起身速度偏慢，该信号本身不代表起身后失稳",
    "trunk_sway": "检测到起身后躯干持续摆动，稳定性需要继续观察",
    "post_rise_lateral_drift": "检测到起身后身体出现横向漂移",
    "support_base_change": "检测到起身后支撑面发生明显变化",
    "compensatory_step": "检测到起身后出现补偿步迹象",
    "assessment_indeterminate": "本次起身后评估不可判定，需要人工复核",
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
        if request.forewarning is not None:
            points.append(
                f"工程风险指数：即时{request.forewarning.instant_index:.2f}、"
                f"30秒{request.forewarning.short_30s_index:.2f}、3分钟{request.forewarning.trend_3min_index:.2f}；"
                f"置信等级为{request.forewarning.confidence_level}"
            )
            points = points[:4]

        if "posture_recovered" in {item.evidence_type for item in request.evidence}:
            summary = "检测到姿态恢复迹象，系统继续观察后续状态"
            action = "建议保持安全姿势并继续观察"
        elif request.intervention_status.value == "SUCCESS":
            summary = "起身后即时不稳事件已有干预记录，系统正在观察回应结果"
            action = "建议确认老人已回应并保持安全姿势"
        else:
            summary = "检测到起身后多信号不稳，需要继续关注老人当前状态"
            action = "建议提醒老人坐稳并继续观察"

        if PlatformCapability.EZVIZ_SERVER_VOICE in request.unverified_capabilities:
            notice = "萤石服务端语音尚未验证，将使用明确标记的文字或 Mock 提醒"
        else:
            notice = "解释基于结构化 Evidence 和工程风险指数生成，不是跌倒概率、临床结论，也不替代状态机裁决"

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
