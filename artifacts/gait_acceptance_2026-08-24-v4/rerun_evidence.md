# 赵勇 GAIT v4 复跑证据

复跑时间：2026-08-24 16:56 (+08:00)

## 实现身份

本报告是在当前工作树 `HEAD=89f641e` 上生成的，`contracts/v1/gait_adapter.py` 最后修改提交为 `f0788d5`，视频特征提取来自 `contracts/v1/gait_video.py`。

赵勇反馈使用的是 `origin/feature/zy/modified-video-baseline`，其 adapter 文件最后修改提交为 `f068b21`。该分支的视频分支把 `stable_posture_duration` 固定为 `0.0`，与当前工作树的特征提取实现不同。因此两份输出不能直接互相否定，必须先选定一个规范提交再复跑。

## 范围

- 仅执行 `GAIT` adapter。
- `source_mode=RECORDED_REPLAY`、`simulated=true`。
- 未启动后端 Worker，未执行 TRAJECTORY，未创建 RiskEvent。
- 不包含凭证、Token、设备序列号或播放地址。

## 完整性

v4 supplement 中两段 MP4 的 SHA-256 均与 `manifest.csv` 和 `SHA256SUMS.txt` 一致：`2/2 passed`。

## 复跑结果

| 样本 | 输入规格 | 预期 | 当前实际 | 结论 |
|---|---|---|---|---|
| `normal/D2_WALK_02_right_to_left.mp4` | 568x320, 15 FPS, 16.867 s | `NO_EVIDENCE` | `SUCCESS`: `posture_recovered`, `relative_speed_change` | 预期不匹配 |
| `controlled_risk/5_rapid_rise_720p.mp4` | 1280x720, 15 FPS, 19.2 s | `SUCCESS`: 3 类 Evidence | `SUCCESS`: 4 类 Evidence，新增 `posture_recovered` | 预期不匹配 |

## 判定

当前工作树的 GAIT adapter 能稳定提取特征并返回有效 `AdapterBatch`，但不能把 v4 supplement 标记为通过：

1. v4 预检快照与赵勇分支输出属于不同 adapter 实现，当前不能作为同一基线比较。
2. 正常视频为 568x320，低于联调清单的 720p 输入目标。

## 需要赵勇补充

- 先确认联调规范提交：当前主干 `f0788d5`，或赵勇分支 `f068b21`，只能选一个。
- 在选定提交和同一 `.venv` 下重新生成 `manifest.csv` 与 `preflight_snapshot.json`，更新两段视频的 expected status/Evidence。
- 提供 720p 或更高分辨率的正常样本；不要用简单放大替代真实 720p 素材。
- 保持 `module_scope=GAIT`，本批次不纳入 TRAJECTORY。

详细机器可读结果见 [rerun_evidence.json](rerun_evidence.json)。
