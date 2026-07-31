# “萤目守望”7.31统一验收证据索引

本索引汇总2026年7月31日模拟端到端里程碑的可复现证据，并严格区分`MOCK`模拟闭环与`LIVE_DEVICE`实机补验。设备完整三轮未完成不等于模拟端到端失败。

## 验收结论

- **7.31 模拟端到端目标：PASS**
- **后端闭环：3/3 PASS**
- **前端 API 闭环：3/3 PASS**
- **设备状态：3/3 SUCCESS**
- **设备抓图：2/3 SUCCESS**
- **ezopen临时地址：已有1次实机成功**
- **设备完整三轮：INCOMPLETE，不阻塞模拟端到端里程碑**
- **HLS、实际视频播放、真实语音：未验证**

模拟闭环使用`source_mode=MOCK`、`simulated=true`和`mock_voice`。设备记录只证明对应开放平台接口在记录时的实际结果，不把状态、抓图或一次ezopen地址成功外推为连续视频、HLS或语音能力。

## 一、后端三轮模拟闭环

- [三轮最终摘要](../e2e-2026-07-31/final-summary.json)：`passed=true`、`consistent=true`。
- 每轮摘要：[第1轮](../e2e-2026-07-31/run-1/summary.json)、[第2轮](../e2e-2026-07-31/run-2/summary.json)、[第3轮](../e2e-2026-07-31/run-3/summary.json)。
- RuleTrace：[第1轮](../e2e-2026-07-31/run-1/07-rule-traces.json)、[第2轮](../e2e-2026-07-31/run-2/07-rule-traces.json)、[第3轮](../e2e-2026-07-31/run-3/07-rule-traces.json)。
- 状态转移：[第1轮](../e2e-2026-07-31/run-1/08-state-transitions.json)、[第2轮](../e2e-2026-07-31/run-2/08-state-transitions.json)、[第3轮](../e2e-2026-07-31/run-3/08-state-transitions.json)。
- InterventionResult位于每轮的[干预响应](../e2e-2026-07-31/run-1/03-intervention-response.json)和[最终事件详情](../e2e-2026-07-31/run-1/06-final-event-detail.json)中；第2、3轮结构一致。

固定语义链为`GREEN → ORANGE/INTERVENING → OBSERVING → GREEN/RESOLVED`，匹配`R-FALL-01/02/04/05`，最终`risk_after=0.24`。

## 二、前端API三轮闭环

- [验收说明与复现命令](../frontend-api-2026-07-31/README.md)。
- 每轮摘要：[第1轮](../frontend-api-2026-07-31/run-1/summary.json)、[第2轮](../frontend-api-2026-07-31/run-2/summary.json)、[第3轮](../frontend-api-2026-07-31/run-3/summary.json)。
- 每轮均保存`INTERVENING`、`OBSERVING`、`RESOLVED`三张截图：[第1轮截图](../frontend-api-2026-07-31/run-1/01-intervening.png)、[第2轮截图](../frontend-api-2026-07-31/run-2/02-observing.png)、[第3轮截图](../frontend-api-2026-07-31/run-3/03-resolved-trace.png)。
- 前端证据对象示例：[RuleTrace](../frontend-api-2026-07-31/run-1/rule-traces.json)、[状态转移](../frontend-api-2026-07-31/run-1/state-transitions.json)、[InterventionResult](../frontend-api-2026-07-31/run-1/intervention-result.json)。
- [录像清单、大小与SHA-256](../frontend-api-2026-07-31/video-manifest.json)。三轮WebM保存在本地/飞书，不进入Git仓库。

`data_mode=api`表示页面通过真实HTTP访问FastAPI；后端工具与Evidence仍明确标记为模拟数据，不宣称真实设备端到端。

## 三、萤石实机补验

- 最新三轮：[第1轮](../backend-2026-07-31/ezviz-live-validation-run-1.json)、[第2轮](../backend-2026-07-31/ezviz-live-validation-run-2.json)、[第3轮](../backend-2026-07-31/ezviz-live-validation-run-3.json)、[汇总](../backend-2026-07-31/ezviz-live-validation-summary.json)。
- 配置验证码前的归档：[第1轮](../backend-2026-07-31/ezviz-live-validation-pre-code/run-1.json)、[第2轮](../backend-2026-07-31/ezviz-live-validation-pre-code/run-2.json)、[第3轮](../backend-2026-07-31/ezviz-live-validation-pre-code/run-3.json)、[汇总](../backend-2026-07-31/ezviz-live-validation-pre-code/summary.json)。
- 仅尝试加密HLS的归档：[第1轮](../backend-2026-07-31/ezviz-live-validation-with-code-hls/run-1.json)、[第2轮](../backend-2026-07-31/ezviz-live-validation-with-code-hls/run-2.json)、[第3轮](../backend-2026-07-31/ezviz-live-validation-with-code-hls/run-3.json)、[汇总](../backend-2026-07-31/ezviz-live-validation-with-code-hls/summary.json)。
- [开放平台能力矩阵](../../docs/萤石对接阶段文档/阶段二_萤石开放平台能力矩阵文档.md)。
- [异常及未完成清单](../backend-2026-07-31/exceptions-and-todos.md)。
- [设备补验脚本](../../scripts/validate_ezviz_live.py)与[脱敏/离线/回退测试](../../tests/test_validate_ezviz_live.py)。

最新三轮中设备状态3/3成功，抓图2/3成功，完整“状态—抓图—临时地址”链路仅1/3成功且`consistent=false`。HLS遇到60019后，第1轮使用仅存于本地环境的验证码回退ezopen并取得一次临时地址；报告不保存验证码、图片或地址。

## 四、算法Evidence与行为统计

### 赵勇：跌倒Evidence

- [7类跌倒Evidence批量包](../zy/pose-demo/evidence/fall_evidence_batch.json)。
- [黄金半分钟Evidence包](../zy/pose-demo/integration/golden_30s_fall_evidence.json)及[联调说明](../zy/pose-demo/integration/README.md)。
- [姿态Demo、规则基线和当前边界](../zy/pose-demo/README.md)。

算法模块只输出Freeze v1.0 Evidence，不直接输出最终风险等级。

### 常易铭：活动范围与房间转换

- [活动范围与访客MOCK统计](../cym/audio-behavior-demo/samples/mock_behavior_statistics.json)：个人基线4个区域、当前2个区域。
- [行为Observation/Evidence联调包](../cym/audio-behavior-demo/samples/behavior_evidence_bundle.example.json)。
- [确定性MOCK房间转换统计](../cym/audio-behavior-demo/samples/mock_region_transition_statistics.json)：`doorway → living_room → corridor`，访问3个区域、发生2次转换。
- [区域跟踪实现](../cym/audio-behavior-demo/src/regions.py)与[确定性测试](../cym/audio-behavior-demo/tests/test_regions.py)。

房间转换样例由确定性点序列生成，不包含真人视频、摄像头实景或真实居家监测数据，不能用于证明现实识别准确率。

## 五、回归命令与结果

设备补验PR合并后，基于`main@1f05705`在一次性干净worktree中执行：

```powershell
python -m pytest -q
python scripts/run_full_e2e_acceptance.py --runs 3
cd frontend
npm ci
npm test -- --reporter=dot
npm run build
```

结果：

| 检查 | 结果 |
|---|---|
| Python完整测试 | `65 passed` |
| 后端模拟闭环 | `3/3 PASS` |
| 前端Vitest | `9 test files / 36 tests passed` |
| Vite生产构建 | `PASS`，2315模块完成转换 |

构建存在依赖弃用提示和单个大于600 kB的分块警告，但没有测试或构建失败，不阻塞7.31模拟端到端里程碑。

## 六、已知失败与降级边界

| 项目 | 当前结论 | 降级或后续动作 |
|---|---|---|
| 设备完整三轮 | `INCOMPLETE`，仅1/3完整成功 | 保留全部成功与超时记录；不影响模拟端到端PASS |
| HLS | 未成功，观察到60019“加密已开启” | 仅在本地有验证码时尝试ezopen；不宣称HLS成功 |
| 实际视频播放 | 未验证 | 演示继续使用授权片段、截图或明确标记的回放/Mock |
| 真实语音/对讲 | 未验证 | 使用`mock_voice`并写入InterventionResult |
| WebHook真实回调 | 未验证 | 当前只有契约、签名、时效、幂等和脱敏单元测试 |
| 抓图稳定性 | 2/3成功，1轮超时 | 保留超时，不以重跑删除失败证据 |

## 最终口径

7.31验收证明的是：统一四对象、规则引擎、后端恢复闭环和前端API展示可在明确标注的模拟模式下连续复现三次，因此**模拟端到端目标为PASS**。设备补验提供了状态、抓图和一次ezopen临时地址的真实证据，但完整三轮仍为`INCOMPLETE`；两者必须分开陈述。
