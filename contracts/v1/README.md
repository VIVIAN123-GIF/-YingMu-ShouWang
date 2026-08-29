# 四对象契约 v1.0

本目录是7月31日前算法、智能体、后端和前端共同使用的唯一核心数据契约。

## 单一来源

- `models.py`：Pydantic v2唯一代码来源，未知字段一律拒绝；
- `schemas/`：由模型导出的JSON Schema，供前端和文档核对；
- `examples/`：四对象独立样例、跨端共用`four_objects.json`及固定跌倒Mock序列；
- `engine.py`：只用于一期Mock联调的确定性状态机；
- `rehearsal.py`：可复用的GREEN到RESOLVED演练流程。
- `memory.py`：短时30秒、中时24小时、长时7天的内存查询和中位数＋MAD基线；
- `ruleset.py`与版本化`rulesets/*.json`：按活动版本提供规则、门槛、信号族、权重和`RuleTrace`的唯一来源；默认兼容入口为冻结的v1.2，补充验证显式使用v1.4；
- `forewarning.py`与`rulesets/ruleset-v1.3-min.json`：独立工程预警快照、场景多边形、三时间尺度和基线权重；
- `examples/mock_memory_history.json`：明确标注为模拟的7天安全历史。

## 两周冲刺 D1 扩展合同

张同学的平台与智能体交接对象同样以本目录为单一来源：

- `platform.py`：内部 `PlatformSnapshotResult`，临时图片地址只允许传给后端下载器；
- `agent.py`：`AgentExplanationRequest/Response`、能力枚举和基线/干预状态；
- `schemas/platform_snapshot_result.schema.json`：平台抓拍归一化 JSON Schema；
- `schemas/agent_explanation_*.schema.json`：智能体请求和响应 JSON Schema；
- `schemas/algorithm_job.schema.json` 与 `schemas/adapter_batch.schema.json`：后端到算法适配器的严格边界；
- `examples/platform_snapshot_result.json` 与 `examples/agent_explanation_*.json`：D1 冻结样例。

智能体请求只接受结构化事件和 Evidence 摘要，不接受视频、音频、平台 Token、
设备序列号或临时 URL。智能体响应未知字段一律拒绝，因此不能新增或修改
`risk_level`、`risk_score`、`resolved` 或规则 ID。

重新导出Schema和样例：

```powershell
python scripts/export_contract_schemas.py
```

运行35项以上自动校验：

```powershell
python -m unittest discover -s tests -v
```

连续复现三次固定闭环：

```powershell
python scripts/run_mock_sequence.py --runs 3
python scripts/run_memory_ruleset_rehearsal.py --runs 3
```

## 核心对象与页面模型的边界

`title`、`timeline`、`risk_history`、`interventions`、`observations`等是前端组合展示字段，不属于RiskEvent核心契约。前端可以由四对象构建ViewModel，但不得修改核心枚举、字段含义或自行计算风险等级。

字段变更需由张薇和冷雨彤共同批准，并同步更新模型、Schema、样例、测试和冻结记录。

## 已冻结的跨端决定

- Evidence核心对象不包含`asset_id`，素材通过`observation_ids → Observation.asset_id`追溯；
- GREEN是引擎和Dashboard状态，不创建核心RiskEvent；RiskEvent必须至少关联一条Evidence；
- `MemorySnapshot`和`RuleTrace`是智能体内部决策追踪对象，不扩展四对象契约；
- `ruleset-v1.2`中的阈值和权重是工程初值，不是实验或医学结论；
- `ruleset-v1.3-min`输出工程风险指数，不是未来跌倒概率，也不替代`RiskEvent`裁决；
- `ruleset-v1.4`仅用于独立补充验证及明确选择该版本的运行环境，不改写v1.2/v1.3-min或P03结果；
- `ruleset-v1.5`仅用于已知素材的探索性软件整改，增加活动上下文、两周期准入和持续趋势门控；它不是新的正式盲测版本，生产默认仍保持v1.4；
- 前端、后端和算法联调统一使用`examples/four_objects.json`，不得复制后自行扩展v1.0字段。
