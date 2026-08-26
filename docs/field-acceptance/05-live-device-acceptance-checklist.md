# LIVE_DEVICE 实机验收与退出回收检查表

## 配置与预检

- [ ] 私有配置、数据库、媒体、缓冲和运行目录均位于仓库及 OneDrive 外。
- [ ] Webhook 正式验签开启，`EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST=false`。
- [ ] 最终场景已安装，场景 ID、机位 ID 和 `living_room` 完全匹配。
- [ ] 三次 `--stream-probe` 均成功且 `codec_name=h264`，之后才设置 `EZVIZ_LIVE_PLAYBACK_VERIFIED=true`。
- [ ] `check_stream_buffer.py --assembly-probe` 为 `SUCCESS`、`codec_name=h264`、`ready=true`、前置覆盖不少于 10 秒。

## 告警与算法

- [ ] 使用真实 `ys.alarm`，没有使用 `ys.test.msg` 冒充处理任务。
- [ ] 参与者不实施真实跌倒，告警后保持完整入镜至少 20 秒。
- [ ] 最新任务状态为 `COMPLETED`，采集模式为 `RING_BUFFER`。
- [ ] Asset 为 `LIVE_DEVICE/simulated=false`、`VERIFIED_LIVE_BUFFER_CAPTURE`。
- [ ] GAIT 状态：________________  TRAJECTORY 状态：________________
- [ ] 两个模块均实际执行，无 `FAILED` 或 `LOW_QUALITY`。
- [ ] Observation、Evidence（如有）和 ForewarningSnapshot 均继承 `LIVE_DEVICE/simulated=false`。
- [ ] 裁决为保守 `YELLOW/REVIEW`，没有新增 RiskEvent、Agent Job 或自动干预。

## 退出回收

- [ ] 在统一启动器终端按 `Ctrl+C`，没有直接关闭窗口或结束单个子进程。
- [ ] 8000 端口监听数为 0；API、Alarm、Agent、Stream Buffer 进程数均为 0。
- [ ] `worker.lock`、`status.json`、临时 `.ts` 和拼接工作区均已删除。
- [ ] 正式 Asset 和数据库仍存在，并继续遵守授权保留期限。
- [ ] 日志和报告不包含凭证、播放 URL、完整设备序列号或私有绝对路径。

任务脱敏引用：________________  Asset 脱敏引用：________________

执行人：________________  复核人：________________  日期时间：________________

最终结论：`PASS / FAIL / DEGRADED_RETRY`（圈选）

失败或降级错误码：____________________________________________________________
