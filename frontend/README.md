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

复制 `.env.example` 为 `.env.local` 可配置：

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_DATA_MODE=auto
VITE_AUTHORIZED_CLIP_URL=
```

- `auto`：优先请求 FastAPI；网络不可达、404/501 或服务端错误时切换固定 JSON。
- `api`：只读取 FastAPI，错误直接显示。
- `mock`：固定使用内置演示数据。

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

## API 模式联调清单

后续与冷雨彤统一使用 `VITE_DATA_MODE=api` 验证以下接口。每项需检查成功响应、统一数据契约、页面渲染、错误状态；家属反馈还需检查幂等回写。

| 方法 | 接口 |
|---|---|
| GET | `/api/v1/events` |
| GET | `/api/v1/events/{id}` |
| GET | `/api/v1/reports/weekly` |
| GET | `/api/v1/device/status` |
| GET | `/api/v1/assets/{id}` |
| POST | `/api/v1/events/{id}/feedback` |

当前清单仅表示待联调范围，不代表真实 API 已验证通过。

## 依赖审计说明

本次 `npm ci` 报告 6 项高危开发依赖问题，生产依赖审计为 0。该问题当前不阻塞演示，后续依赖升级时统一处理；本次不临时升级依赖，也不隐藏审计结果。

## 授权视频

将经过授权的视频放到 `public/media/authorized-fall-clip.mp4`，再将 `VITE_AUTHORIZED_CLIP_URL` 配置为 `/media/authorized-fall-clip.mp4`。视频文件默认不进入版本控制；未提供素材时页面会明确显示“待素材核验”。
