# 8月14规则基线

本目录保存步态规则基线和稳定性验收结果。

## 文件说明

- `baseline_profile.json`
  基于 URFD cam0 高质量 ADL 序列生成的演示基线，包含中位数、MAD、分位数和规则参数。

- `rule_stability_report.json`
  8月14 验收报告，确认 7 类跌倒 Evidence、数据质量门控和基线来源。

## 生成命令

```powershell
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/build_gait_baseline_profile.py
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/build_fall_evidence_package.py
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/build_rule_stability_report.py
```

## 当前结论

- 状态：`RULE_BASELINE_STABLE_FOR_DEMO`
- 基线样本：高质量 ADL 序列 12 条
- LSTM：P1 对照任务，当前不阻塞 8月14 冻结验收

实机部署前应使用同一机位、同一光照口径的 ADL 片段重新生成本 profile。
