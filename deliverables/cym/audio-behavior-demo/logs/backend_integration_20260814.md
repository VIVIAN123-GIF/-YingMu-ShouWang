# 2026-08-14 后端本地联调日志（脱敏）

## 环境

- 服务：本地 FastAPI Mock，`http://127.0.0.1:8765`
- 数据库：本地临时 SQLite，未进入交付目录
- 输入来源：授权本地回放或脱敏转写，不包含 Token、设备序列号、永久 URL 或原始媒体

## 结果

| 对象 | 数量 | 接口 | 结果 |
|---|---:|---|---|
| Asset | 1 | `POST /api/v1/assets` | HTTP 201 |
| 行为 Observation | 6 | `POST /api/v1/observations` | 6/6 HTTP 201 |
| 行为 Evidence | 0 | `POST /api/v1/evidence` | 无需提交，单段视频没有长期基线 |
| 音频 Observation | 4 | `POST /api/v1/observations` | 4/4 HTTP 201 |
| 音频 Evidence | 1 | `POST /api/v1/evidence` | 1/1 HTTP 201 |
| 趋势联调包 | 6 + 3 | 本地 dry-run | 全部通过字段和关联校验 |

客户端日志只保存对象 ID、接口、HTTP 状态和幂等状态，不保存后端返回的最终风险等级。后端风险引擎的状态转换仍由后端负责。

## 注意

- 行为 Asset 使用 `RECORDED_REPLAY`、`simulated=true`，不能表述为实时设备流；
- 音频 Bundle 来自脱敏转写文本/回放，不能表述为真人实时对讲；
- 当前实测只证明本地接口字段兼容和入库链路，不证明正式阈值、算法准确率或萤石实时能力。
