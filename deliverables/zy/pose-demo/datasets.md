# 数据集状态

## URFD

当前状态：已完成下载和本地整理，可用于当前阶段 Demo 与后续步态特征提取。

用途：

- 跑通姿态关键点提取
- 验证视频和 RGB 图像序列两类输入
- 后续生成步速、躯干摆动、步态不稳定等特征

官方地址：

- https://fenix.ur.edu.pl/~mkepski/ds/uf.html

本地目录配置：

- `data/raw/urfd/original/`
- `data/raw/urfd/extracted/`
- `data/raw/manifest.csv`
- `deliverables/zy/pose-demo/processed/`

当前已生成的派生数据：

- `processed/urfd_pose_cleaned_frames.csv`
- `processed/urfd_gait_features.csv`
- `processed/build_summary.json`

当前构建口径：

- 仅处理 `cam0`
- `frame_stride=2`

## Pre-VFall

当前状态：未完成下载。

原因：

- 官方压缩包约 `21 GB`
- 下载过程中磁盘空间不足
- 当前阶段已优先保证 URFD 主线任务可运行

用途：

- 更适合后续补充“跌倒前早期征兆”相关验证
- 不是当前 33 点提取验收的硬前置条件

官方地址：

- https://doi.org/10.6084/m9.figshare.26488216.v3

说明：

- 原始数据集不上传 GitHub
- 后续如有更大容量磁盘，再补下 Pre-VFall
