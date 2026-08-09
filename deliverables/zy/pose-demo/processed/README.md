# 步态特征提取结果

本目录存放 2026-07-26 基于 URFD 生成的清洗后数据集和序列级特征表。

## 文件说明

- `urfd_pose_cleaned_frames.csv`
  清洗后的逐帧数据，保留姿态关键派生量和平滑结果。

- `urfd_gait_features.csv`
  按序列汇总后的步态特征表，可直接用于后续规则验证或建模。

- `build_summary.json`
  本次构建的摘要信息，包括序列数、逐帧数据行数、标签分布和特征列。

快速起身 Evidence 由上级目录脚本生成：

- `../scripts/build_rapid_rise_evidence.py`
  基于清洗后的逐帧姿态数据检测髋部中心快速上移窗口，并输出 `../evidence/rapid_rise.json`。
- `../scripts/build_fall_evidence_package.py`
  基于逐帧姿态数据和序列级特征表生成 7 类跌倒 Evidence、数据质量证据和黄金半分钟联调包。

## 当前构建参数

- 数据源：URFD
- 视角：cam0
- 抽帧：frame_stride=2
- 特征：
  - `step_speed`
  - `sway_frequency_hz`
  - `step_length_asymmetry_ratio`

## 快速起身规则

- 规则名：`rapid-rise-rule-v1`
- 输入字段：`pelvis_y_smooth`、`timestamp_ms`、`core_visibility_mean`
- 判定窗口：0.4s 到 1.5s
- 最小上移量：0.05 个画面高度
- 最小上移速度：0.12 个画面高度/秒
- 默认起身时长基线：2.5s

## 数据质量与联调

- `valid_frame_ratio` 用于判断姿态跟踪有效帧比例
- `mean_core_visibility` 用于 Evidence 的 `data_quality`
- 当 `valid_frame_ratio` 低于默认阈值 0.65 时生成 `tracking_lost`
- `../integration/golden_30s_fall_evidence.json` 可用于 8月7 与智能体接口联调

## 当前结果摘要

- 序列数：70
- 清洗后逐帧数据行数：2813
- fall：30
- adl：40
