# 萤目守望统一家属端

基于 Vue 3、Element Plus 与 ECharts 的统一家属端。项目完成九个一级入口，其中四个核心页面完成，其余为低保真骨架。

## 启动

```powershell
npm install
npm run dev
```

默认访问 `http://localhost:5173`。生产检查：

```powershell
npm test
npm run build
```

## 端到端复现

首次端到端测试因缺少 Playwright 录屏组件失败，需先安装 ffmpeg：

```powershell
npx playwright install ffmpeg
npm run evidence
```

三轮复现是**固定 Mock 前端展示闭环，不代表真实算法和设备闭环**。复现材料输出到 `artifacts/evidence/run-1` 至 `run-3`，包括截图、WebM 录屏、脱敏审计日志和验收摘要。

GitHub 的 `.gitignore` 排除了 `artifacts/`，因此原 PR 本身不包含这些证据。请至少将以下文件中的一份截图和一份录屏上传到飞书或会议材料，并在对应记录中保留摘要：

- `01-home.png`
- `02-timeline.png`
- `04-event-trace.png`
- `screen-recording.webm`
- `summary.json`

HTML 测试报告生成于 `artifacts/evidence/report`，同样不会随原 PR 提交。

## 数据模式

复制 `frontend/.env.example` 为 `frontend/.env.local` 可配置：

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_DATA_MODE=auto
VITE_RESIDENT_ID=resident-001
VITE_AUTHORIZED_CLIP_URL=
```

- `auto`：优先请求 FastAPI；网络不可达、404/501 或服务端错误时切换固定 JSON。
- `api`：只读取 FastAPI，错误直接显示。
- `mock`：固定使用内置演示数据。

`VITE_RESIDENT_ID` 用于统一首页、事件、周报和基线查询的居民标识；API 验收脚本会覆盖为隔离的验收居民。

页面右上角可在运行时切换模式。演示数据覆盖绿色日常、黄色心理趋势、橙色跌倒干预与回落、诈骗核验和工具失败。

## 接口边界

前端对接 `/api/v1/events`、事件详情、个人基线、周报、设备状态、截图、授权片段和家属反馈接口。页面不持有萤石账号、AccessToken 或永久公开视频地址。

每个事件和回放必须显示 `LIVE_DEVICE`、`RECORDED_REPLAY`、`PUBLIC_DATASET` 或 `MOCK`；模拟内容必须带“模拟实验回放”水印。

### 四对象 v1.0 契约

- `RiskEvent.evidence_summary` 只保留 `evidence_id`、`evidence_type`、`explanation` 三个摘要字段。
- 完整 Evidence、Observation 和 InterventionResult 仅放在前端 ViewModel 的 `evidences`、`observations`、`interventions` 中，不作为 RiskEvent 核心字段回传。
- Evidence 不直接保存 `asset_id`，素材通过 `observation_ids` 追溯到 Observation；Observation 的 `asset_id` 必须存在但允许为 `null`，页面显示“暂无可追溯视频”。
- 前端会校验四对象的 `schema_version`、身份字段、版本字段、来源与模拟状态等冻结必填项。
- 可复用样例位于 `contracts/v1/examples/four-objects.json`。

## API 模式联调与三轮验收

使用隔离 SQLite 和 FastAPI Mock 工具运行真实 HTTP 前端验收：

```powershell
npm run evidence:api
```

脚本使用 `8010` 端口启动临时后端、用 `VITE_DATA_MODE=api` 启动前端，连续三轮验证以下接口。仓库证据位于 `deliverables/frontend-api-2026-07-31`；完整 WebM 和飞书上传包生成于 `frontend/artifacts/api-evidence`。

| 方法 | 接口 |
|---|---|
| GET | `/api/v1/events` |
| GET | `/api/v1/events/{id}` |
| GET | `/api/v1/reports/weekly` |
| GET | `/api/v1/device/status` |
| GET | `/api/v1/assets/{id}` |
| POST | `/api/v1/events/{id}/feedback` |

截至 2026-07-30，三轮均已验证页面无需刷新即可自动同步 `INTERVENING → OBSERVING → RESOLVED`，并完成 Evidence/Observation 追溯、InterventionResult 同步和反馈幂等 `201 → 200`。每轮仓库材料包含完整脱敏请求/响应、事件快照、RuleTrace、状态迁移、工具结果、审计日志和关键截图；这里的 `data_mode=api` 只表示前端真实调用 FastAPI，Evidence 与工具仍标记为 `source_mode=MOCK`、`simulated=true`，不宣称真实设备闭环。

## 个人基线与活动热力图

`/baseline` 展示后端中位数、MAD、样本数、有效天数和基线状态。固定 Mock 数据额外提供“日期 × 时段”近七日活动热力图，并显示“模拟实验回放”。当前后端未提供活动时序接口，因此 API 模式只展示真实基线统计和明确空状态，不使用 Mock 趋势补位。

## 8 月 13 日周报与核验卡验收

`/weekly` 在固定 Mock 模式下提供黄色趋势周报、家属关怀确认和诈骗访客核验卡。关怀与核验反馈都通过统一的 `submitFamilyFeedback` 写入，并使用稳定反馈 ID 保障重复提交幂等；页面只更新提交结果文案，不自行改变风险状态。

- 周报：展示趋势 Evidence、低打扰原则和一次性关怀建议；文案不作医学诊断。
- 关怀确认：提交后显示“关怀反馈已记录”，来源和模拟状态沿用报告数据。
- 诈骗核验卡：展示访客、停留时长和高风险组合词三类 Evidence，提交后显示“身份核验已记录”。
- API 模式：后端未返回趋势、关怀选项或 `visitor_case` 时显示明确空状态，不用 Mock 数据补位。

生成 8 月 13 日前端演示证据：

```powershell
npm run evidence -- --grep "8月13日前端周报"
```

材料输出到 `artifacts/weekly-evidence-2026-08-13` 和仓库交付目录 `deliverables/frontend-2026-08-13`。其中内容均为 `MOCK`/`RECORDED_REPLAY` 模拟演示，不代表真实诈骗识别或真实设备闭环。

## 依赖审计说明

本次 `npm ci` 报告 6 项高危开发依赖问题，生产依赖审计为 0。该问题当前不阻塞演示，后续依赖升级时统一处理；本次不临时升级依赖，也不隐藏审计结果。

## 授权视频

将经过授权的视频放到 `public/media/authorized-fall-clip.mp4`，再将 `VITE_AUTHORIZED_CLIP_URL` 配置为 `/media/authorized-fall-clip.mp4`。视频文件默认不进入版本控制；未提供素材时页面会明确显示“待素材核验”。
