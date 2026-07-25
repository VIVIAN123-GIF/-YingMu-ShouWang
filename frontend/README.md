# 萤目守望统一家属端

基于 Vue 3、Element Plus 与 ECharts 的统一家属端。项目完整实现首页安全水位、事件详情、周报/核验，并为冻结方案中的其余一级页面提供低保真路由骨架。

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

## 授权视频

将经过授权的视频放到 `public/media/authorized-fall-clip.mp4`，再将 `VITE_AUTHORIZED_CLIP_URL` 配置为 `/media/authorized-fall-clip.mp4`。视频文件默认不进入版本控制；未提供素材时页面会明确显示“待素材核验”。

## 三次复现材料

```powershell
npm run evidence
```

命令会使用本机 Microsoft Edge 连续执行三轮固定闭环，在 `artifacts/evidence/run-1` 至 `run-3` 输出截图、WebM录屏、脱敏审计日志和验收摘要。HTML测试报告位于 `artifacts/evidence/report`。
