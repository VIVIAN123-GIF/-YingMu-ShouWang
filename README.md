# “萤目守望”开发冻结方案

## 冻结信息

| 项目 | 内容 |
|---|---|
| 冻结版本 | Freeze v1.1 |
| 冻结日期 | 2026年7月22日 |
| 项目负责人 | 张薇 |
| 内部开发完成 | 2026年8月27日 |
| 最终交付准备完成 | 2026年8月31日 |
| 核心演示 | “张爷爷没有跌倒的第100天”黄金半分钟闭环 |

本目录是8月31日前研发、联调、实验和材料制作的统一执行依据。若其他文档与本冻结方案冲突，以本目录中的最新决策记录为准。

## 一句话目标

> 以跌倒风险为核心任务，完成“连续观测—个人基线—多时标融合—分级干预—风险回落”的可运行预警闭环；心理健康和诈骗风险只作为证据适配场景接入同一系统。

## 冻结文档

1. [范围与验收](./01-范围与验收.md)
2. [统一接口规范](./02-统一接口规范.md)
3. [风险状态机](./03-风险状态机.md)
4. [场景功能映射](./04-场景功能映射.md)
5. [人员任务看板](./05-人员任务看板.md)
6. [风险与决策日志](./06-风险与决策日志.md)
7. [单设备异地协作与实机管理](./07-单设备异地协作与实机管理.md)

关联主文档：

- [完整解决方案](../7.22解决方案.md)
- [三线融合叙事](../7.22三线融合叙事.md)
- [老师建议](../7.21老师建议.md)
- [初步分工（历史草案）](../初步分工.md)
- [交互与技术调研交付包](../交互调研/README.md)
- [飞书研发推进台账](../飞书台账/README.md)

## 冻结原则

- 跌倒主闭环优先级高于所有扩展功能；
- 心理、诈骗不得建设独立的记忆、状态机和预警后台；
- 算法模块只输出统一Evidence证据，不直接决定最终风险等级；
- 大模型只用于解释和报告，不参与红色风险最终判定；
- 唯一一台萤石C6c由张薇保管，跌倒使用实机，心理和诈骗使用明确标注的模拟回放；
- 远程成员通过授权接口、事件片段和回放开发，不共享张薇的萤石主账号；
- 8月27日后不增加功能，只修复阻塞性问题；
- 故事、页面、接口、日志和实验数据必须一一对应；
- 任何范围变更必须登记决策编号、负责人、工期影响和回退方案。

## 最终完成定义

只有同时满足以下条件，项目才算“开发完成”：

1. 实机、回放和Mock输入能够通过统一设备适配器进入系统；
2. 跌倒前兆Evidence能够进入统一风险引擎；
3. 系统至少完成一项已核验萤石资源的真实调用；语音或消息若未获开放能力，则展示失败日志和降级工具；
4. 干预后能够继续观察并完成风险回落；
5. 心理和诈骗证据能进入同一事件时间轴；
6. 全新环境可依据部署文档完成运行；
7. 核心指标有可复现实测结果；
8. PPT、视频、研究报告与实际系统一致。

## 变更流程

任何成员提出新增功能时，必须回答：

1. 是否直接服务跌倒主闭环？
2. 是否在8月27日前有明确负责人和验收方式？
3. 是否复用统一接口和状态机？
4. 删除什么现有任务来换取开发时间？

未登记在《风险与决策日志》中的新增功能，不进入最终版本。

---

## 赵勇：姿态 Demo 交付说明

本部分对应赵勇分支 `feature/zy/pose-demo` 的当前交付内容，仅说明 MediaPipe 姿态估计 Demo 与 33 个关键点提取阶段，不代表跌倒前兆算法已经完成。

当前会议状态应表述为：

> MediaPipe 官方姿态 Demo 已跑通，可以提取 33 个关键点；跌倒前兆特征、数据质量和 Evidence 生成仍待实现验证。

### 当前结论

- MediaPipe 官方 Pose Landmarker Demo 已跑通
- 可从视频或 RGB 图像序列中提取 33 个姿态关键点
- URFD 已完成下载和本地整理
- Pre-VFall 尚未完成下载，不作为当前阶段阻塞项

### 当前真实可运行环境

当前仓库内已验证可运行的环境为：

- Python `3.9.25`
- `mediapipe 0.10.21`
- `opencv-contrib-python 4.11.0.86`
- `numpy 1.26.4`

运行方式：

```powershell
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

环境验证命令：

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_setup.py
```

验收通过标志：

```text
PoseLandmarker initialization: OK
```

### 已完成脚本

- `scripts/download_pose_model.py`
- `scripts/verify_setup.py`
- `scripts/run_pose_demo.py`
- `scripts/download_datasets.py`
- `requirements.txt`

模型文件本地路径：

- `models/pose_landmarker_heavy.task`

### 数据集状态

#### URFD

URFD 当前状态：已完成下载和整理，可用于当前阶段 Demo 与后续步态特征提取。

本地目录：

- `data/raw/urfd/original/`
- `data/raw/urfd/extracted/`
- `data/raw/manifest.csv`

用途：

- 跑通姿态关键点提取
- 验证视频和 RGB 图像序列两类输入
- 后续生成步速、躯干摆动、步态不稳定等特征

官方地址：

- https://fenix.ur.edu.pl/~mkepski/ds/uf.html

#### Pre-VFall

Pre-VFall 当前状态：未完成下载。

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

### 运行命令

下载模型：

```powershell
.\.venv\Scripts\python.exe .\scripts\download_pose_model.py
```

下载 URFD：

```powershell
.\.venv\Scripts\python.exe .\scripts\download_datasets.py --dataset urfd --include-preview-mp4
```

对本地视频运行姿态估计：

```powershell
.\.venv\Scripts\python.exe .\scripts\run_pose_demo.py --input .\data\raw\urfd\samples\fall-01-cam0.mp4 --max-frames 60
```

对 RGB 图像序列运行姿态估计：

```powershell
.\.venv\Scripts\python.exe .\scripts\run_pose_demo.py --input .\data\raw\urfd\extracted\adl-01-cam0-rgb --max-frames 60
```

### 33 个关键点输出说明

输出目录：

- `outputs/demo/`

已验证输出：

- `fall-01-cam0_annotated.mp4`
- `fall-01-cam0_landmarks.csv`
- `adl-01-cam0-rgb_annotated.mp4`
- `adl-01-cam0-rgb_landmarks.csv`

关键点 CSV 字段固定为：

```text
source_video, frame_idx, timestamp_ms, landmark_id, x, y, z, world_x, world_y, world_z, visibility, presence
```

33 点验收方式：

- `landmark_id` 唯一值数量应为 `33`

输出样例：

```text
source_video=fall-01-cam0.mp4
frame_idx=1
timestamp_ms=33
landmark_id=0
x=0.6172115206718445
y=0.5502452850341797
z=-0.12100448459386826
world_x=0.3750496506690979
world_y=-0.3089500069618225
world_z=-0.41035938262939453
visibility=0.9982107877731323
presence=0.9975377321243286
```

### Evidence 样例

当前仓库还没有完整的跌倒前兆算法输出，以下 Evidence 为本阶段占位样例，用于说明后续接口结构和证据表达方式，不代表算法已经完成。

#### rapid_rise

```json
{
  "evidence_type": "rapid_rise",
  "source": "pose_demo_rule_stub",
  "video": "fall-01-cam0.mp4",
  "time_window_ms": [0, 2000],
  "score": 0.32,
  "status": "stub",
  "note": "当前仅完成姿态关键点提取，快速起身特征尚未正式建模。"
}
```

#### trunk_sway

```json
{
  "evidence_type": "trunk_sway",
  "source": "pose_demo_rule_stub",
  "video": "fall-01-cam0.mp4",
  "time_window_ms": [0, 2000],
  "score": 0.41,
  "status": "stub",
  "note": "当前仅完成躯干关键点可提取，左右摆动幅度阈值仍待验证。"
}
```

#### gait_instability

```json
{
  "evidence_type": "gait_instability",
  "source": "pose_demo_rule_stub",
  "video": "adl-01-cam0-rgb",
  "time_window_ms": [0, 2000],
  "score": 0.27,
  "status": "stub",
  "note": "当前仅完成步态关键点序列输出，步长差异比和步速波动规则仍待实现。"
}
```

### 当前失败场景说明

当前阶段已经确认以下风险或失败场景仍待解决：

- 低照度场景：人体边缘和四肢关键点更容易抖动或丢失
- 遮挡场景：手臂、腿部被家具或身体遮挡时，关键点稳定性下降
- 人物出画：当人物只剩半身或快速离开画面时，连续跟踪容易中断
- 视角变化大：非正侧视、俯拍或仰拍时，步态相关特征解释难度会上升
- 多人同时出现：当前脚本默认只处理 `num_poses=1` 的主目标

这些问题目前仅有现象判断，还没有形成完整降级策略。

### 当前边界

当前可以确认的结论：

- MediaPipe Pose Demo 可运行
- 33 个关键点可稳定导出为 CSV
- URFD 可作为当前步态特征提取的主数据来源

当前不能夸大表述为已完成的内容：

- 跌倒前兆识别算法
- `rapid_rise`、`trunk_sway`、`gait_instability` 的正式规则或模型
- 低照度、遮挡、出画条件下的稳定性验证
- Pre-VFall 的完整下载和实测

### 下一步

1. 基于 URFD 批量导出 33 点关键点序列
2. 实现 `rapid_rise`、`trunk_sway`、`gait_instability` 的初版规则
3. 形成真实 Evidence 输出，而不再使用 stub 样例
4. 再决定是否补充 Pre-VFall 作为扩展数据源
