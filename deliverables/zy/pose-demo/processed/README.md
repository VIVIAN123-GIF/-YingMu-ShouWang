# 步态特征提取结果

本目录存放 2026-07-26 基于 URFD 生成的清洗后数据集和序列级特征表。

## 文件说明

- `urfd_pose_cleaned_frames.csv`
  清洗后的逐帧数据，保留姿态关键派生量和平滑结果。

- `urfd_gait_features.csv`
  按序列汇总后的步态特征表，可直接用于后续规则验证或建模。

- `build_summary.json`
  本次构建的摘要信息，包括序列数、逐帧数据行数、标签分布和特征列。

## 当前构建参数

- 数据源：URFD
- 视角：cam0
- 抽帧：frame_stride=2
- 特征：
  - `step_speed`
  - `sway_frequency_hz`
  - `step_length_asymmetry_ratio`

## 当前结果摘要

- 序列数：70
- 清洗后逐帧数据行数：2813
- fall：30
- adl：40
