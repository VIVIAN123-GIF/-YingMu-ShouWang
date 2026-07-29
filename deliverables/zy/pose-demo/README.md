# 赵勇：MediaPipe 姿态 Demo 交付

本目录对应分支 `feature/zy/pose-demo` 的独立交付，不覆盖主项目根目录说明。

当前阶段结论：

- MediaPipe 官方 Pose Landmarker Demo 已跑通
- 可从视频或 RGB 图像序列中提取 33 个关键点
- URFD 已完成下载和本地整理
- 已完成步态特征提取 pipeline 首版，实现：
  - `step_speed`
  - `sway_frequency_hz`
  - `step_length_asymmetry_ratio`
- 已补充快速起身 `rapid_rise` 正式规则首版，可从清洗后的姿态帧生成 Freeze v1.0 Evidence
- 已生成清洗后数据集与序列级特征数据集
- Pre-VFall 尚未完成下载，不作为当前阶段阻塞项

会议中应表述为：

> MediaPipe 官方姿态 Demo 已跑通，可以提取 33 个关键点；起身、摇晃和相对步速第一版已具备可复现产物；`trunk_sway` 和 `gait_instability` 的正式 Evidence 阈值仍待后续实机验证。

## 目录说明

- `requirements.txt`：依赖版本
- `scripts/`：姿态估计相关脚本
- `samples/`：33 点关键点 CSV 样例
- `logs/`：脱敏运行日志
- `evidence/`：`rapid_rise` 正式规则样例，以及 `trunk_sway`、`gait_instability` 占位样例
- `datasets.md`：URFD / Pre-VFall 下载地址、用途和当前状态
- `failure_scenarios.md`：当前已知失败场景说明
- `processed/`：清洗后逐帧数据、序列级特征表和构建摘要

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

构建步态特征数据集：

```powershell
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/build_gait_feature_dataset.py --model models/pose_landmarker_heavy.task --urfd-root data/raw/urfd --output-dir deliverables/zy/pose-demo/processed --camera-filter cam0 --frame-stride 2
```

构建快速起身 Evidence：

```powershell
.\.venv\Scripts\python.exe deliverables/zy/pose-demo/scripts/build_rapid_rise_evidence.py --frames-csv deliverables/zy/pose-demo/processed/urfd_pose_cleaned_frames.csv --output deliverables/zy/pose-demo/evidence/rapid_rise.json
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

当前样例说明：

- 共 `99` 行有效数据
- 包含 `3` 个检测成功帧
- 每个成功帧都覆盖 `0—32` 共 `33` 个 `landmark_id`

## Evidence 样例说明

当前 `rapid_rise.json` 由快速起身规则脚本生成，符合 Freeze v1.0 Evidence 字段。`trunk_sway` 和 `gait_instability` 仍为接口占位样例，不代表对应 Evidence 规则已经完成。

当前样例文件：

- `evidence/rapid_rise.json`
- `evidence/trunk_sway.json`
- `evidence/gait_instability.json`

## 步态特征与清洗后数据集

当前已交付：

- `scripts/build_gait_feature_dataset.py`
- `scripts/build_rapid_rise_evidence.py`
- `processed/urfd_pose_cleaned_frames.csv`
- `processed/urfd_gait_features.csv`
- `processed/build_summary.json`
- `evidence/rapid_rise.json`

本次构建口径：

- 数据源：`URFD`
- 视角：仅 `cam0`
- 抽帧：`frame_stride=2`
- 标签：`fall / adl`

逐帧清洗后数据字段包含：

- `sequence_id`
- `label`
- `frame_number`
- `timestamp_ms`
- `pelvis_x / pelvis_y`
- `shoulder_x / shoulder_y`
- `trunk_angle_deg`
- `ankle_gap`
- `left_stride_extent / right_stride_extent`
- `core_visibility_min / core_visibility_mean`
- 平滑后的关键派生量

序列级特征表当前包含：

- `step_speed`
- `sway_frequency_hz`
- `step_length_asymmetry_ratio`
- `valid_frame_ratio`
- `mean_core_visibility`

快速起身规则首版：

- 输入：`urfd_pose_cleaned_frames.csv` 中的 `pelvis_y_smooth`、`timestamp_ms`、`core_visibility_mean`
- 规则：在 `0.4s` 到 `1.5s` 窗口内，髋部中心上移不少于 `0.05` 个画面高度，且上移速度不少于 `0.12` 个画面高度/秒
- 输出：`rapid_rise` Evidence，`current_value` 为起身时长秒数，`baseline_value` 默认为 `2.5s`

当前构建结果：

- 序列数：`70`
- 清洗后逐帧数据行数：`2813`
- 标签分布：`30` 条 `fall`，`40` 条 `adl`

## 当前边界

当前可以确认：

- 姿态关键点提取可运行
- 33 点 CSV 可导出
- URFD 可作为当前阶段主数据源
- 首版步态特征提取 pipeline 已可运行
- `rapid_rise` 正式规则首版已可运行
- 清洗后数据集和序列级特征表已生成

当前尚未完成：

- `trunk_sway`、`gait_instability` 的正式 Evidence 规则或模型
- 低照度、遮挡、出画条件下的稳定性验证
- Pre-VFall 的完整下载和实测
