# 冻结接口兼容与验收矩阵

## 契约依据

1. `冻结方案/02-统一接口规范.md`；
2. `origin/feature/cs/frontend` 中 `frontend/src/services/repository.js`、Mock JSON 与四对象校验；
3. `origin/feature/zy/pose-demo` 中冻结 Evidence 样例。

未在上述来源出现的算法专用 HTTP 路径、萤石 WebHook 路径和请求字段均未自行新增。

## 已实现路径

| 方法 | 路径 | 对接方 | 状态 |
|---|---|---|---|
| POST | `/api/v1/observations` | 算法 | 已实现，幂等写入 |
| POST | `/api/v1/evidence` | 算法/智能体 | 已实现，冻结 Evidence 名称校验 |
| GET | `/api/v1/residents/{resident_id}/baseline` | 前端/智能体 | 已实现 |
| POST | `/api/v1/risk/evaluate` | 智能体 | 已实现 P0 跌倒 Mock 规则 |
| GET | `/api/v1/events` | 前端 | 已按 `resident_id` 查询 |
| GET | `/api/v1/events/{event_id}` | 前端 | 顶层 RiskEvent，并附 `evidences/observations/interventions` |
| POST | `/api/v1/events/{event_id}/intervene` | 智能体/后端 | 已实现可审计 Mock/实机能力门控 |
| POST | `/api/v1/events/{event_id}/results` | 后端/工具 | 已按 InterventionResult v1.0 写入 |
| POST | `/api/v1/events/{event_id}/feedback` | 前端 | 已匹配前端 `feedback_id/feedback_type/value/operator` 并幂等写入 |
| GET | `/api/v1/reports/weekly` | 前端 | 已实现 |
| GET | `/api/v1/device/status` | 前端 | 已实现 DeviceAdapter 来源标识 |
| GET | `/api/v1/device/snapshot` | 前端 | 已实现 Mock/实机能力门控 |
| POST | `/api/v1/assets` | 现场网关/后端 | 已按前端资产对象实现幂等登记 |
| GET | `/api/v1/assets/{asset_id}` | 前端 | 已实现 |
| POST | `/api/v1/device/stop` | 授权现场服务 | 已实现 `X-Control-Token` 鉴权 |

## 算法对接规则

算法不新增“步态分数接口”或“语音风险等级接口”，统一执行：

1. `POST /api/v1/observations` 写入直接观测；
2. 适配器生成冻结 Evidence；
3. `POST /api/v1/evidence` 写入并触发统一风险评估。

跌倒类型严格为 `rapid_rise`、`slow_rise`、`trunk_sway`、`gait_instability`、`relative_speed_change`、`posture_recovered`、`tracking_lost`。行为、语音、人工确认和系统 Evidence 同样按冻结文档校验；未知名称返回 422，不由后端猜测映射。

## 仍需外部条件的验收

以下内容不能由代码或 Mock 伪造为完成：

- C6c 到货、绑定、在线状态、真实截图和临时播放地址；
- 语音/消息能力的真实可用性与送达率；
- 萤石告警订阅方式、WebHook 路径、签名和真实回调报文；
- 前端分支合入后的 `VITE_DATA_MODE=api` 页面联调；
- 算法分支提交真实 Observation 后的端到端联调；
- 连续运行、P95 延迟、误报率和闭环三次复现。

在收到真实设备、脱敏报文和共同确认的告警回调契约前，后端不公开猜测的 WebHook 接口。
