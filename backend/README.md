# 幕目守望后端

后端采用 FastAPI、SQLAlchemy 2.0 异步 ORM 与 SQLite，负责统一 Observation、Evidence、风险事件、干预结果、设备状态、授权资产和周报数据。

## 目录

```text
backend/
├── api/          # FastAPI 路由与异常处理
├── db/           # 数据库引擎、模型与初始化
├── schemas/      # 请求与响应契约
├── service/      # 业务逻辑、风险规则、设备适配器
├── utils/        # 萤石鉴权与平台客户端
├── config.py     # 环境变量与运行配置
└── main.py       # 应用入口
```

## 启动

在仓库根目录执行：

```powershell
python -m pip install -r backend/requirements.txt
python -m backend.db.init_db
python -m uvicorn backend.main:app --reload
```

- Swagger：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

真实萤石凭证和设备视频加密验证码只可放在本地 `.env`，不得提交或写入日志。Mock 模式不需要真实凭证。

## 分层约定

- `api`：参数校验、响应状态码和调用 service；不直接编写业务判断。
- `service`：风险评估、事件状态、设备适配和数据聚合；通过异步 SQLAlchemy 会话读写模型。
- `db`：数据库连接、ORM 模型和初始化迁移；不承载业务规则。
- `schemas`：冻结接口的 Pydantic 契约。

调用链为：`HTTP 请求 → api → service → SQLAlchemy models → SQLite`。

## 验证

```powershell
python -m pytest tests/test_risk_api.py -q
python scripts/validate_database.py
```

真实设备三轮验收使用：

```powershell
python scripts/validate_ezviz_live.py --runs 3
```

脚本遵循“状态 → 抓图 → 临时播放地址”的顺序，分别保存三轮脱敏报告、最后一轮兼容报告和一致性汇总。任一阶段失败时退出码为 1，但已完成轮次仍会保留；设备离线会明确标记为 `FAILED/MOCK/DEVICE_OFFLINE`。加密设备的 HLS 请求返回 60019 时，若本地已配置验证码，脚本会尝试 ezopen 回退；报告只记录协议和结果，不保存地址。
