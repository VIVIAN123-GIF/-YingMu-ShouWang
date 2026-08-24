# 萤石告警异步处理

## 目的

`POST /api/v1/webhooks/ezviz` 必须快速应答萤石平台，不能在请求内执行取流、FFmpeg 或
算法推理。每条已验证、已去重的 `RiskAlarm` 都会创建唯一的 `AlarmProcessingTask`。

```text
萤石 Webhook
  -> RiskAlarm
  -> AlarmProcessingTask(PENDING)
  -> alarm_worker 申请临时直播地址
  -> FFmpeg 录制到授权私有目录
  -> Asset(CAPTURED)
  -> GAIT / TRAJECTORY AdapterBatch
  -> Observation / Evidence
  -> RiskEvent / Agent Job（仅在 Evidence 满足规则时）
```

真实告警当前使用 `VIDEO` 模式。2026-08-22 的现场互操作配置为 HLS 和 4 秒采集窗口；
该配置完成了真实 MP4 采集和 TRAJECTORY Observation 入库，但 GAIT 仍因
`no_pose_detected` 未通过业务验收。最新边界见
[2026-08-22 真实设备后端算法联调结论](./2026-08-22-真实设备后端算法联调结论.md)。

## 运行

开发期间，临时隧道只指向 FastAPI 的 `8000` 端口；两个 Worker 不需要公网端口。
从仓库根目录分别启动三个进程：

```powershell
Set-Location 'D:\OneDrive\Desktop\荧目守望'

.\.venv\Scripts\python.exe -m dotenv -f .env run --override -- `
  .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

.\.venv\Scripts\python.exe -m dotenv -f .env run --override -- `
  .\.venv\Scripts\python.exe -m backend.worker.alarm_worker --poll-seconds 1

.\.venv\Scripts\python.exe -m dotenv -f .env run --override -- `
  .\.venv\Scripts\python.exe -m backend.worker.agent_worker --poll-seconds 1
```

启动前必须确认：

- `.env` 中 `PYTHONPATH` 包含仓库根目录和行为适配器 `src`；
- `YINGMU_FFMPEG_BINARY` 在启动进程的环境中可执行；
- 私有媒体目录位于仓库和 OneDrive 外，授权与保留期限有效；
- Live 环境 `EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST=false`；
- 临时通道当前公网 `/health` 返回 `status=ok`。

安装 FFmpeg 后应重新打开终端或使用绝对路径。只在新终端执行 `ffmpeg -version` 成功，
不能证明已经运行的 Worker 也获得了更新后的 `PATH`。

## 任务状态

- `PENDING`：真实告警已入队。
- `PROCESSING`：Worker 正在申请播放地址或采集媒体。
- `RETRY`：当前阶段发生可重试错误；通过 `error_stage` 区分 `CAPTURE` 或 `ALGORITHM`。
- `CAPTURED`：私有 Asset 已创建，等待算法领取。
- `ALGORITHM_PROCESSING`：算法适配器正在处理。
- `COMPLETED`：算法产生有效 Evidence，任务完成。
- `NO_EVIDENCE`：算法正常运行但本段没有风险 Evidence。
- `FAILED`：重试耗尽或出现不可重试错误。

`NO_EVIDENCE` 不自动等于“所有模块成功”。仍需检查 `error_code` 和 `algorithm_summary`；
例如 `PARTIAL_ALGORITHM_FAILURE` 表示至少一个模块失败、另一个模块产生了有效批次。

## 验收与诊断

触发一次真实设备告警后查询：

```text
GET /api/v1/alarms/processing
```

验收至少核对：

1. Webhook HTTP 状态和任务创建时间；
2. `capture_asset_id`、私有对象存在性和 `LIVE_DEVICE/simulated=false`；
3. 采集与算法各自的尝试次数；
4. 每个算法模块的状态、错误码、Observation/Evidence 数量；
5. 本任务关联的 RiskEvent 和 Agent Job 增量，而不是只查看总表数量。

流媒体使用仓库脱敏入口验证：

```powershell
.\.venv\Scripts\python.exe -m dotenv -f .env run --override -- `
  .\.venv\Scripts\python.exe scripts\validate_ezviz_live.py `
  --runs 1 --interval-seconds 0 --stream-probe --output-dir <仓库外诊断目录>
```

报告不得保存播放 URL、Token、设备序列号或私有视频。需要分析 FFmpeg 时，只输出预定义
错误分类和媒体技术指标，不直接粘贴原始命令行或 stderr。

同一平台告警 ID 重推只能保留一条 `RiskAlarm` 和一条处理任务。已失败任务只有在私有媒体
存在、失败阶段明确且原因已修复时才能做单条条件重排；禁止批量改库伪造成功状态。
