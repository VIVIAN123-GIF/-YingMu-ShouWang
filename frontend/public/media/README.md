# 授权事件片段放置说明

固定 JSON 模式使用以下三个本地授权片段：

- `new-risk-left-take03.mp4`：2026-09-03 新拍受控风险动作。真实算法为 YELLOW；ORANGE 闭环指标为显式模拟数据。
- `new-normal-control-take02.mp4`：2026-09-03 新拍正常动作对照。原片未通过算法质量门；绿色页面读数为显式模拟数据。
- `new-recovery-take01.mp4`：2026-09-03 新拍恢复状态。真实算法输出 `posture_recovered / GREEN`。
- `activity-route-replay.mp4`：轨迹验证中的 A-B-C 区域路线原始授权片段（HEVC 源文件）。
- `activity-route-replay-browser.mp4`：同一片段的 H.264 浏览器兼容播放副本。
- `daily-baseline-replay.mp4`：三参与者实验 P03 的日常基线原始授权片段（HEVC 源文件）。
- `daily-baseline-replay-browser.mp4`：同一片段的 H.264 浏览器兼容播放副本。

如需临时替换跌倒风险片段，可在 `.env.local` 中配置：

```text
VITE_AUTHORIZED_CLIP_URL=/media/authorized-fall-clip.mp4
```

视频文件默认被 `.gitignore` 排除，不应把未经授权的家庭视频提交到仓库。页面只播放 H.264 兼容副本，原始 HEVC 文件仅作为受控来源保留。页面只有在浏览器成功读取视频首帧后才显示“授权片段已加载”，并始终标记为 `RECORDED_REPLAY / 模拟实验回放`。

## 精选演示片段（仅本地受限发布包）

`selected/` 是事件详情页使用的 28 条受控工程对照片段。先在仓库根目录保留私有 `视频/` 源目录，再执行：

```powershell
cd frontend
npm run media:build
npm run media:verify
```

选择清单只记录匿名编号、场景、用途、源 SHA-256 与时长；前端不显示源路径或原始文件名。`npm run build:pages` 会主动排除整个 `public/` 目录，因此不会将这些真人视频放入公开 Pages 构建产物。
