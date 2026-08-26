# 三参与者最终实验执行包

本目录用于完成3名健康成年参与者、每人32段、共96段的受控实验。实验只验证工程可行性和初步跨参与者适配能力，不代表老年人群临床表现或大规模泛化能力。

## 安全边界

- 只模拟快速起身、受控摇晃、慢速小步和步幅不对称，不实施真实跌倒。
- 保护人员位于镜头外但伸手可及；出现头晕、真实失衡、碰撞、椅子移动或必须搀扶时立即停止。
- 中止片段标记`ABORTED`并保留原因，不计入96段；使用新的`clip_id`补拍同一`planned_slot_id`。
- 原始视频、签字授权、设备凭证和P03锁定目录不得提交Git。

## 数据角色

| 参与者 | 数据集 | 用途 | 是否允许调参 |
|---|---|---|---|
| P01 | CALIBRATION | 建立首版个人基线并校准规则 | 允许，必须记日志 |
| P02 | VALIDATION | 独立验证候选规则 | 全部处理后最多一次 |
| P03 | TEST | 最终盲测和主报告指标 | 禁止 |

每人第一天拍8段正常基线，第二个不同日期拍24段评测场景。每人的第一条`POS_RAPID_RISE_SWAY`使用115秒黄金闭环协议。

## 目录约定

```text
experiments/three-participant/
├─ templates/                 可提交的空白模板
├─ private/                   原始视频，Git忽略
│  ├─ P01/
│  ├─ P02/
│  └─ P03/
├─ signed-consent/            签字原件，Git忽略
├─ TEST_LOCKED/               P03锁定副本，Git忽略
└─ results/                   脱敏统计结果
```

## 执行顺序

1. 打印并签署`templates/参与者授权与安全确认.md`，每人一份。
2. 按`templates/现场拍摄检查表.md`固定机位并拍摄三段小样。
3. 填写`templates/capture-manifest.csv`，完成后运行严格校验：

```powershell
python scripts/three_participant_experiment.py validate-manifest `
  --manifest experiments/three-participant/templates/capture-manifest.csv `
  --stage captured `
  --media-root experiments/three-participant/private `
  --report experiments/three-participant/results/capture-validation.json
```

4. 完成P03拍摄后立即锁定，锁定前不得运行P03算法：

```powershell
python scripts/three_participant_experiment.py lock-test `
  --manifest experiments/three-participant/templates/capture-manifest.csv `
  --media-root experiments/three-participant/private `
  --output-dir experiments/three-participant/TEST_LOCKED
```

5. 处理P01，记录每次阈值变化；再一次性处理P02。若调整一次规则，重新处理P01和P02全部48段。
6. 在Git工作区干净、规则和模型确定后冻结：

```powershell
python scripts/three_participant_experiment.py freeze-rules `
  --lock-file experiments/three-participant/TEST_LOCKED/test-lock.json `
  --ruleset contracts/v1/rulesets/ruleset-v1.0.json `
  --model models/pose_landmarker_heavy.task `
  --output experiments/three-participant/results/rule-freeze.json
```

7. 冻结成功后才允许处理P03。生成结果录入表：

```powershell
python scripts/three_participant_experiment.py generate-predictions `
  --manifest experiments/three-participant/templates/capture-manifest.csv `
  --output experiments/three-participant/results/predictions.csv
```

8. 填完预测表后生成正式指标和四组消融：

```powershell
python scripts/three_participant_experiment.py analyze `
  --manifest experiments/three-participant/templates/capture-manifest.csv `
  --predictions experiments/three-participant/results/predictions.csv `
  --lock-file experiments/three-participant/TEST_LOCKED/test-lock.json `
  --freeze-file experiments/three-participant/results/rule-freeze.json `
  --output-dir experiments/three-participant/results/final
```

9. 完成三次4小时正常运行，填写`templates/stability-runs.csv`并汇总：

```powershell
python scripts/three_participant_experiment.py analyze-stability `
  --input experiments/three-participant/templates/stability-runs.csv `
  --output experiments/three-participant/results/stability-summary.json
```

10. 根据`templates/`中的JSON模板补齐三个脱敏汇总：

- `results/urfd-results.json`：URFD公开数据复核，固定标记`PUBLIC_DATASET`，不得与自采指标混算；
- `results/golden-loop-results.json`：P01、P02、P03各一次115秒黄金闭环复现；
- `results/authorization-summary.json`：只保存参与者编号和授权完成状态，不保存姓名、签字或扫描原件。

任何命令返回`FAIL`或`INCOMPLETE`时不得把对应结果写成正式通过。

## 原始视频初筛

原始文件名无场景信息、存在重拍或参与者目录放错时，先运行标签盲态清点。该步骤只做媒体完整性、人工观察和文件整理，不运行P03姿态或风险推理，也不根据画面自动生成正式真值。

```powershell
python scripts/review_three_participant_videos.py audit `
  --input "<仓库外授权素材包>" `
  --output-dir outputs\three-participant-review
```

输出目录中的`review-index.html`用于逐段确认参与者、`scenario_id`和有效性；`video-confirmation.csv`是等价的机器可读确认表。拍摄同学确认后运行：

```powershell
python scripts/review_three_participant_videos.py finalize `
  --confirmation outputs\three-participant-review\video-confirmation-reviewed.csv `
  --output-dir outputs\three-participant-review
```

`capture-manifest.draft.csv`只有在96个槽位全部真实匹配、人工事件区间和授权编号完整，并通过`three_participant_experiment.py validate-manifest --stage captured`后，才能用于P03锁定。冒烟小样和未选重拍片段始终保留在审计清单中，不计入96段。
