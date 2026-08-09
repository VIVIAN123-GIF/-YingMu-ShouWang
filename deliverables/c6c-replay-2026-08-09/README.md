# C6c 录制回放验收

本目录只保存脱敏验收摘要，不保存视频、关键点原始文件、绝对路径、设备序列号或凭证。

运行命令：

```powershell
python scripts/run_c6c_replay_acceptance.py `
  --video-zip "<仓库外>\视频.zip" `
  --result-zip "<仓库外>\C6c真实素材处理结果_2026-08-08.zip" `
  --output deliverables/c6c-replay-2026-08-09/summary.json
```

本次交付包 SHA-256：

- 视频包：`26838EA4C2D2EC84BCAEB4A1C3AB79C1DAD135172D70513D10FCDCD6B8F71D76`
- 处理结果包：`CA6067483C7F7E568C4290C41EC76659C7EAD26EDD5958EA252696E733397F85`

`PARTIAL` 表示真实录制回放的 Asset → Observation → Evidence 提交和幂等验证通过，但素材自身没有达到风险决策的高置信度组合门槛；该结果不宣称实时设备自动闭环或 RESOLVED。
