# 后端 P0 联调说明

## 运行进程

后端主服务、告警 Worker 和解释 Worker 是三个独立进程：

```powershell
py -3.14 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
py -3.14 -m backend.worker.alarm_worker
py -3.14 -m backend.worker.agent_worker
```

告警 Worker 负责抓拍、私有 Asset、算法适配器和风险状态推进。解释 Worker 只消费已经形成的 `RiskEvent + Evidence`，不读取原始图片、视频、音频或萤石凭证。

## 算法适配器

首次在本机或服务器初始化算法运行环境时，使用 Python 3.9-3.12 执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_algorithm_runtime.ps1 -PythonExe python
```

脚本会创建仓库 `.venv`、安装后端与视频算法依赖、下载官方
`pose_landmarker_heavy.task`、校验 SHA-256，并实际初始化 PoseLandmarker。
模型是部署资产且被 Git 忽略，终端用户不需要下载；服务器构建或初始化时只需执行一次。

算法入口使用 `package.module:callable` 配置：

```ini
YINGMU_RULESET_VERSION=ruleset-v1.4
YINGMU_FOREWARNING_RULESET_VERSION=ruleset-v1.4
YINGMU_GAIT_ADAPTER=contracts.v1.gait_adapter_v14:run
YINGMU_GAIT_POSE_MODEL=models/pose_landmarker_heavy.task
YINGMU_TRAJECTORY_ADAPTER=adapters.trajectory_adapter:run
YINGMU_LANGUAGE_ADAPTER=adapters.language_adapter:run
YINGMU_SCENE_CONFIG_ID=scene-living-room-v1
YINGMU_LOCATION=living_room
```

入口接收 `AlgorithmJob` 并返回 `AdapterBatch`。步态入口直接支持本地 MP4/AVI/MOV/MKV/WebM，运行时在内存中提取冻结步态特征，同时继续兼容预计算 JSON/CSV；视频模式需安装 `deliverables/zy/pose-demo/requirements.txt` 并准备由 `YINGMU_GAIT_POSE_MODEL` 指定的 MediaPipe 模型。入口可为同步或异步函数，后端不会导入算法 Demo 目录。未注册时任务明确结束为 `FAILED / ADAPTER_NOT_REGISTERED`。

告警任务状态：

```text
PENDING -> PROCESSING -> CAPTURED -> ALGORITHM_PROCESSING
        -> COMPLETED | NO_EVIDENCE | RETRY | FAILED
```

历史 `WAITING_ALGORITHM` 可继续领取，但不会再产生该状态。`GET /api/v1/alarms/processing` 只返回脱敏模块摘要，不返回设备序列号、媒体路径、临时 URL 或转写原文。

## 风险与恢复

- `no_response`、`persistent_instability`、`quality_gate_failed` 只允许后端生成；公开 `POST /api/v1/evidence` 提交这些类型返回 `422 INTERNAL_EVIDENCE_FORBIDDEN`。
- 成功干预后 60 秒无 `STABLE/HELP` 回应生成幂等 `no_response`。
- 30 秒内三条质量合格、来源一致的不稳定证据生成幂等 `persistent_instability`。
- `STABLE` 只记录回应，不直接解除事件。
- `posture_recovered` 达到 15 秒后进入 `OBSERVING`，再经过 60 秒无新危险才由状态机进入 `RESOLVED`。
- 高风险区域和障碍交互只在同一 30 秒窗口存在可用 FALL Evidence 时参与上下文分，SYSTEM Evidence 不单独创建 ORANGE/RED。

## 智能体解释

事件创建、升级为 RED、干预结果新增或恢复结果变化时，会写入幂等解释任务。模型调用由独立 Worker 执行：

```http
GET  /api/v1/events/{event_id}/explanation
POST /api/v1/events/{event_id}/explanation
```

`POST` 是补偿入口，要求 `X-Control-Token`。首次入队返回 201，同一事件版本重复提交返回 200。Provider 正常时任务为 `SUCCESS`；Provider 失败且模板有效时为 `FALLBACK`。

大模型只解释结构化 `RiskEvent` 和 `Evidence`，不参与风险等级判定，不直接识别原始媒体。模型输出不能修改 `risk_level`、`risk_score`、`resolved` 或规则 ID。

## 验收

```powershell
py -3.14 scripts/export_contract_schemas.py
py -3.14 -m pytest -q
py -3.14 scripts/validate_agent_llm_live.py
git diff --check
git diff --name-only
```

真实 API Key 只放本地 `.env`，不得提交仓库。实时模型校验产生的报告也不得包含 Token、媒体路径、临时 URL、设备序列号或原始敏感转写。
