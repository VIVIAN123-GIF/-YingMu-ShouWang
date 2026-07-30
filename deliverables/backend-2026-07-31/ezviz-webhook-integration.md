# 萤石原生告警 WebHook 对接说明

## 已实现

- 外部平台端点：`POST /api/v1/webhooks/ezviz`（不属于前端或算法协作 API）。
- 只接受 `header.type = "ys.alarm"` 的 `{header, body}` 回调报文。
- 校验 HTTP 头 `t`、`Signature`：`HMAC-SHA1(EZVIZ_WEBHOOK_SECRET, 原始请求体 + t)`；拒绝过期或错误签名。
- 设备必须已在 `device_info` 中登记并关联居民；以 `body.alarmId` 幂等写入 `risk_alarm`。
- 原始报文落库前删除敏感值：设备密码 `checksum`、图片 URL、令牌和密钥。只保存图片 `id`。
- 成功在两秒内返回官方所需的最小响应：`{"messageId":"..."}`。

告警入库是后续分析的待消费触发源。算法接入仍严格使用冻结的 Observation/Evidence 入口，未假设任何尚未确认的算法服务路径。

## 控制台实机验收步骤

1. 在萤石开放平台“云信令 → 消息推送”启用消息推送，选择 `ys.alarm`。
2. 将公开 HTTPS 地址登记为 `https://<域名>/api/v1/webhooks/ezviz`；本地地址不能接收云端回调。
3. 在平台和部署环境的本地 `.env` 设置同一签名密钥 `EZVIZ_WEBHOOK_SECRET`，并登记 `EZVIZ_RESIDENT_ID`、`EZVIZ_DEVICE_SERIAL`。
4. 等待平台配置生效后触发一次移动侦测，确认 HTTP 200、`messageId` 回显、`risk_alarm` 新增且敏感值未落库。

该步骤完成前，回调功能只能标记为契约实现与单元测试通过，不能标记为真实设备验收完成。
