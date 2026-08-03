# 8月1—7日算法、智能体与后端联调交付

版本：`handoff-v1.0`

冻结契约：`schema_version=1.0`

冻结规则：`ruleset-v1.0`

接口时区：所有时间必须含偏移量，联调统一使用 `+08:00`

本目录回答后端提出的五类交付要求：可启动服务、请求/响应 JSON Schema、正常与异常样例、错误与超时约定、Observation/Evidence 字段映射，并给出五步决策规则的输入输出和验收结果。

## 1. 交付结论与边界

1. 算法适配器只生成 `Observation` 和 `Evidence`，不得生成风险等级或事件状态。
2. `contracts/v1/decision.py` 是智能体和 FastAPI 共用的唯一跌倒决策核心；阈值只读 `contracts/v1/rulesets/ruleset-v1.0.json`。
3. `POST /api/v1/evidence` 成功入库后同步执行一次决策，并在响应的 `evaluation` 中返回规则结果。
4. `POST /api/v1/risk/evaluate` 不接收 Evidence；它按 `resident_id + evaluated_at` 对已入库证据复评，主要用于观察窗口计时和显式重算。
5. 决策告警业务记录是 `RiskEvent`。`RiskAlarm` 仅保存萤石云 WebHook 原始告警，两者不得混为一张记录。
6. `ruleset-v1.0` 当前只冻结了跌倒域的自动升级和回落规则。语音、行为、心理和诈骗 Evidence 可以校验、入库与追溯，但 v1.0 不得据此自行创建 ORANGE/RED 事件。
7. 本文中的阈值是工程联调初值，不是医学诊断阈值。

## 2. 三方接口交付矩阵

| 负责人 | 模块输出 | 交付入口 | 后端收到后负责 |
|---|---|---|---|
| 赵勇 | 姿态/步态 Observation 与 FALL Evidence | 先 `POST /assets`，再 `/observations`，最后 `/evidence` | 引用校验、授权资产门禁、幂等入库、跌倒决策 |
| 常易铭 | 语音/行为 Observation 与 MENTAL/FRAUD/SYSTEM Evidence | `/observations` → `/evidence` | 契约校验、入库、留痕；v1.0 不自动升级非跌倒事件 |
| 张薇 | 五步决策结果、RuleTrace、RiskEvent 状态迁移 | `/evidence` 的 `evaluation`；`/risk/evaluate`；`/events/{id}` | 持久化、重试降级、干预结果和事件闭环验证 |

完整契约的代码唯一来源：

- `contracts/v1/models.py`
- `contracts/v1/schemas/observation.schema.json`
- `contracts/v1/schemas/evidence.schema.json`
- `contracts/v1/schemas/risk_event.schema.json`
- `contracts/v1/schemas/intervention_result.schema.json`

运行时端点包装 Schema 以 FastAPI 的 `/openapi.json` 为准。本目录另外提供Observation/Evidence创建响应、决策复评请求/响应和统一错误响应 Schema。

## 3. 可启动服务

在集成仓库根目录启动独立联调数据库：

```powershell
python -m pip install -r backend/requirements.txt
$env:YINGMU_ENV='mock'
$env:YINGMU_DB_PATH="$env:TEMP\yingmu-agent-handoff.db"
python -m backend.db.init_db
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

预期：

```json
{
  "status": "ok",
  "schema_version": "1.0",
  "ruleset_version": "ruleset-v1.0"
}
```

接口入口：

| 方法与路径 | 用途 | 正常状态码 |
|---|---|---:|
| `POST /api/v1/assets` | 登记授权素材 | 新建201；同内容幂等200 |
| `POST /api/v1/observations` | 保存完整观测 | 新建201；同内容幂等200 |
| `POST /api/v1/evidence` | 保存证据并同步决策 | 新建201；同内容幂等200 |
| `POST /api/v1/risk/evaluate` | 对已入库证据显式复评/推进时间 | 200 |
| `GET /api/v1/events/{event_id}` | 获取事件、证据、观测、RuleTrace、干预 | 200 |
| `POST /api/v1/events/{event_id}/intervene` | 执行语音或明确标记的Mock干预 | 200 |
| `POST /api/v1/events/{event_id}/results` | 保存工具执行结果 | 新建201；幂等200 |

真实 `RECORDED_REPLAY + FALL` 必须严格按 `Asset → Observation → Evidence` 提交。Mock 与非跌倒样例不应冒充真实 C6c 验收。

## 4. 五步决策模块

### 第一步：接收并规范化多模态证据

输入：已经通过冻结 Evidence 契约校验的对象，以及其 `observation_ids` 引用的完整 Observation。

输出：

- 合法：Evidence 入库并进入后续决策；
- 低质量：Evidence 仍入库，另生成内部质量记录，匹配 `R-FALL-03`，不升级；
- 契约或语义错误：422，不入状态机；
- 引用、居民、来源或资产冲突：409，不入状态机。

Evidence 不携带 `asset_id`。素材固定通过 `Evidence.observation_ids → Observation.asset_id → Asset` 追溯。

### 第二步：读取个人基线

输入：`resident_id`、评估时间、相同脱敏设备和相同机位下的安全历史样本。

输出到 RuleTrace：

- `baseline_snapshot.overall_status`：`INSUFFICIENT` 或 `PROVISIONAL`；
- 三项工程基线：起身时长、相对步速、稳定躯干角度；
- 样本数、不同日期数、机位来源。

少于3个日期显示 `INSUFFICIENT`；同机位三日且样本合格后为 `PROVISIONAL`。公开数据、Mock、低质量、危险和非GREEN时段不得进入真实个人基线。基线不足不会阻断短时安全规则，但必须在 RuleTrace 中明确显示。

### 第三步：质量门控和上下文校正

Evidence 可用条件为闭区间门槛：

```text
confidence >= 0.70 AND data_quality >= 0.70
```

组合证据还要求至少一条：

```text
confidence >= 0.80
```

上下文贡献来自24小时/7天记忆，求和后截断到 `[0,1]`：

| 上下文 | 权重 | 当前说明 |
|---|---:|---|
| 夜间（22:00—05:59） | 0.25 | 已执行 |
| 低照度 Evidence | 0.25 | 已执行 |
| 24小时内至少2次快速起身 | 0.20 | 已执行 |
| YELLOW状态 | 0.40 | v1.0无YELLOW生成规则，当前保留为0 |
| 长期偏离绝对值至少2 | 0.20 | 已执行 |

质量和上下文必须原样写入 RuleTrace，前端不得重新计算。

### 第四步：三时标融合、评分和事件升级

记忆窗口：短时30秒、中时24小时、长时7天。

R-FALL-02 的组合条件：

```text
同一 resident_id
rapid_rise 与 trunk_sway 时间差绝对值 <= 30秒
两条 confidence、data_quality 均 >= 0.70
至少一条 confidence >= 0.80
当前不存在未关闭的风险事件
```

满足后创建一个 `RiskEvent`：

```text
risk_level = ORANGE
status = INTERVENING
time_horizon = IMMINENT
recommended_action = 先坐稳，扶住固定物，再慢慢起身
intervention_policy = fall-orange-gentle-v1
```

风险分不是固定值，公式为：

```text
severity_component = max(组合Evidence.severity)
confidence_component = max(组合Evidence.confidence)
quality_component = min(组合Evidence.data_quality)
context_component = min(max(context_score, 0), 1)

risk_score = round(
  0.45*severity_component
  + 0.30*confidence_component
  + 0.15*quality_component
  + 0.10*context_component,
  2
)
```

当前 v1.0 以“有效组合规则命中”作为 ORANGE 创建条件，`orange_score=0.70` 会进入 RuleTrace，但不作为第二个拒绝门槛；后端不得另加一套评分门槛。验收标准样例的动态分数应达到0.70以上。

### 第五步：干预、恢复和回落复核

1. ORANGE事件创建后进入 `INTERVENING`；工具执行成功只生成 `InterventionResult`，不能直接解除事件。
2. `posture_recovered.current_value` 必须是连续稳定秒数，`baseline_value=15.0`。
3. Evidence 必须同时引用 `stable_posture_duration` 和 `stable_trunk_angle_deg` 两条 Observation。
4. `current_value < 15.0`：仍为 `INTERVENING`。
5. `current_value >= 15.0`：匹配 `R-FALL-04`，进入 `OBSERVING`。
6. 从进入 OBSERVING 的恢复 Evidence 时间开始，满60秒且无新可用危险 Evidence：匹配 `R-FALL-05`，事件状态变为 `RESOLVED`。
7. 观察期出现新危险：匹配 `R-FALL-06`，同一事件回到 `INTERVENING`，不新建第二条 RiskEvent。
8. 两次干预后又出现新 `trunk_sway/gait_instability`，或内部出现持续危险/无响应：匹配 `R-FALL-07`，进入 `RED/ESCALATED`，通知家属并转人工接管，不自动拨打120。

事件解除时接口评估结果回到GREEN，但数据库中的 RiskEvent 保留其峰值 `risk_level=ORANGE`，用 `status=RESOLVED` 表示已经回落。

## 5. Evidence 类型及决策作用

### 5.1 跌倒域

| Evidence类型 | 时间尺度 | v1.0决策作用 |
|---|---|---|
| `rapid_rise` | SHORT | 单独匹配R-FALL-01，GREEN等待；与trunk_sway组合触发R-FALL-02 |
| `trunk_sway` | SHORT | 与rapid_rise组合；观察期内作为新危险；两次干预后可触发R-FALL-07 |
| `slow_rise` | SHORT/MEDIUM | 不单独创建事件；活动事件观察期内视为危险 |
| `gait_instability` | SHORT | 不作为初始ORANGE组合；观察期内视为危险，可参与升级 |
| `relative_speed_change` | SHORT/MEDIUM | 不作为初始ORANGE组合；观察期内视为危险 |
| `posture_recovered` | SHORT | 15秒门槛；控制INTERVENING→OBSERVING |
| `tracking_lost` | SHORT | 留存质量/追踪信息，不触发风险升级 |
| `normal_baseline_sample`及三类基线样本 | LONG | 基线候选，不触发风险事件 |

决策核心还预留了 `persistent_instability` 和 `no_response`，但当前 FastAPI 冻结 Evidence 枚举尚未接受这两个外部类型。8月7日前HTTP验收使用“两次干预后新trunk_sway”覆盖R-FALL-07，不得提交未冻结字段。

### 5.2 语音、行为、心理和诈骗域

| 类型 | 含义 | ruleset-v1.0输出 |
|---|---|---|
| `fraud_keyword` | 授权转写中的高风险话术特征 | 保存；GREEN/NO_MATCH；不创建诈骗结论 |
| `unauthorized_visitor` | 授权信息未匹配 | 保存；GREEN/NO_MATCH；建议后续版本做身份核验组合 |
| `unusual_dwell_time` | 停留超过尚待标定的工程阈值 | 保存；GREEN/NO_MATCH |
| `activity_range_decline` | 活动范围相对本人基线下降 | 保存；GREEN/NO_MATCH；不得作心理诊断 |
| `day_night_rhythm_change`等MENTAL类型 | 长期行为趋势 | 保存；GREEN/NO_MATCH |
| `audio_quality_low` | 音频质量不足 | SYSTEM质量证据；不得升级 |
| `low_illumination` | 低照度上下文 | 不单独升级；可为跌倒评分增加0.25上下文 |

非跌倒组合规则必须进入后续 `ruleset-v1.1` 评审后才能实施。默认配置表中的旧 `mental_long_days`、`fraud_min_evidence_count` 不是 v1.0 决策来源，后端不得据此私自创建事件。

## 6. 输出、告警记录和建议动作

| 规则 | 接口风险输出 | RiskEvent状态 | 新建RiskEvent | 建议动作 |
|---|---|---|---:|---|
| 正常/NO_MATCH | GREEN | 无 | 否 | 无 |
| R-FALL-01 | GREEN | 无 | 否 | 等待独立危险证据 |
| R-FALL-03 | 保持原风险 | 保持原状态 | 否 | 记录质量问题、等待可用数据 |
| R-FALL-02 | ORANGE | INTERVENING | 是 | 坐稳、扶住固定物、缓慢起身；执行温和语音干预 |
| R-FALL-04 | ORANGE | OBSERVING | 否 | 继续观察，不重复告警 |
| R-FALL-05 | GREEN | RESOLVED | 否 | 关闭处置，保留完整审计链 |
| R-FALL-06 | ORANGE | INTERVENING | 否 | 恢复干预，可进行第二次语音提示 |
| R-FALL-07 | RED | ESCALATED | 否 | 通知家属、人工接管；不自动拨打120 |
| R-SYSTEM-01 | 保持原风险 | 保持原状态 | 否 | 幂等返回，不重复执行工具 |

只有 `R-FALL-02` 在当前冻结规则下新建决策告警记录。恢复、观察失败和升级均更新同一个 RiskEvent。

## 7. Observation/Evidence字段映射

| 算法含义 | Observation | Evidence |
|---|---|---|
| 起身时长 | `feature_name=sit_to_stand_duration`，秒 | `rapid_rise/slow_rise.current_value`，个人基线写入`baseline_value` |
| 躯干摇晃 | `feature_name=trunk_sway_angle`，度 | `trunk_sway.current_value` |
| 相对步速 | `feature_name=relative_gait_speed`，`frame_height_per_second` | `relative_speed_change.current_value` |
| 步态不稳定 | 对称性、连续性等完整Observation | `gait_instability` |
| 恢复持续时间 | `stable_posture_duration`，秒 | `posture_recovered.current_value` |
| 恢复角度 | `stable_trunk_angle_deg`，度 | 仅通过`observation_ids`引用，不写入`current_value` |
| 音频转写 | 转写可用状态、文本或脱敏标签Observation | `fraud_keyword`仅表达话术特征 |
| 访客行为 | 人数、授权匹配、停留时间Observation | `unauthorized_visitor/unusual_dwell_time` |
| 长期活动 | 当前/基线区域数、房间转换等Observation | `activity_range_decline`等MENTAL趋势Evidence |
| 质量与环境 | 遮挡、照度、音频质量Observation | SYSTEM Evidence或Evidence自身`data_quality` |

共同字段约束：

- Evidence 的 `resident_id/source_mode/simulated` 必须与全部引用 Observation 一致；
- 相同实体的时间、位置和单位必须具有同一语义；
- `confidence/severity/data_quality` 范围均为0—1；
- 未知值用 `null`，不得用0或空字符串冒充；
- `RECORDED_REPLAY + FALL` 的每条 Observation 必须指向未过期、已授权的 `EZVIZ_C6C` Asset。

## 8. 错误、幂等和超时约定

统一错误结构：

```json
{
  "error": {
    "code": "OBSERVATION_NOT_FOUND",
    "message": "observations do not exist: [...]",
    "request_id": "req-..."
  }
}
```

| HTTP | 典型错误 | 是否重试 |
|---:|---|---|
| 422 | 缺字段、枚举/类型/分数/时区错误、恢复语义错误 | 否；修正载荷 |
| 409 | 引用不存在、居民/来源冲突、ID异内容冲突、资产授权问题 | 否；先修正前置数据 |
| 404 | Asset/Event不存在 | 否；核对ID或先创建 |
| 500 | 未预期服务错误 | 可有限重试并携带同一请求ID |
| 503 | 设备或外部工具不可用 | 可重试/降级；RiskEvent保持未关闭 |

8月1—7日客户端超时约定（当前由调用方实施，FastAPI未内置请求超时中间件）：

| 调用 | connect | 总响应 | 最大重试 |
|---|---:|---:|---:|
| Asset/Observation/Evidence/Risk evaluate | 2秒 | 5秒 | 3次 |
| 干预工具 | 2秒 | 10秒 | 1次自动重试 |
| Event详情查询 | 2秒 | 5秒 | 3次 |

重试退避为0.5、1、2秒并加少量抖动。只重试连接失败、超时、500、502、503、504；不自动重试422/409。若超时发生在提交后且服务端可能已经成功，必须使用相同ID和完全相同载荷重试：相同内容返回200幂等成功；相同ID不同内容返回409。所有调用应携带稳定的 `X-Request-ID`，并记录响应同名头。

降级要求：

- Observation/Evidence提交失败：写入本地脱敏outbox，保持顺序重放，不跳过缺失Observation直接发Evidence；
- 语音工具失败：保存 `InterventionResult.delivery_status=FAILED`，RiskEvent继续 `INTERVENING`，转家属/人工通道；
- 数据质量不足：保存Evidence和质量RuleTrace，不升级风险；
- 决策复评超时：不得在前端本地重算风险，继续展示最后一次后端确认状态并标明延迟。

## 9. 验收样例

可执行完整载荷：

- 跌倒：`contracts/v1/examples/mock_fall_sequence.json`
- 语音/行为：`deliverables/cym/audio-behavior-demo/samples/behavior_evidence_bundle.example.json`
- 本目录逐场景期望：`samples/decision-acceptance-cases.json`
- 本地三段真实C6c素材的脱敏登记：`samples/real-recorded-sample-register.json`

必须覆盖：

1. 正常样本不创建RiskEvent；
2. rapid_rise单独保持GREEN；
3. 30秒内rapid_rise+trunk_sway创建ORANGE/INTERVENING；
4. 质量0.69不升级，0.70通过；
5. 两条置信度均0.79时不满足高置信组合；
6. 14.9秒保持INTERVENING，15.0秒进入OBSERVING；
7. 观察59.999秒不解除，60.0秒无新危险进入RESOLVED；
8. 观察期新危险回到INTERVENING；
9. 两次干预后新危险进入RED/ESCALATED；
10. 语音关键词、未授权访客和活动下降在v1.0只入库留痕，不自动生成诊断或RiskEvent；
11. 相同Evidence重放幂等，不重复事件或工具调用。

## 10. RuleTrace验收字段

每次决策至少核对：

```text
trace_id
event_id / evidence_id / resident_id
evaluated_at
ruleset_version
matched_rule
previous_state / next_state
previous_status / next_status
event_created
queried_windows
thresholds
baseline_snapshot
quality_snapshot
context_snapshot
score_components
reason / not_matched / error
```

数据库 RuleTrace、JSONL规则日志、事件详情API和页面必须按 `trace_id` 展示同一份内容。浏览器不得二次拼装或重新判断风险。

## 11. 8月7日验收命令

```powershell
python -m pytest tests/test_risk_api.py -q
python -m pytest tests/test_memory_and_ruleset.py -q
python deliverables/zy/pose-demo/scripts/submit_golden_package.py --validate-only --allow-pending
```

真实C6c素材经姿态适配器输出后，再按 `POST /assets → /observations → /evidence` 运行三轮HTTP闭环。当前75.8秒黄金片段没有完成恢复后的60秒观察，因此只可验收到 `OBSERVING`，不得伪造 `RESOLVED`。
