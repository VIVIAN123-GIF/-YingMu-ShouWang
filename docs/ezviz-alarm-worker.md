# 萤石告警异步处理

## 目的

`POST /api/v1/webhooks/ezviz` 必须快速应答萤石平台，不能在请求内执行抓图或算法。每条已验证、已去重的 `RiskAlarm` 都会创建唯一的 `AlarmProcessingTask`。

```text
萤石 WebHook → RiskAlarm → AlarmProcessingTask(PENDING)
                              ↓
                         alarm_worker
                              ↓
             平台抓图 → WAITING_ALGORITHM
```

当前算法适配器尚未接入，因此 Worker 不创建 `Observation`、`Evidence` 或 `RiskEvent`。`WAITING_ALGORITHM` 是明确的真实状态，不代表跌倒检测已完成。

## 运行

开发期间，临时隧道继续指向 FastAPI 的 `8000` 端口；Worker 不需要公网端口：

```powershell
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
python -m backend.worker.alarm_worker
```

腾讯云演示环境也必须分别运行 Web 服务和 Worker。只有 Web 服务地址需要配置为萤石 WebHook 回调地址。

## 状态与验收

- `PENDING`：告警已入队。
- `PROCESSING`：Worker 已领取任务。
- `WAITING_ALGORITHM`：抓图成功，等待未来算法适配器消费。
- `RETRY`：抓图临时失败，最多重试 3 次。
- `FAILED`：重试耗尽；保留失败类型，但不保存 URL、Token 或原始报文。

验证时触发一次真实设备告警，再查询 `GET /api/v1/alarms/processing`。接口只返回脱敏的设备/告警引用，不返回设备序列号、回调原文、抓图 URL 或凭据；同一 `alarmId` 重推只能保留一条告警和一条处理任务。
