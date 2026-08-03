# 授权 C6c 录像适配与验收

## 环境

使用 Python 3.11 和仓库 `.venv`：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -r contracts\requirements.txt -r deliverables\zy\pose-demo\requirements.txt
.\.venv\Scripts\python.exe deliverables\zy\pose-demo\scripts\download_pose_model.py
```

模型、视频、本地清单、逐帧输出和绝对路径均被 Git 忽略。

## 视频转契约包

```powershell
.\.venv\Scripts\python.exe deliverables\zy\pose-demo\scripts\recorded_replay_adapter.py `
  --manifest ..\视频\recording_manifest.local.json `
  --video-dir ..\视频 `
  --model models\pose_landmarker_heavy.task `
  --output-root ..\视频\processed
```

每个 `take_id` 输出 `frames.csv`、`landmarks.csv`、`analysis.json` 和 `package.json`。人工时间点仅用于核对；Evidence 数值来自真实帧。修改组包规则后可加 `--reuse-analysis`，从已提取的本地逐帧结果重建包而不重复推理。

## FastAPI闭环

```powershell
.\.venv\Scripts\python.exe scripts\run_recorded_replay_acceptance.py `
  --package-root ..\视频\processed `
  --output ..\视频\processed\http_acceptance.json
```

脚本使用临时数据库并逐场景隔离，执行资产、Observation、Evidence和重复提交。详细请求响应留在本地；仓库仅保存脱敏汇总。

## 强制边界

- `data_quality` 或 `confidence < 0.70` 的动作候选不生成业务 Evidence，并记录 `QUALITY_BLOCKED`。
- 快速起身单独只生成 `rapid_rise`，预期为 GREEN。
- `posture_recovered.current_value` 是连续稳定秒数；角度保存为独立 Observation。
- 没有一条组合证据置信度达到0.80时不得声称 ORANGE。
- 没有完成稳定后的60秒观察时不得声称 RESOLVED。
- 危险和控制录像不得写入个人正常基线。

