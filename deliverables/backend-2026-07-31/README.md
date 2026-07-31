# 后端 7 月 31 日交付包

## 启动

```powershell
python -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
python -m backend.db.init_db
python -m uvicorn backend.main:app --reload
```

- Swagger: http://127.0.0.1:8000/docs
- 健康检查: http://127.0.0.1:8000/health
- Mock 模式不需要真实萤石密钥。
- Live 模式只允许通过 `.env` 配置已经轮换的新凭证，禁止提交 `.env`。
- 设备开启视频加密时，将验证码写入本地 `EZVIZ_DEVICE_VERIFY_CODE`；该值只用于临时播放地址请求，不得进入报告或日志。

## 自动测试

```powershell
python -m pytest tests/test_risk_api.py -q
```

当前测试还覆盖：冻结 Evidence 名称校验、事件列表与前端详情结构、干预结果、家属反馈幂等、授权资产、周报和带控制令牌的一键停止采集。

完整的前端/算法兼容关系及实机阻塞项见 `interface-compatibility.md`。实机能力未验证前不得把 Mock 结果描述为真实萤石调用成功。

当前完整 Python 测试结果为 `65 passed`。测试覆盖 GREEN→ORANGE→OBSERVING→RESOLVED、0.70 质量门控、SYSTEM 质量 Evidence、幂等、基线准入、资产、干预、反馈、周报、授权停止采集，以及萤石验收报告的离线降级、业务消息脱敏、三轮独立归档和加密设备 ezopen 回退。

生成四项真实HTTP请求、响应、RuleTrace和结构化日志：

```powershell
python scripts/run_backend_http_acceptance.py
```

结果保存在`deliverables/backend-2026-07-31/results/`，固定验收摘要中的`passed`必须为`true`。

真实设备三轮验收在确认凭证已经重新轮换、且只存在本地 `.env` 后执行：

```powershell
python scripts/validate_ezviz_live.py --runs 3
```

脚本生成 `ezviz-live-validation-run-1/2/3.json`、`ezviz-live-validation-summary.json`，并以最后一轮更新兼容文件 `ezviz-live-validation.json`。非零退出码表示至少一轮不完整，不表示报告未生成。加密设备的 HLS 请求返回 60019 时可回退 ezopen；取得 ezopen 地址只能证明地址获取成功，不能声明 HLS 或实际播放成功。所有文件只允许包含设备别名和脱敏业务消息，不得保存完整序列号、凭证、图片或播放地址。

## 固定请求顺序

依次提交 `requests` 中的 01—07。第二条正常Evidence自动生成
`event-mock-fall-001`，无需修改数据库。随后调用：

```text
POST /api/v1/risk/evaluate
GET  /api/v1/residents/resident-mock-001/baseline
GET  /api/v1/events/event-mock-fall-001
```

## 数据库重新初始化

先停止服务。备份现有 `ezviz_system.db` 后，将其移出仓库目录，再执行：

```powershell
python -m backend.db.init_db
```

不得在未备份时删除现有数据库。测试使用独立的 `test_risk_api.db`。

## 已知限制

- 当前只有一台冻结方案指定的萤石 C6c，原任务中的“双路摄像头”已被冻结决策 D021 替代。
- 实机请求结果必须使用轮换后的 AppSecret/AccessToken 重新生成；泄露在聊天图片中的凭证禁止继续使用。
- FastAPI 已实现当前冻结的跌倒 P0 升级与恢复闭环；三轮闭环记录使用明确标注的 Mock 虚拟时间，不能描述成实机设备闭环。
- 2026-07-30 的旧实机记录确认设备状态与抓图成功，临时播放地址返回业务码 60019 并降级为 `MOCK`；聊天中出现过的凭证再次按泄露处理，完成新一轮安全轮换前不得重跑或据此声明最终验收完成。
