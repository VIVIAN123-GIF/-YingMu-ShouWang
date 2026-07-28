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

## 自动测试

```powershell
python -m pytest tests/test_risk_api.py -q
```

当前本地验证结果：后端API `6 passed`，原智能体契约与规则测试 `37 passed`。测试覆盖GREEN→ORANGE、0.70质量门控、SYSTEM质量Evidence、幂等、基线准入和主要错误状态码。

生成四项真实HTTP请求、响应、RuleTrace和结构化日志：

```powershell
python scripts/run_backend_http_acceptance.py
```

结果保存在`deliverables/backend-2026-07-31/results/`，固定验收摘要中的`passed`必须为`true`。

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
- `MockRiskEngine` 实现当前冻结的跌倒 P0 规则；若队长另有同名正式引擎文件，应以共同确认版本替换，接口层无需改名。
- 摄像头虽然已到货、绑定且App画面可用，但开放平台凭证尚未配置，当前后端验收仍明确使用`source_mode=MOCK`。
