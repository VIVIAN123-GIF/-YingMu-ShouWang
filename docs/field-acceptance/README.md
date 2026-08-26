# 最终现场验收资料包

本目录只保存空白模板、脱敏示例和执行口径，不保存参与者姓名、签名、设备序列号、凭证、私有路径或原始视频。

## 两条证据链

1. `RECORDED_REPLAY/simulated=true`：同一授权健康成年参与者、同一固定机位的风险段和恢复段，用于验证真实录制像素的 ORANGE、模拟干预、OBSERVING 和 RESOLVED 闭环。
2. `LIVE_DEVICE/simulated=false`：真实萤石设备的 H.264、环形缓冲、GAIT、TRAJECTORY、来源继承和保守 `YELLOW/REVIEW` 验收，不自动干预。

两条链路必须分别记录和表述。不得把授权回放写成实机实时事件，也不得把健康成年人受控模拟写成真实老人验证。

## 使用顺序

1. 负责人和参与者签署 `01-授权与安全确认.md`，签字件保存到仓库和 OneDrive 外的受控目录。
2. 拍摄人员逐项完成 `02-现场执行检查表.md`。
3. 拍摄后立即填写 `03-positive-pair-manifest.template.csv`，两名标注员在运行算法前冻结人工标签。
4. 根据最终画幅替换 `04-scene-calibration.example.json` 的全部示例标识和坐标，再用安装工具写入仓库外目录。
5. 按 `05-live-device-acceptance-checklist.md` 执行一次实机验收，并将脱敏结果写入 `06-live-device-acceptance.template.json` 的副本。

## 正向回放命令

```powershell
.\.venv\Scripts\python.exe scripts\run_v13_closed_loop_acceptance.py `
  --expected-outcome EVENT_RESOLVED `
  --input <风险段> --recovery-input <恢复段> `
  --database <仓库外数据库> --private-root <仓库外私有媒体目录> `
  --captured-at <带时区时间> --recovery-captured-at <带时区时间> `
  --resolve-at <恢复时间至少60秒后的时间> --retention-until <带时区期限> `
  --scene-config-id <最终场景ID> --scene-config-dir <仓库外场景目录> `
  --camera-position-id <最终机位ID> --report <脱敏报告>
```

阈值、人工标签和来源标识不得为了得到预期结果而修改。失败片段标为 `REJECTED` 或 `ABORTED` 并保留失败原因，重新拍摄使用新的 `clip_id`。
