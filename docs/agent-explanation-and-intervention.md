# D3 智能体解释与干预能力

## 边界

智能体只消费风险引擎已经确定的 `RiskEvent` 和结构化 `Evidence`，生成解释和建议；它不识别原始视频，不上传图片、音频或视频，也不修改 `risk_level`、`risk_score`、`resolved` 或规则结论。

```text
RiskEvent + Evidence
        -> AgentExplanationRequest
        -> AgentExplanationService
           -> configured LLMProvider
           -> TemplateFallback
        -> AgentExplanationResponse
```

同一事件的 `request_id` 由 `event_id` 和事件版本生成。服务使用有界内存缓存（最多 512 条、默认 15 分钟），重复请求返回原结果，不重复调用模型。当前后端已使用持久化 Explanation 任务记录事件版本、结构化请求、生成结果、来源、降级标记和脱敏错误码；模型调用在独立 Agent Worker 中执行，不阻塞 RiskEvent 数据库事务。

## 配置

可选的 OpenAI-compatible Provider 配置：

```dotenv
AGENT_LLM_BASE_URL=https://openai.ezviz.com/v1
AGENT_LLM_API_KEY=
AGENT_LLM_MODEL=qwen3.6-flash
AGENT_LLM_TIMEOUT_SECONDS=30
AGENT_LLM_MAX_OUTPUT_TOKENS=400
```

`AGENT_LLM_BASE_URL` 或 `AGENT_LLM_MODEL` 为空时，服务只使用模板降级。API Key 只允许存在本地 `.env`，禁止写入代码、测试样例和交付报告。平台示例中的 `EZVIZ_API_KEY` 可作为兼容别名，但项目统一推荐使用 `AGENT_LLM_API_KEY`，避免和设备开放平台凭证混淆。

Provider 失败、超时、429、5xx、非法 JSON 或响应合同校验失败时，服务返回：

```text
generated_by=template-fallback-v1
fallback_used=true
```

配置完成后执行一次真实验证：

```powershell
py -3.14 scripts/validate_agent_llm_live.py
```

只有报告中 `result=SUCCESS`、`fallback_used=false`、`generated_by=qwen3.6-flash` 才表示真实模型调用成功；`FALLBACK` 只证明降级链路可用。

2026-08-16 对萤石 Token Switch `qwen3.6-flash` 的现场验证结果：5 秒和 15 秒超时配置均进入模板降级；30 秒配置成功返回，实测耗时 23584 ms。因此演示环境使用 30 秒超时，并在 RiskEvent 提交后异步生成解释。前端应先显示“解释生成中”，模型失败或超过 30 秒时再显示模板解释，不能阻塞风险事件入库和干预状态机。

模型仅可解释输入证据，不得宣称已经发生跌倒、进行医学诊断、自行定义风险区间，或自行触发报警和紧急流程。干预是否升级仍由风险引擎、状态机和人工确认共同决定。

## 干预工具

| 工具 | 启用条件 | 结果 |
|---|---|---|
| `ezviz_voice` | `YINGMU_ENV=live` 且 `EZVIZ_VOICE_VERIFIED=true` | 真实调用，`simulated=false` |
| `mock_voice` | 萤石语音未验证或不可用 | 明确降级，`simulated=true` |
| `local_text` | 前端文字提醒 | 明确降级，`simulated=true` |

干预工具只记录 `InterventionResult`，不会直接把事件标记为已恢复。恢复必须由现有状态机结合 `posture_recovered` 和观察窗口完成。

## 当前能力矩阵

| 能力 | 状态 |
|---|---|
| Token 获取 | 已验证 |
| 设备状态 | 已验证 |
| WebHook真实回调 | 已验证 |
| 真实抓拍 | 已验证；最新批次10/10成功，历史超时记录保留 |
| 真实告警自动抓拍 | 已验证 |
| Asset 私有入库 | 已验证 |
| 临时播放地址 | 部分验证或未稳定验证 |
| 萤石 `qwen3.6-flash` | 已验证；真实调用22980 ms |
| RiskEvent 智能体解释 | 已验证；可持久化并通过事件接口查询 |
| 模板解释降级 | 已实现并通过测试 |
| 萤石服务端语音 | 未验证 |
| Mock 语音/文字提醒 | 已实现 |
| 授权 MP4 风险闭环 | 已验证；`RECORDED_REPLAY/simulated=true` |
| 真实设备时序闭环 | 尚未完整验证 |

## 联调顺序

1. RiskEvent 在数据库事务提交后创建幂等 Explanation 任务。
2. Agent Worker 异步调用 `AgentExplanationService.explain()`，成功或模板降级结果均持久化。
3. 前端通过 `GET /api/v1/events/{event_id}/explanation` 独立轮询，不阻塞事件详情。
4. 前端分栏展示风险引擎结果、智能体解释、能力提示和降级状态。
5. 干预由状态机或前端按钮触发，不能由模型自行触发。

## 最终验证证据

- 萤石 Token Switch `qwen3.6-flash`：`deliverables/zhang-d3-agent-llm/ezviz-qwen-live-validation-final.json`，结果 `SUCCESS`，耗时22980 ms，`fallback_used=false`；
- 授权录像闭环：`deliverables/lyt-mp4-worker-e2e/closed-loop-validation.json`，事件依次命中 `R-FALL-02`、`R-FALL-04`、`R-FALL-05` 并最终 `RESOLVED`；
- 最新 Explanation：`generated_by=qwen3.6-flash`、`fallback_used=false`，API 时间带 `+08:00`；
- 干预：当前验证工具为 `mock_voice`，`simulated=true`；萤石服务端语音仍未验证。
