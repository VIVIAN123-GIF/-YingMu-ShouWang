# C6c 行为结果实际入库验收

此目录只保存脱敏摘要，不保存原始 MP4、关键点文件、外部 ZIP 路径、设备序列号或凭证。

运行命令：

```powershell
python scripts/run_behavior_replay_acceptance.py `
  --delivery-zip "<仓库外>\c6c-behavior-result-only-20260809.zip" `
  --sha256 "44943F36C48492BD6C3D225128E94192F9E5B5903DD8C51D784E51042B283116" `
  --output deliverables/c6c-behavior-replay-2026-08-09/summary.json
```

`PARTIAL` 表示 Asset 和 Observation 已实际写入临时后端并通过幂等检查。该交付包故意不含 Evidence，因此不会执行风险评估、创建事件或宣称完成自动实机闭环。
