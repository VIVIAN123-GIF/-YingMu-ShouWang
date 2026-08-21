# Worker 适配器交接说明

本目录提供两个独立入口。TRAJECTORY 调用已有行为构造函数，LANGUAGE 只把上游
脱敏结果转换为冻结 Observation/Evidence，不写数据库、不调用风险引擎、不输出
`risk_level`。公共合同唯一来源是仓库根目录的
`contracts/v1/algorithm.py`；适配器不再定义第二套 `AlgorithmJob` 或
`AdapterBatch`。

## 入口和配置

```ini
PYTHONPATH=.;deliverables/cym/audio-behavior-demo/src
YINGMU_TRAJECTORY_ADAPTER=adapters.trajectory_adapter:run
YINGMU_LANGUAGE_ADAPTER=adapters.language_adapter:run
```

两个入口均为：

```python
async def run(job: AlgorithmJob) -> AdapterBatch
```

入口签名严格为：

```python
from contracts.v1.algorithm import AdapterBatch, AlgorithmJob

async def run(job: AlgorithmJob) -> AdapterBatch:
    ...
```

后端注册器传入仓库公共 `AlgorithmJob`，入口返回仓库公共 `AdapterBatch`。
顶层固定
包含 `schema_version=adapter-batch/1.0`、`job_id`、`module`、
`adapter_version`、`status`、`started_at`、`completed_at`、`observations`、
`evidences`、`diagnostics` 和 `error`。

## 运行方式

在仓库根目录执行：

```powershell
$env:PYTHONPATH = "$PWD/deliverables/cym/audio-behavior-demo/src"
python -c "import asyncio,json; from adapters.trajectory_adapter import run; j=json.load(open('deliverables/cym/audio-behavior-demo/adapter_contract/algorithm_job.trajectory.json',encoding='utf-8')); print(json.dumps(asyncio.run(run(j)),ensure_ascii=False,indent=2))"
python -c "import asyncio,json; from adapters.language_adapter import run; j=json.load(open('deliverables/cym/audio-behavior-demo/adapter_contract/algorithm_job.language.json',encoding='utf-8')); print(json.dumps(asyncio.run(run(j)),ensure_ascii=False,indent=2))"
```

依赖沿用 Demo 的 `requirements.txt`，并要求从仓库根目录启动。行为入口需要
Python、OpenCV 和已有行为模块；LANGUAGE 入口不运行 Whisper，也不读取原始音频，
只消费上游已经脱敏的结构化语言分析结果。

## 输入格式

### TRAJECTORY

- `.json`：OpenCV 脱敏摘要，必须是摘要对象或 `{\"summary\": {...}}`；
- `.json` 也可使用 `{\"summary\": {...}, \"trend\": {\"days\": [...]}}`，
  将当前视频摘要与后端日聚合数据一起适配；趋势的任务、住户、资产和来源字段
  统一继承 `AlgorithmJob`；
- `.csv`：可选列 `person_count`、`motion_area`、`activity_level`、`x`、`y`，
  包装层聚合成已有行为摘要；
- `.mp4`、`.avi`、`.mov`、`.mkv`、`.webm`：包装层以 `--headless` 调用未修改
  的 `behavior_demo.py`，只读取临时脱敏摘要；
- 图片被拒绝，因为单张图片不能证明行为时间序列。

### LANGUAGE

只接受符合 `language-analysis/1.0` 的 `.json`：

```json
{
  "schema_version": "language-analysis/1.0",
  "keyword_groups": ["guaranteed_return"],
  "resident_response": "resident_response_help",
  "audio_quality": 0.92,
  "processing_source": "WHISPER_REDACTED",
  "model_version": "whisper-tiny-local",
  "language": "Chinese"
}
```

- `keyword_groups` 只能使用冻结标签，不接收逐字转写；
- `resident_response` 只能为 `resident_response_help`、
  `resident_response_stable` 或 `null`；
- `.wav/.mp3`、原始转写 `.txt`、包含 `raw_transcript`、音频路径、媒体路径或
  平台凭证字段的 JSON 一律返回 `FAILED`。

## 状态和边界

- `SUCCESS`：完成处理并产生至少一条 Evidence；
- `NO_EVIDENCE`：正常完成但本段没有风险 Evidence，必须保留至少一条 Observation，且 `evidences=[]`；
- `LOW_QUALITY`：行为检出比例低于 0.65，或音频质量低于 0.45；
- `FAILED`：输入、依赖或处理异常，且 `observations=[]`、`evidences=[]`，必须有
  标准 `AdapterError`。

语言回应写入 AdapterBatch 顶层 `resident_response_candidate`。包装层只会把
`resident_response_help` 映射为公共合同的 `HELP`，把
`resident_response_stable` 映射为 `STABLE`；其他情况不输出候选，不输出
`UNCERTAIN`。`transcript_observation_id` 指向本批次的脱敏摘要 Observation。
无回应不直接判定跌倒。

同一 `job_id` 和同一输入窗口的 Observation/Evidence ID 由确定性命名生成，重试
不会随机变化。Evidence 不包含 `asset_id`，只通过 `observation_ids` 关联本批次
Observation。所有 Observation 继承 Job 的 `resident_id`、`asset_id`、
`source_mode`、`simulated`；Evidence 继承 `resident_id`、`source_mode`、
`simulated`。

`request_id` 不属于算法合同，算法不会调用 AgentExplanation 或大模型。相同事件
版本的稳定 `request_id`、已完成解释复用和“重复查询不重复调用模型”由后端 Agent
作业层负责；算法侧只保证稳定 `job_id` 对应稳定 Observation/Evidence ID。

TRAJECTORY 的边界是：`unusual_pacing` 可由单段视频的区域往返序列产生；
`activity_range_decline`、`room_transition_decline` 必须依赖至少 7 天稳定个人基线，
不能由单段视频直接推断。日聚合数据应由后端生成后通过 `trend.days` 传入。

视频入口保持原始宽高比并分别输出 HOG `detection_quality` 和 HOG+KCF 短时
`tracking_quality`；KCF 最多桥接12帧，质量门槛仍为 `0.65`。固定机位视频必须
解析匹配 `scene_config_id` 的区域标定，缺失或摄像头位置不一致时返回
`FAILED/SCENE_CONFIG_MISSING` 或 `FAILED/SCENE_CONFIG_MISMATCH`，不猜测区域。

## 示例文件

`algorithm_job.trajectory.json` 和 `algorithm_job.language.json` 是脱敏输入；
`trajectory_input.summary.json`、`trajectory_input.trends.json` 和
`language_input.redacted.json` 是可直接运行的测试输入。旧的
`language_input.transcript.txt` 已禁用，仅保留迁移提示。每个模块均提供：

```text
adapter_batch.<module>.success.json
adapter_batch.<module>.no_evidence.json
adapter_batch.<module>.low_quality.json
adapter_batch.<module>.failed.json
```

自动化验证位于 `../tests/test_adapters.py`，运行：

```powershell
python -m unittest discover -s deliverables/cym/audio-behavior-demo/tests -v
```
