# 授权事件片段放置说明

固定 JSON 模式使用以下三个本地授权片段：

- `fall-risk-replay.mp4`：GAIT 受控实验中的快速起身与躯干摇晃片段。
- `activity-route-replay.mp4`：轨迹验证中的 A-B-C 区域路线原始授权片段（HEVC 源文件）。
- `activity-route-replay-browser.mp4`：同一片段的 H.264 浏览器兼容播放副本。
- `daily-baseline-replay.mp4`：三参与者实验 P03 的日常基线原始授权片段（HEVC 源文件）。
- `daily-baseline-replay-browser.mp4`：同一片段的 H.264 浏览器兼容播放副本。

如需临时替换跌倒风险片段，可在 `.env.local` 中配置：

```text
VITE_AUTHORIZED_CLIP_URL=/media/authorized-fall-clip.mp4
```

视频文件默认被 `.gitignore` 排除，不应把未经授权的家庭视频提交到仓库。页面只播放 H.264 兼容副本，原始 HEVC 文件仅作为受控来源保留。页面只有在浏览器成功读取视频首帧后才显示“授权片段已加载”，并始终标记为 `RECORDED_REPLAY / 模拟实验回放`。
