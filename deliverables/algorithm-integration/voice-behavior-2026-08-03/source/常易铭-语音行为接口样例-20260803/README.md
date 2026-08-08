# 常易铭：语音与行为 Observation + Evidence 接口样例

交付日期：2026-08-03  
契约版本：Freeze v1.0  
用途：供后端验证 Observation/Evidence 入库、字段兼容、引用关系和幂等行为。

## 1. 交付范围

本包提供两组脱敏样例，每个JSON文件对应一次独立POST请求：

```text
voice/
  01-observation-transcript.json
  02-observation-keyword-count.json
  03-evidence-fraud-keyword.json
behavior/
  01-observation-baseline-range.json
  02-observation-current-range.json
  03-evidence-activity-range-decline.json
schemas/
  observation.schema.json
  evidence.schema.json
scripts/
  generate_samples.py
  submit_samples.py
validation/
  dry-run-log.json
  first-submit.json
  idempotent-submit.json
manifest.json
字段含义与生成方式.md
验收结果.md
```

语音组模拟一段合成录音回放，转写命中“保证收益、验证码、马上转账”三类高风险交互话术。它只表示需要核验的交互特征，不直接判断诈骗。

行为组模拟当前访问区域数由个人基线4个下降到2个。它只表示活动范围变化，不作心理疾病诊断。

## 2. 提交顺序

Evidence必须引用已入库的Observation，所以必须严格按`manifest.json`中的顺序提交：

1. 语音转写Observation；
2. 语音关键词数量Observation；
3. `fraud_keyword` Evidence；
4. 行为基线区域数Observation；
5. 行为当前区域数Observation；
6. `activity_range_decline` Evidence。

接口：

- Observation：`POST /api/v1/observations`
- Evidence：`POST /api/v1/evidence`

## 3. 自动生成

在本交付包根目录执行：

```powershell
python .\scripts\generate_samples.py
```

脚本会覆盖生成6个请求JSON并检查字段完整性、时区、0到1分数、Observation引用和来源继承关系。

## 4. 后端联调

先启动项目后端，再在本交付包根目录执行只读校验：

```powershell
python .\scripts\submit_samples.py --dry-run
```

真实提交：

```powershell
python .\scripts\submit_samples.py `
  --base-url http://127.0.0.1:8000 `
  --log-output .\submission-log.json
```

脚本只记录HTTP状态、`saved`和`idempotent`，不会把后端计算出的最终风险等级写入算法交付日志。

第一次提交通常返回HTTP 201和`saved: true`；以完全相同的JSON再次提交应返回HTTP 200和`idempotent: true`。同一ID若修改内容，后端应返回409冲突。

## 5. 边界说明

- 全部样例均为模拟或合成回放，不含真实老人、家庭、摄像机或录音数据；
- `source_mode`和`simulated`在每组Observation与Evidence中保持一致；
- Evidence必须引用本组中已经提交的Observation ID；
- `confidence`、`data_quality`和`severity`是接口联调值，尚未正式标定；
- 不包含GREEN/YELLOW/ORANGE/RED等最终风险等级；
- 不包含账号密钥、设备序列号、视频、音频或模型权重。

完整字段解释与实际Demo生成路径见`字段含义与生成方式.md`。

本机实际入库结果见`验收结果.md`和`validation/`中的脱敏日志。
