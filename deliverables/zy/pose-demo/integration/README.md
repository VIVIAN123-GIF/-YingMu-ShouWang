# 8月7-14步态联调交付

本目录提供赵勇步态模块在 8月7-14 需要交给智能体和后端的可调用材料。

## 文件说明

- `golden_30s_fall_evidence.json`
  Observation 完整的黄金半分钟联调包，包含 Asset、Observation、Evidence 与提交顺序。仓库当前公开数据生成物固定标记为 `PENDING_ASSET`，不能冒充真实 C6c 验收。
- `provisional_baseline_manifest.example.json`
  8月1—3日同机位正常动作的脱敏输入模板。只填写匿名居民、设备/机位引用、授权非敏感引用和三项工程指标；`local_path` 即使存在也不会写入生成包。

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

## 静态校验与提交

```powershell
python deliverables/zy/pose-demo/scripts/submit_golden_package.py --validate-only --allow-pending
# 授权 C6c 包生成后，不带 --allow-pending 才能提交：
python deliverables/zy/pose-demo/scripts/submit_golden_package.py
```

提交顺序固定为 `POST /assets → POST /observations → POST /evidence`。每条 Evidence 的引用、居民、来源、模拟标记和资产均会先做本地校验，后端再执行409门禁。
黄金闭环只有在授权/保留期有效、证据质量通过且实际连续稳定时长达到15秒时才会标为 `READY`；不足15秒的真实算法结果会保留，但仍是 `PENDING_ASSET`，不会伪造恢复完成。

## 同机位初步基线包

复制模板到 Git 外的本地目录，填入三日脱敏记录后执行：

```powershell
python deliverables/zy/pose-demo/scripts/build_provisional_baseline_package.py D:\private\baseline-manifest.json --output D:\private\baseline-package.json
python deliverables/zy/pose-demo/scripts/submit_golden_package.py --package D:\private\baseline-package.json
```

三项指标均覆盖3个日期、质量不低于0.70且授权有效时，生成包才为 `READY`；后端最终仍会排除危险、低质量、非GREEN时段、公开数据及混合机位样本。相对步速单位固定为 `frame_height_per_second`，不伪造米/秒。

## 智能体联调口径

- POST endpoints：`/api/v1/assets`、`/api/v1/observations`、`/api/v1/evidence`
- 当前仓库回归包输入来源：`PUBLIC_DATASET`，仅用于算法回归并保持 `PENDING_ASSET`
- 真实黄金包/基线输入来源：`RECORDED_REPLAY`，且必须追溯到授权 C6c 资产
- 是否模拟：`simulated=true`
- 规则基线：默认读取 `baseline/baseline_profile.json`
- 预期行为：`rapid_rise`、`trunk_sway`、`gait_instability`、`relative_speed_change` 进入跌倒短时证据链，风险引擎应进入 `ORANGE / IMMINENT`；`posture_recovered` 进入观察回落证据。

本联调包不直接输出最终风险等级，只提供 Freeze v1.0 Evidence。

## 本地适配器

```powershell
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/run_fall_evidence_adapter.py --sequence-id adl-14-cam0-rgb
```

该命令直接输出 `fall_evidence_batch.json` 内容，供后端或智能体在没有 HTTP 服务包装时做本地联调。
