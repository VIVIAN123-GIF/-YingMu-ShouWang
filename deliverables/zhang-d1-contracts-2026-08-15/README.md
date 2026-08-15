# 张同学 D1 平台与智能体合同冻结记录

日期：2026-08-15

状态：`FROZEN_FOR_D2_INTEGRATION`

## 本日交付

| 交付物 | 代码来源 | JSON Schema | 固定样例 |
|---|---|---|---|
| PlatformSnapshotResult | `contracts/v1/platform.py` | `contracts/v1/schemas/platform_snapshot_result.schema.json` | `contracts/v1/examples/platform_snapshot_result.json` |
| AgentExplanationRequest | `contracts/v1/agent.py` | `contracts/v1/schemas/agent_explanation_request.schema.json` | `contracts/v1/examples/agent_explanation_request.json` |
| AgentExplanationResponse | `contracts/v1/agent.py` | `contracts/v1/schemas/agent_explanation_response.schema.json` | `contracts/v1/examples/agent_explanation_response.json` |

## 冻结决定

1. `PlatformSnapshotResult` 只用于张同学的平台适配器到冷同学下载器的内部交接。
2. `temporary_url` 是必需的 LIVE 抓拍内部字段，在 Schema 中标记为 `writeOnly`，不得进入日志、RuleTrace、Asset 元数据或前端响应。
3. 平台抓拍只接受 `LIVE_DEVICE` 与 `MOCK`；LIVE 必须 `simulated=false`，MOCK 必须 `simulated=true`。
4. 所有抓拍时间必须包含时区；`expires_at` 如存在，必须晚于 `captured_at`。
5. 智能体只接收结构化 RiskEvent 摘要、Evidence 解释、基线状态、干预状态和能力矩阵，不接收原始媒体。
6. 能力只能从冻结枚举中选择，`verified_capabilities` 和 `unverified_capabilities` 不得重复或重叠。
7. 智能体响应只包含解释和建议文本，不能输出安全等级、风险分、解除状态或规则 ID。

## D2 交接边界

- 张同学：使用 `PlatformSnapshotResult` 包装 10 次真实萤石抓拍调用并保存脱敏记录。
- 冷同学：只在后端进程内消费 `temporary_url`，下载、校验并创建 Asset。
- 陈同学：只消费 Asset 和 AgentExplanation 公共字段，不读取平台抓拍临时 URL。
- 蔡同学：核对 10 次抓拍的现场画面、设备在线状态和机位版本。

## 验证命令

```powershell
python scripts/export_contract_schemas.py
pytest -q tests/test_zhang_d1_contracts.py
```
