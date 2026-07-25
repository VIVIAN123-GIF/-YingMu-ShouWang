# 赵勇：MediaPipe 姿态 Demo 交付

本目录对应分支 `feature/zy/pose-demo` 的独立交付，不覆盖主项目根目录说明。

当前阶段结论：

- MediaPipe 官方 Pose Landmarker Demo 已跑通
- 可从视频或 RGB 图像序列中提取 33 个关键点
- URFD 已完成下载和本地整理
- Pre-VFall 尚未完成下载，不作为当前阶段阻塞项

会议中应表述为：

> MediaPipe 官方姿态 Demo 已跑通，可以提取 33 个关键点；跌倒前兆特征、数据质量和 Evidence 生成仍待实现验证。

## 目录说明

- `requirements.txt`：依赖版本
- `scripts/`：姿态估计相关脚本
- `samples/`：33 点关键点 CSV 样例
- `logs/`：脱敏运行日志
- `evidence/`：`rapid_rise`、`trunk_sway`、`gait_instability` 占位样例
- `datasets.md`：URFD / Pre-VFall 下载地址、用途和当前状态
- `failure_scenarios.md`：当前已知失败场景说明

## 当前真实可运行环境

当前本机已验证环境：

- Python `3.9.25`
- `mediapipe 0.10.21`
- `opencv-contrib-python 4.11.0.86`
- `numpy 1.26.4`

安装命令：

```powershell
.\.venv\Scripts\python.exe -m pip install -r deliverables/zy/pose-demo/requirements.txt
```

验证命令：

```powershell
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/verify_setup.py --model models/pose_landmarker_heavy.task
```

验收通过标志：

```text
PoseLandmarker initialization: OK
```

## 运行命令

下载模型：

```powershell
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/download_pose_model.py --output models/pose_landmarker_heavy.task
```

下载 URFD：

```powershell
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/download_datasets.py --dataset urfd --include-preview-mp4
```

对本地视频运行姿态估计：

```powershell
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/run_pose_demo.py --input data/raw/urfd/samples/fall-01-cam0.mp4 --model models/pose_landmarker_heavy.task --max-frames 60
```

对 RGB 图像序列运行姿态估计：

```powershell
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/run_pose_demo.py --input data/raw/urfd/extracted/adl-01-cam0-rgb --model models/pose_landmarker_heavy.task --max-frames 60
```

## 33 点输出说明

关键点 CSV 字段固定为：

```text
source_video, frame_idx, timestamp_ms, landmark_id, x, y, z, world_x, world_y, world_z, visibility, presence
```

33 点验收方式：

- `landmark_id` 唯一值数量应为 `33`

样例文件：

- `samples/fall-01-cam0_landmarks_sample.csv`

## Evidence 样例说明

当前仓库还没有完整的跌倒前兆算法输出，`evidence/` 中的 JSON 仅为本阶段接口占位样例，不代表算法已经完成。

## 当前边界

当前可以确认：

- 姿态关键点提取可运行
- 33 点 CSV 可导出
- URFD 可作为当前阶段主数据源

当前尚未完成：

- `rapid_rise`、`trunk_sway`、`gait_instability` 的正式规则或模型
- 低照度、遮挡、出画条件下的稳定性验证
- Pre-VFall 的完整下载和实测
