# 授权事件片段放置说明

将经过授权的短视频命名为 `authorized-fall-clip.mp4` 放在本目录，并在 `.env.local` 中配置：

```text
VITE_AUTHORIZED_CLIP_URL=/media/authorized-fall-clip.mp4
```

真实视频文件默认被 `.gitignore` 排除，不应把未经授权的家庭视频提交到仓库。页面只有在浏览器成功读取视频元数据后才显示“授权片段已加载”。
