# 私有抓拍媒体闭环交接

更新时间：2026-08-28

本文记录本轮“主动抓拍图片可在系统内安全查看”的后端工作。所有内容为脱敏说明；不得把真实令牌、设备序列号、私有媒体目录、萤石临时 URL、图片文件或公网入口写入本文件、Git 或聊天记录。

## 1. 当前任务

为真实萤石主动抓拍补齐私有媒体闭环：后端抓拍后下载图片到仓库外的私有目录，生成可审计的 `Asset`，再由受控 API 返回图片字节，供后续前端以受权方式展示。

范围限制：本轮只修改后端、后端配置示例和后端测试；没有修改前端页面、前端请求逻辑、数据库结构、告警 Worker 或真实萤石配置。

## 2. 已完成内容

1. 新增 `POST /api/v1/device/snapshot`。
   - 原有 `GET /api/v1/device/snapshot` 保持不变，只返回脱敏抓拍审计信息。
   - 新 POST 会调用真实抓拍、下载图片、校验类型/文件签名/大小、写入 `YINGMU_PRIVATE_MEDIA_ROOT`，并创建 `Asset`。
   - 返回 `201` 和脱敏的 `asset` 元数据；不返回萤石临时 URL、设备序列号、私有存储键或真实文件路径。

2. 新增 `GET /api/v1/assets/{asset_id}/content`。
   - 只支持 `image/jpeg`、`image/png`、`image/webp`。
   - 读取前检查 Asset 的 `available`、`authorization_status=AUTHORIZED`、授权记录、保留期、私有文件存在性和 SHA-256 完整性。
   - 使用 `Content-Disposition: inline`、`Cache-Control: private, no-store` 与 `X-Content-Type-Options: nosniff` 返回图片。
   - 不直接跳转或转发萤石 URL。

3. 新增 `YINGMU_MEDIA_ACCESS_TOKEN` 配置项，并写入 `.env.example` 空值示例。

4. 新增 `tests/test_private_media_api.py`。
   - 未提供媒体令牌时返回 `401`。
   - 正确令牌可读取私有图片。
   - 私有文件被篡改时返回 `409 ASSET_MEDIA_INTEGRITY_FAILED`。
   - 保留期已过时返回 `410 ASSET_MEDIA_EXPIRED`。
   - `POST /device/snapshot` 响应不包含平台临时 URL。

5. 已验证：
   - `python -m pytest tests/test_private_media_api.py tests/test_snapshot_asset_service.py -q`
   - 结果：`21 passed`。
   - OpenAPI 已确认注册 `POST /api/v1/device/snapshot` 和 `GET /api/v1/assets/{asset_id}/content`。

## 3. 必须配置的环境变量

真实配置只放在仓库外的 live 配置文件，例如 `C:\YingMu-private\live.env`。不要在仓库根目录 `.env`、`.env.example`、前端环境文件、截图或 Git 提交中填写真实值。

主动抓拍持久化依赖以下已有配置，任一缺失或无效都会导致 `POST /api/v1/device/snapshot` 无法保存图片：

```dotenv
YINGMU_ENV=live
EZVIZ_APP_KEY=<真实值>
EZVIZ_APP_SECRET=<真实值>
EZVIZ_ACCESS_TOKEN=<真实值或可刷新配置>
EZVIZ_DEVICE_SERIAL=<真实值>
EZVIZ_CHANNEL_NO=1

YINGMU_PRIVATE_MEDIA_ROOT=<仓库外、可写的绝对路径>
YINGMU_CAMERA_POSITION_ID=<已冻结的现场机位 ID>
YINGMU_AUTHORIZATION_RECORD_ID=<有效授权记录 ID>
YINGMU_RETENTION_UNTIL=<未来且带时区的 ISO-8601 时间>
```

新增的媒体读取配置：

```dotenv
YINGMU_MEDIA_ACCESS_TOKEN=<高强度随机值>
```

关键要求：

- `YINGMU_PRIVATE_MEDIA_ROOT` 必须存在或可创建，且必须在仓库目录外；不能放在 Git、OneDrive 同步工作区或公开静态目录。
- `YINGMU_RETENTION_UNTIL` 必须晚于抓拍时间，并携带时区，例如 `2030-01-01T00:00:00+08:00`。不可使用示例时间作为正式授权期限。
- `YINGMU_MEDIA_ACCESS_TOKEN` 为空时，图片代理故意返回 `503 MEDIA_ACCESS_TOKEN_NOT_CONFIGURED`。
- 图片接口需要 `Authorization: Bearer <令牌>`；令牌错误或缺失返回 `401 MEDIA_ACCESS_FORBIDDEN`。
- **绝不能把 `YINGMU_MEDIA_ACCESS_TOKEN` 写入 `VITE_*` 变量、浏览器 JavaScript、静态 HTML 或客户端本地存储。** 这些位置的值会被终端用户读取。前端接入必须通过已有登录会话、受信任 BFF/反向代理注入凭据，或实现短期签名的媒体会话；不能把长期媒体令牌交给浏览器。
- 修改 live 配置后必须重启 FastAPI。`backend.config` 在进程启动/导入时读取环境变量，运行中的服务不会自动加载新值。

## 4. 当前接口用法

创建一张新的私有抓拍：

```text
POST /api/v1/device/snapshot
```

成功响应包含：

```json
{
  "asset": {
    "asset_id": "...",
    "source_mode": "LIVE_DEVICE",
    "simulated": false,
    "content_type": "image/jpeg",
    "content_sha256": "..."
  },
  "idempotent": false
}
```

读取图片：

```text
GET /api/v1/assets/{asset_id}/content
Authorization: Bearer <YINGMU_MEDIA_ACCESS_TOKEN>
```

这两个接口只面向 API/BFF 层。前端尚未接入，不能直接用 `<img src="...">` 携带 Bearer 令牌。

## 5. 当前卡点

1. 前端尚未实现受权图片展示。
   - 本轮按要求没有改动前端。
   - 浏览器原生 `<img>` 不能附加 `Authorization` 请求头，不能直接将内容接口拼到 `src`。
   - 下一位前端负责人需要在不暴露长期令牌的前提下，通过受信任 BFF、登录 Cookie 或短期签名会话实现 Blob 拉取并展示。

2. 未执行真实持久化抓拍。
   - 本轮没有为了验收代码而额外生成真实个人图像。
   - 启用前先确认授权、机位、保留期和私有目录均有效，再由授权操作员执行一次 `POST /api/v1/device/snapshot`。

3. 全量 `tests/test_risk_api.py` 未完成。
   - 原因：本机运行中的服务占用了 `test_risk_api.db`，Windows 无法删除该测试库。
   - 这不是本次新增测试的失败；不要通过删除业务数据库或强制杀掉现场服务来绕过。应在停止占用进程或干净测试环境后重新运行。

4. 当前工作区还有不属于本轮的未提交改动与运行产物。
   - 已知包括 `backend/README.md`、测试临时目录、历史 deliverables 等。
   - 提交本功能时只能显式暂存本轮文件，不使用 `git add .` 或 `git add -A`。

## 6. 下一步计划

1. 在仓库外 live 配置中生成并填入 `YINGMU_MEDIA_ACCESS_TOKEN`，确认不进入 Git。
2. 重启 FastAPI，先验证 `POST /api/v1/device/snapshot` 返回 `201` 和 `asset_id`。
3. 使用受控服务端请求或 BFF 验证 `GET /api/v1/assets/{asset_id}/content`：无令牌为 `401`，正确令牌为 `200 image/*`。
4. 前端负责人设计受权媒体会话，不把媒体令牌打包进浏览器；接入后完成跨机 VPN 场景下的页面展示验收。
5. 补充真实抓拍的脱敏审计证据：Asset ID、内容类型、字节数、哈希、授权状态、保留期和请求 ID；不保留图片副本、临时 URL 或令牌。
6. 在停止会占用 `test_risk_api.db` 的进程后，重新运行完整风险 API 回归。

## 7. 本轮踩过的坑

- 设备状态 `online=true` 仅表示萤石设备在线；它不等于网页已经可以安全播放/展示平台临时资源。
- 之前前端调用 `/api/v1/device/live-address` 返回 `404`，是既有后端安全约束：项目禁止把萤石临时直播 URL 公开给浏览器。不要为消除 `404` 而恢复该接口。
- 原 `GET /device/snapshot` 是脱敏探测接口，不会落盘图片；需要使用新增的 `POST /device/snapshot` 才会创建私有 Asset。
- 萤石临时图片 URL 不应进入 API 响应、日志、异常 debug、数据库公开字段或交接文档。
- 在 `device.py` 中不能直接使用名为 `status` 的导入模块，因为已有 `status()` 路由函数会遮蔽它；新增代码使用 `status as http_status`。
- 私有图片代理在每次读取前计算 SHA-256。文件被修改、替换或损坏时应返回 `409`，而不是把未知内容展示给用户。
- 若 FastAPI 没有重启，新增路由和新的环境变量不会生效；可以用 `/openapi.json` 检查新接口是否已注册。
