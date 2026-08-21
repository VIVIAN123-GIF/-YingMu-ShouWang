# 2026-08-19 行为/语言算法联调变更

## 算法侧已完成

1. `TRAJECTORY` 继续支持视频、CSV 和脱敏 JSON 摘要。
2. JSON 包装可附带后端日聚合的 `trend.days`，用于生成：
   - `unusual_pacing`
   - `activity_range_decline`
   - `room_transition_decline`
3. `LANGUAGE` 不再读取 WAV、MP3 或逐字转写，只接受
   `language-analysis/1.0` 脱敏 JSON。
4. 居民回应 Observation 只输出：
   - `resident_response_help`
   - `resident_response_stable`
5. 公共 `AdapterBatch` 合同仍使用 `HELP/STABLE`，包装层执行以下固定映射：
   - `resident_response_help -> HELP`
   - `resident_response_stable -> STABLE`
6. 未明确匹配上述两类时，`resident_response_candidate=null`，算法不输出
   `UNCERTAIN`。
7. 输出不包含原始转写、音频路径、媒体路径、平台凭证或 `risk_level`。
8. 同一 `job_id` 重跑时 Observation/Evidence ID 保持稳定。

## 后端仍需处理

### 1. InterventionResult 映射

后端收到 `ResidentResponseCandidate.intent` 后，应写入：

```python
response_by_intent = {
    "HELP": "resident_response_help",
    "STABLE": "resident_response_stable",
}
```

公共合同中 `intent` 当前是字符串 Literal，不应调用 `candidate.intent.value`；应直接
使用 `candidate.intent`。也不应仅执行 `.lower()`，否则会得到不符合新口径的
`help/stable`。

### 2. AgentExplanation 输入白名单

AgentExplanation 只能接收后端整理后的 Observation/Evidence 摘要和
InterventionResult。禁止透传：

- `media_locator`
- 原始转写
- 音频路径或媒体路径
- 平台 Token、Secret 或其他凭证

### 3. request_id 幂等

`request_id` 不属于 `AlgorithmJob/AdapterBatch`，应由后端按“事件 ID + 事件版本”
确定性生成或持久化复用。重复查询时应先查询已完成的 AgentExplanation 作业，命中后
直接返回结果，不再次调用模型。

算法侧只保证：相同 `job_id` 和相同输入产生相同 Observation/Evidence ID；算法适配器
自身不调用 AgentExplanation 模型。

## 联调入口

```ini
YINGMU_TRAJECTORY_ADAPTER=adapters.trajectory_adapter:run
YINGMU_LANGUAGE_ADAPTER=adapters.language_adapter:run
```

验证命令：

```powershell
python -m pytest -q deliverables/cym/audio-behavior-demo/tests
```
