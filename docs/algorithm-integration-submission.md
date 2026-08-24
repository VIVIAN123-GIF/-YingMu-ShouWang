# 算法与后端联调说明

## 当前调用方式

步态、语音和行为算法不需要提供独立 HTTP 服务。当前保留两种调用路径：

### Live 告警主路径

真实设备告警由后端 Worker 构造冻结的 `AlgorithmJob`，通过仓库配置的入口函数直接调用
算法，并校验返回的 `AdapterBatch`：

```text
私有 Asset
  -> AlgorithmJob
  -> run(AlgorithmJob)
  -> AdapterBatch
  -> 后端统一持久化 Observation / Evidence
  -> 规则评估与事件记录
```

入口签名固定为：

```python
async def run(job: AlgorithmJob) -> AdapterBatch:
    ...
```

适配器入口由 `YINGMU_GAIT_ADAPTER`、`YINGMU_TRAJECTORY_ADAPTER` 和
`YINGMU_LANGUAGE_ADAPTER` 配置；Worker 的 `PYTHONPATH` 必须能够导入仓库合同和算法包。

### 离线产物兼容路径

对外部算法进程、历史样本和独立幂等验收，算法生成结果后可以依次调用后端统一入口：

```text
算法输入（视频帧 / 音频 / 视频片段）
  -> 生成 Observation
  -> POST /api/v1/observations
  -> 适配生成 Evidence
  -> POST /api/v1/evidence
  -> 后端校验、入库、决策与事件记录
```

两种路径下，算法都不得直接写数据库、提交最终 `risk_level`，或调用干预接口。

## 离线产物可使用的后端入口

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/v1/observations` | 保存算法直接观测到的特征 |
| `POST` | `/api/v1/evidence` | 保存风险证据并触发统一评估 |

Evidence 引用的每个 `observation_id` 必须已经成功提交；关联数据的 `resident_id`、`source_mode`、`simulated` 必须一致。

字段和枚举以以下冻结 Schema 为准，不得自行增加字段：

- [Observation Schema](../contracts/v1/schemas/observation.schema.json)
- [Evidence Schema](../contracts/v1/schemas/evidence.schema.json)

## 提交命令

后端启动后，可用仓库脚本提交一对 JSON：

```powershell
python scripts/submit_algorithm_result.py `
  --observation <observation.json> `
  --evidence <evidence.json> `
  --backend-url http://127.0.0.1:8000
```

如果一条 Evidence 关联多条 Observation，按顺序重复传入多个 `--observation` 参数；这些 Observation 会全部写入成功后才提交 Evidence。

对于赵勇提供的批量场景文件，可直接指定文件和场景名：

```powershell
python scripts/submit_algorithm_result.py `
  --scenario-file deliverables/algorithm-integration/pose/incoming/gait_module_output_samples_2026-08-03.json `
  --scenario abnormal_gait_trunk_sway
```

提交前可校验整份批量样例：

```powershell
python scripts/validate_algorithm_samples.py `
  --samples deliverables/algorithm-integration/pose/incoming/gait_module_output_samples_2026-08-03.json
```

常易铭 2026-08-03 语音/行为包保留为原始压缩包和原样解包副本，采用其自身的六个
有序请求，而非伪造为步态批量文件。运行隔离验收：

```powershell
python scripts/validate_voice_behavior_package.py
```

成功状态：首次写入为 `201`；相同 ID、相同内容的重试为 `200`。字段错误为 `422`，Observation 不存在或关联数据不一致为 `409`。

## 当前实机状态与待补充内容

2026-08-22 的真实告警已完成私有 HLS 视频采集和 Worker 算法调用：TRAJECTORY 生成 14 条
Observation 并返回 `NO_EVIDENCE`；GAIT 返回 `FEATURE_INPUT_INVALID`，脱敏原因是
`no_pose_detected`。该任务没有新增 Evidence、RiskEvent 或 Agent Job。

各模块需要在下一轮联调前提供正常和受控风险两类授权样本、预期 AdapterBatch，以及最低
时长、FPS、有效姿态帧数和拍摄条件。当前不填写任何未由算法或智能体负责人确认的特征、
Evidence 或决策规则。

一次性联调准备见
[2026-08-24 后端与算法一次性联调说明](./2026-08-24-后端与算法一次性联调说明.md)，
当天实机证据见
[2026-08-22 真实设备后端算法联调结论](./2026-08-22-真实设备后端算法联调结论.md)。

## 步态联调验收归档

步态适配器和后端整链验收统一使用以下命令生成证据，禁止手工拼接请求与响应 JSON：

```powershell
.\.venv\Scripts\python.exe scripts\run_gait_integration_acceptance.py `
  --media D:\private\authorized-c6c-replay.mp4 `
  --captured-at 2026-08-20T09:30:00+08:00 `
  --resident-id resident-redacted-001 `
  --camera-position-id living-room-fixed-001 `
  --scene-config-id scene-config-v1 `
  --backend-url http://127.0.0.1:8000 `
  --authorization-record-id auth-redacted-001 `
  --retention-until 2026-09-30T23:59:59+08:00
```

脚本不归档私有媒体路径或视频副本，只保存 SHA-256、字节数和格式。判定等级如下：

- `CONTRACT_PASS`：预计算 JSON/CSV 通过合同，不能称为真实视频联调。
- `ADAPTER_PASS`：真实视频通过 MediaPipe 和适配器合同，但未验证后端。
- `BACKEND_E2E_PASS`：在 `ADAPTER_PASS` 基础上，Asset、Observation、Evidence 首次写入均为 `201`，相同内容重试均为 `200`，且事件详情包含提交证据和 RuleTrace。该等级不包含前端视觉验收。
- `FAIL`：任一必需门禁失败。没有后端回执时绝不输出系统级通过。

该归档脚本验证的是授权回放和 HTTP 持久化闭环，不能替代 Live 告警 Worker 的私有媒体、
适配器直调和任务状态验收。完整验收必须分别保留两条路径的证据。

验收目录中的 `algorithm_job.redacted.json` 与 `adapter_batch.json` 保留相同任务、居民和资产 ID，可直接用 `validate_batch_for_job` 复核。历史材料若无法完成该配对，不得通过修改归档文件补写为成功。
