# 张同学 D2 萤石真实抓拍交付

状态：`ENGINEERING_READY_FOR_FIELD_CAPTURE`

## 已完成工程能力

- 萤石抓拍结果通过 `PlatformSnapshotResult` 校验。
- 临时图片 URL 只保留在进程内，公共接口和验收文件均不保存。
- 公共抓拍响应只返回脱敏审计字段，不提前伪造 Asset。
- 实机验收脚本支持仅抓拍模式和独立输出目录。
- 每次尝试单独保存；失败记录不会被成功记录覆盖。
- 汇总报告统计成功、失败、跳过和抓拍延迟。

## 现场前置条件

1. 张同学在仓库外安全渠道确认当前 AppKey/AppSecret 已完成轮换。
2. 只在本机 `.env` 写入凭证、完整设备序列号和验证码。
3. 蔡同学确认 C6c 在线、机位为 `living-room-c6c-v1`、镜头无遮挡。
4. 确认素材授权记录有效，现场不拍摄未授权人员。
5. 冷同学确认后端下载器已准备接收进程内 `PlatformSnapshotResult`。

## 本地配置

`.env` 至少配置以下字段，真实值不得写入本文档或聊天：

```dotenv
YINGMU_ENV=live
EZVIZ_APP_KEY=
EZVIZ_APP_SECRET=
EZVIZ_DEVICE_SERIAL=
EZVIZ_CHANNEL_NO=1
EZVIZ_CAPTURE_TIMEOUT_SECONDS=45
EZVIZ_RESIDENT_ID=
```

`EZVIZ_ACCESS_TOKEN` 可以留空，由 AppSecret 获取并缓存。D2 抓拍不需要
`EZVIZ_DEVICE_VERIFY_CODE`，该字段只与后续取流验证有关。

## 运行前检查

```powershell
git check-ignore -v .env
py -3.14 -m pytest tests/test_zhang_d2_snapshot.py -q
```

第一条命令必须显示 `.env` 被根目录 `.gitignore` 忽略。

## 执行十次连续抓拍

在项目根目录运行：

```powershell
py -3.14 scripts/validate_ezviz_live.py `
  --runs 10 `
  --interval-seconds 5 `
  --capture-only `
  --output-dir deliverables/zhang-d2-snapshot-2026-08-15/batch-1
```

非零退出码表示至少一次调用不完整，但报告仍会生成。不得删除失败记录。
问题修复后应改用 `batch-2`，不能覆盖 `batch-1`。

## 自动生成文件

```text
batch-1/
├── ezviz-live-validation-run-1.json
├── ...
├── ezviz-live-validation-run-10.json
├── ezviz-live-validation.json
└── ezviz-live-validation-summary.json
```

检查汇总文件：

- `runs` 必须为 `10`；
- `acceptance_mode` 必须为 `CAPTURE_ONLY`；
- `capture_records` 必须为 `10`；
- 目标是 `capture_successes=10`；
- `contains_credentials` 和 `contains_temporary_url` 必须为 `false`。

失败同样是有效实测证据。若不足 10 次成功，应在 PR 和能力矩阵中如实
写明成功数、失败原因和是否重跑，不能把 Mock 或历史图片计入成功。

## 人员交接

### 张同学

- 执行十次连续真实调用并保留完整批次。
- 将每次 `request_id` 和时间填写到现场核对表。
- 检查报告中没有 Token、完整设备序列号、验证码或 URL。

### 蔡同学

- 在每次调用时确认设备在线和现场画面状态。
- 根据后端已下载的受保护图片核对机位、时间和画面。
- 填写 `field-verification-template.md`，不把人脸截图提交到 Git。

### 冷同学

- 只在后端进程内读取 `PlatformSnapshotResult.temporary_url`。
- 立即下载并验证 HTTP 200、`image/*` 和非零字节。
- 计算 SHA-256，保存到受控目录，再创建 Asset。
- Asset 成功前不得写入 `capture_asset_id`。

## 禁止项

- 不提交 `.env`、Token、AppSecret、验证码或完整设备序列号。
- 不保存萤石临时 URL，不复制到群聊、日志、RuleTrace 或前端。
- 不用本地图片冒充 `LIVE_DEVICE`。
- 不因为抓拍成功而宣称取流、语音或算法闭环已经成功。
