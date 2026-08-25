# 心理趋势与诈骗核验结构化虚拟场景验证报告

> This is structured synthetic engineering validation. It is not clinical accuracy, real fraud-case accuracy, real elderly validation, visitor identity recognition, or real continuous multi-day monitoring.

- 生成器版本：`extension-scenarios-v1.0`
- 来源：`MOCK`，全部 `simulated=true`
- 总体结果：**PASS**（24/24 场景通过）

| 领域 | 场景通过 | Evidence 匹配 | 场景触发率 | 误触发/误升级 | Evidence 可追溯 | 闭环 | 幂等 | 时延 P50/P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MENTAL | 12/12 | 16/16 | 9/9 (100.0%) | 0/0 | 16/16 (100.0%) | 3/3 | 12/12 | 28.716/181.07 |
| FRAUD | 12/12 | 19/19 | 10/10 (100.0%) | 0/0 | 19/19 (100.0%) | 2/2 | 12/12 | 28.593/41.3 |

## 口径说明

本报告只验证结构化输入下的 Evidence 契约、工程规则触发、事件状态闭环、可追溯性、幂等和处理时延。
不报告心理疾病识别准确率、真实诈骗识别准确率，也不代表真实老人、真实访客或真实连续多日监测验证。
真实视频与现场验证安排在初赛后执行。
