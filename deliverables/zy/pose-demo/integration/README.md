# 8月7-14步态联调交付

本目录提供赵勇步态模块在 8月7-14 需要交给智能体和后端的可调用材料。

## 文件说明

- `golden_30s_fall_evidence.json`
  第100天黄金半分钟联调包，包含 30 秒内按时间顺序提交给 `/api/v1/evidence` 的跌倒 Evidence。

## 生成命令

```powershell
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/build_gait_baseline_profile.py
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/build_fall_evidence_package.py
```

## 验证命令

```powershell
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/validate_evidence_schema.py --require-all-fall-types
```

通过标志：

```text
Evidence schema OK: 7 item(s)
```

## 智能体联调口径

- POST endpoint：`/api/v1/evidence`
- 输入来源：`PUBLIC_DATASET`
- 是否模拟：`simulated=true`
- 规则基线：默认读取 `baseline/baseline_profile.json`
- 预期行为：`rapid_rise`、`trunk_sway`、`gait_instability`、`relative_speed_change` 进入跌倒短时证据链，风险引擎应进入 `ORANGE / IMMINENT`；`posture_recovered` 进入观察回落证据。

本联调包不直接输出最终风险等级，只提供 Freeze v1.0 Evidence。

## 本地适配器

```powershell
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/run_fall_evidence_adapter.py --sequence-id adl-14-cam0-rgb
```

该命令直接输出 `fall_evidence_batch.json` 内容，供后端或智能体在没有 HTTP 服务包装时做本地联调。
