# 智能体最终验收后端材料

## 可查询环境

- 后端 API：`http://127.0.0.1:8000`
- `event_id`：`event-3ba71dcd92774794`
- 来源：`RECORDED_REPLAY`，`simulated=true`
- 当前事件：`ORANGE / 0.76 / INTERVENING`
- 查询：`GET /api/v1/events/event-3ba71dcd92774794/explanation`

完整脱敏响应、幂等结果、事件前后对比、Worker 日志和请求字段审计见
`acceptance-summary.json`。

## 能力复核修正

队长给出的 6 条结论中，第 1、2、4、5、6 条与当前实现及可查记录一致。
第 3 条不能按“真实持久化证据完整”复核：Worker 私有下载、图片校验、SHA-256
和 Asset 创建已实现且自动化测试通过，但当前共享数据库没有可追溯的
`LIVE_DEVICE` Asset，历史任务中的 3 个 `capture_asset_id` 也无法关联 Asset 行。
建议能力状态改为：

```text
Worker 真实抓拍 Asset 私有入库：实现及自动化验证通过，待补可追溯实机持久化记录
```

因此不应回复“全部结论一致”的固定句子。

## 约束修正

模型请求不包含图片、视频、音频、完整设备序列号、Token、临时 URL、媒体路径或
`storage_key`。但“请求只包含 RiskEvent、Evidence 摘要、基线状态和干预状态”按
字面并不准确：当前合同还包含幂等标识、匿名内部标识、`time_horizon` 和能力矩阵。
这些字段不包含原始媒体或平台凭证。

SUCCESS 使用已配置的 `qwen3.6-flash`，单次 Worker 调用返回 HTTP 200；FALLBACK
使用独立测试数据库和独立一次性 Worker，以进程级错误模型名得到 HTTP 404 后进入
`template-fallback-v1`。共享 `.env` 未修改。全量回归结果为 `175 passed`。
