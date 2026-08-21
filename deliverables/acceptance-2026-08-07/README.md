# 8月7日前软件验收阶段报告

生成日期：2026-08-06（Asia/Shanghai）
规则集：`ruleset-v1.0`
素材范围：现有授权 C6c 回放、公开数据回归、Mock/合成契约样例。
隐私边界：本报告不包含视频、模型、授权原件或本地绝对路径。

## 阶段结论

软件链路和 Mock 闭环可以交付；现有三段 C6c 视频完成了真实逐帧适配和局部 HTTP 验收。黄金素材不满足完整 ORANGE/RESOLVED 证据门槛，个人同机位基线仍为“样本不足”。不通过改阈值、补写时长或虚拟时间推进来改变结论。

## 已验收项目

| 项目 | 结果 | 证据 |
|---|---|---|
| Python/MediaPipe 环境 | PASS | Python 3.11.9、MediaPipe 0.10.21；模型 SHA-256 为 `64437af838a65d18e5ba7a0d39b465540069bc8aae8308de3e318aad31fcbc7b` |
| 后端/契约测试 | PASS | `88 passed` |
| 公开 Evidence Schema 回归 | PASS | 7 项 Evidence schema 校验通过 |
| Mock HTTP 闭环 | PASS | 3 轮；GREEN→ORANGE/INTERVENING→OBSERVING→RESOLVED；重复提交幂等 |
| 前端单测/构建 | PASS | 36 项通过，Vite production build 通过 |
| 前端 API 浏览器闭环 | PASS | 3 轮，页面状态和后端事件 ID 一致 |
| 真实 C6c HTTP 提交 | PASS（局部） | 3 个 Asset、8 个 Observation、6 个 Evidence 均按顺序入库；重复 Evidence 返回 200；DB/JSONL RuleTrace 精确一致 |
| 音频/行为趋势模块 | PASS（合成） | 29 项趋势分析测试通过；输入为 Mock/合成日活动和 Evidence bundle |

## 现有视频的真实结果

| take | 算法结果 | 阶段结论 |
|---|---|---|
| golden | rapid 0.4s/质量0.788；sway 22.077°/质量0.754；稳定49.466s、角度7.878°/质量0.746 | `PENDING_ASSET / CONFIDENCE_BLOCKED`；最高置信度未达到0.80，稳定后不足60s，不能声明 ORANGE 或 RESOLVED |
| rapid-only | 仅发出 `rapid_rise`，质量0.759 | `GREEN`，无告警事件 |
| under15 | 稳定7.534s、角度7.436°/质量0.781 | 不满足15秒恢复阈值；在活动事件场景中应保持 `INTERVENING` |

## RuleTrace 与风险分说明

后端风险服务、智能体核心、数据库记录、JSONL 日志和事件详情 API 均读取同一份 `ruleset-v1.0`。前端只展示 API 返回的 RuleTrace，不在浏览器重新判断。历史材料中出现的 `0.82` 是某组严重度、质量和上下文输入经公式计算后的结果，不是硬编码；动态向量见同目录 `dynamic-risk-score-samples.json`。

## 待补事项

1. 8月8日后补拍黄金片段：至少一条置信度达到0.80，并在达到15秒稳定后继续无危险观察60秒。
2. 同一 C6c、同一机位、至少3个不同日期录制正常起身，才可将个人基线从 `INSUFFICIENT` 变为 `PROVISIONAL`。
3. 音频/行为模块已完成契约、规则、合成趋势样例和 29 项测试；真实授权音频素材到位后再做现场 HTTP 验收。

## 禁止事项

- 不把公开数据、Mock、危险样本写入个人基线。
- 不把 `RECORDED_REPLAY` 或 `simulated=true` 包装成实时设备监测。
- 不把现有黄金片段标记为完整闭环或 `RESOLVED`。
