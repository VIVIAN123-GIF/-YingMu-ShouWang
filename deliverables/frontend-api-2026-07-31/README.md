# 前端 API 模式三轮验收

本目录保存陈硕前端通过真实 HTTP 对接 FastAPI 后的脱敏验收摘要、完整接口交换、状态证据、审计日志和关键截图。

- `data_mode=api` 表示前端没有使用固定 JSON 降级。
- 后端工具与 Evidence 仍为 `source_mode=MOCK`、`simulated=true`，不代表真实设备验收。
- 三轮完整 WebM 不提交仓库，由 `npm run evidence:api` 生成在 `frontend/artifacts/api-evidence`，并打包为本地 ZIP 供上传飞书。
- 每轮必须由页面自动同步复现 `INTERVENING → OBSERVING → RESOLVED`，中途不刷新页面，并验证家属反馈首次写入 `201`、幂等重放 `200`。
- 每轮保存 `requests.json`、`responses.json`、三个事件快照、RuleTrace、状态迁移、InterventionResult、前端审计日志和三张状态截图。
- 所有结构化材料在写盘前递归脱敏，不保存 Token、密码、鉴权头或永久媒体地址。

复现命令：

```powershell
cd frontend
npm run evidence:api
```
