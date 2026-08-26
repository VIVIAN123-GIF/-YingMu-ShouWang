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

萤石 WebHook 的慢处理独立于 HTTP 服务运行。开发时在第二个终端执行：

```powershell
python -m backend.worker.alarm_worker
```

回调接口只会完成验签、去重、告警入库和任务入队，然后立即返回 `messageId`。Worker 会为每条新告警抓取一次平台快照，并在算法适配器接入前将任务标记为 `WAITING_ALGORITHM`；它不会伪造 Observation、Evidence 或 RiskEvent。可通过 `GET /api/v1/alarms/processing` 查看脱敏后的处理状态。

- Swagger：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

真实萤石凭证和设备视频加密验证码只可放在本地 `.env`，不得提交或写入日志。Mock 模式不需要真实凭证。

## 分层约定

- `api`：参数校验、响应状态码和调用 service；不直接编写业务判断。
- `service`：风险评估、事件状态、设备适配和数据聚合；通过异步 SQLAlchemy 会话读写模型。
- `db`：数据库连接、ORM 模型和初始化迁移；不承载业务规则。
- `schemas`：冻结接口的 Pydantic 契约。

调用链为：`HTTP 请求 → api → service → SQLAlchemy models → SQLite`。

## 决策规则来源

后端不维护第二套风险阈值。张薇已合并的
`contracts/v1/rulesets/ruleset-v1.2.json` 是当前规则版本、短中长时间窗和
观察阈值的唯一来源；`contracts/v1/engine.py` 是对应的确定性 Mock
状态机。`backend/service/risk_service.py` 负责把该规则集适配到持久化
RiskEvent、Evidence 和 RuleTrace。

独立的前置预警层由 `contracts/v1/rulesets/ruleset-v1.3-min.json` 和
`backend/service/forewarning_service.py` 实现，输出三时间尺度、四分量的
工程风险指数。它不替代 v1.2 事件裁决，也不表示跌倒概率。查询接口为：

```text
GET /api/v1/residents/{id}/forewarning/latest
GET /api/v1/residents/{id}/forewarning
GET /api/v1/events/{id}/forewarning
GET /api/v1/scene-calibrations/{id}
```

常易铭的语音/行为算法只提交 Observation 与 Evidence，不提交最终风险
等级。可用下面的隔离验收命令验证其 2026-08-03 原始交付物：

```powershell
python scripts/validate_voice_behavior_package.py
```

## 验证

```powershell
python -m pytest tests/test_risk_api.py -q
python scripts/validate_database.py
python -m scripts.yingmu_launcher self-check
```

`self-check` 只检查关键模块、v1.2/v1.3-min 规则集、姿态模型、场景配置和运行目录，
不会访问萤石设备。Windows 发布包使用等价命令：

```powershell
.\YingMuShouWang.exe self-check
.\YingMuShouWang.exe demo
.\YingMuShouWang.exe live --config config\.env.local
```

`demo` 固定启动 API、Alarm Worker 和 Agent Worker。`live` 在
`YINGMU_STREAM_BUFFER_ENABLED=true` 时额外启动 Stream Buffer Worker；任一子进程异常退出时，
启动器会统一回收全部子进程。缓冲尚未预热时告警链路保守回退到告警后直录，现场验收前仍须运行
`scripts/check_stream_buffer.py` 并确认 `ready=true`。

v1.3-min 录制素材验收器使用显式结果模式。负向模式要求全程不创建 RiskEvent：

```powershell
python scripts/run_v13_closed_loop_acceptance.py `
  --expected-outcome NO_EVENT --input <授权负向视频> `
  --database <临时数据库> --private-root <仓库外私有目录> `
  --captured-at <带时区拍摄时间> --retention-until <带时区保留期限>
```

正向模式还必须提供 `--recovery-input`、`--recovery-captured-at` 和 `--resolve-at`，并满足恢复观察窗口。
报告统一标记为 `RECORDED_TIMELINE`；当前自动化只证明正向工程链路可达，真实像素
`EVENT_RESOLVED` 报告仍需补拍两段已授权风险/恢复素材后生成，不能表述为实时等待或真实老人医学验证。

真实设备三轮验收使用：

```powershell
python scripts/validate_ezviz_live.py --runs 3
```

脚本遵循“状态 → 抓图 → 临时播放地址”的顺序，分别保存三轮脱敏报告、最后一轮兼容报告和一致性汇总。任一阶段失败时退出码为 1，但已完成轮次仍会保留；设备离线会明确标记为 `FAILED/MOCK/DEVICE_OFFLINE`。加密设备的 HLS 请求返回 60019 时，若本地已配置验证码，脚本会尝试 ezopen 回退；报告只记录协议和结果，不保存地址。
