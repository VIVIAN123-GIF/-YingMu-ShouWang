# 第四阶段部署与验收清单

## 责任边界

- 算法同学负责可由 Worker 导入的 `run(AlgorithmJob) -> AdapterBatch` 入口、特征提取和 Observation/Evidence；算法不把最终风险状态写死在模型里。
- 后端负责接收结果、校验、幂等、规则评估，以及算法调用边界的超时、有限重试、熔断和降级。
- 设备负责人/队长负责萤石设备授权、真实设备事件、Webhook 公网 HTTPS 地址和轮换后的密钥。临时播放地址由后端在使用时申请，不能人工长期录入。

真实告警使用 Worker 直接调用算法适配器；`POST /api/v1/observations` 和
`POST /api/v1/evidence` 保留给离线样本、外部算法产物和独立幂等验收，不是 Live 告警的
主要执行路径。

## 算法故障策略

`backend.service.algorithm_gateway.AlgorithmGateway` 是统一入口：

1. 单模块调用有独立超时，默认 8 秒；
2. 仅对超时、连接错误等临时故障做有限重试，并采用递增退避；
3. 连续失败达到阈值后熔断，避免故障模块拖垮整体服务；
4. `run_many` 的隔离语义保证其他算法继续完成；
5. 失败返回带 `degraded=True` 的可审计结果；调用方记录模块错误和部分失败，不得自动伪造 `SYSTEM` Evidence 或正常算法结论。

结果提交脚本 `scripts/submit_algorithm_result.py` 也对幂等的 Observation/Evidence POST 做 408、429、5xx 和网络错误重试；业务 4xx 不重试。

临时联调若平台未提供可配置的 Webhook 签名密钥，可在测试环境显式设置
`EZVIZ_WEBHOOK_ALLOW_UNSIGNED_TEST=true`。该开关只用于短时联调，验收结束必须删除或设为
`false`；正式环境不得依赖无签名回调。

## 上线前配置与验收

确认部署环境具备 `EZVIZ_APP_KEY`、`EZVIZ_APP_SECRET`、`EZVIZ_ACCESS_TOKEN`、`EZVIZ_DEVICE_SERIAL`、`EZVIZ_CHANNEL_NO`；Webhook 真实验收还需要 `EZVIZ_WEBHOOK_SECRET` 和公网 HTTPS 回调地址。凭证只放在部署环境 `.env`，不提交仓库。

Worker 还必须具备：可解析的 `YINGMU_FFMPEG_BINARY`、仓库外私有媒体目录、有效授权与保留期限，以及同时包含仓库合同和行为适配器的 `PYTHONPATH`。

使用 `python scripts/validate_ezviz_live.py --stream-probe` 依次验证设备状态、临时播放地址、FFmpeg 录制和 ffprobe；播放地址必须在调用时生成并立即使用。使用 `python scripts/validate_voice_behavior_package.py` 验证算法样例的 schema、首次写入和幂等写入。

2026-08-22 当前现场基线为 HLS、4 秒视频窗口和 `VIDEO` 媒体模式。FLV 在当前环境中无媒体数据并超时；该结论只代表现场互操作结果。GAIT 最低输入门槛确认后，协议和窗口仍需重新验收。

第四阶段的最终证据应包含：真实视频/音频输入、正常无证据场景、至少一个算法降级场景、受控风险 Evidence、RiskEvent、Agent Job、幂等回执、请求 ID/脱敏日志、核心接口延迟，以及连续运行期间无未处理异常。未连接真实设备时，只能标记为模拟验收，不能宣称实机链路完成。

截至 2026-08-22，实机链路已到达私有视频、算法调用和 Observation 入库；GAIT 因
`no_pose_detected` 失败，未新增 Evidence、RiskEvent 或 Agent Job。因此当前状态是“真实设备
到算法已联通，算法风险闭环未完成”，不得写成完整端到端验收通过。
