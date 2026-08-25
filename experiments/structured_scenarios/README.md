# 结构化虚拟场景验证

本目录用于初赛前验证心理趋势与诈骗核验的 Evidence 合同、工程规则和事件闭环，不包含真实视频、真实老人数据或真实诈骗案例。

心理场景各包含 12 天的活动范围、房间转换次数、昼间活动占比和数据质量序列；诈骗场景只包含授权状态、停留时长和脱敏对话标签，不保存原始逐字稿或媒体。

## 运行

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts\run_extension_scenario_acceptance.py
```

默认输出到 `artifacts/extension-scenario-acceptance/`：

- `scenario-catalog.json`：心理 12 组、诈骗 12 组场景定义；
- `case-results.json`：逐场景规则、状态、追溯、幂等与时延结果；
- `mental-summary.json`、`fraud-summary.json`：分领域汇总；
- `summary.json`：机器可读总结果；
- `report.md`：评审可读报告。

## 数据口径

所有场景均使用：

```json
{
  "source_mode": "MOCK",
  "simulated": true,
  "scenario_kind": "STRUCTURED_SYNTHETIC",
  "generator_version": "extension-scenarios-v1.0"
}
```

`scenario_kind` 与 `generator_version` 位于场景包和 Observation metadata；Evidence 受冻结合同限制，通过 `source_mode`、`simulated` 和 `adapter_version` 保存同等来源信息。

结果只能表述为场景触发、误升级、Evidence 可追溯完整率、状态闭环、幂等和处理时延。不得表述为临床准确率、真实诈骗识别准确率、真实老人验证、真实访客身份识别或真实连续多日监测。
