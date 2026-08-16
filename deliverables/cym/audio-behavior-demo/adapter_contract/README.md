# Worker 适配器交接说明

本目录提供两个独立入口。它们只调用 `src/behavior_adapter.py` 和
`src/audio_evidence.py` 的已有构造函数，不写数据库、不调用风险引擎、不输出
`risk_level`。

## 入口和配置

```ini
PYTHONPATH=deliverables/cym/audio-behavior-demo/src
YINGMU_TRAJECTORY_ADAPTER=adapters.trajectory_adapter:run
YINGMU_LANGUAGE_ADAPTER=adapters.language_adapter:run
```

两个入口均为：

```python
async def run(job: AlgorithmJob) -> AdapterBatch
```

`AlgorithmJob` 可以直接传 Python `dict`，也可以传
`adapters.contract.AlgorithmJob`。返回值是 JSON-compatible `dict`，顶层固定
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

依赖沿用 Demo 的 `requirements.txt`：行为入口需要 Python、OpenCV 和已有行为
模块；语言文本测试只需要 Python，真实音频还需要 `openai-whisper` 和系统
`FFmpeg`。缺少 Whisper 或 FFmpeg 时返回 `FAILED`，不会伪造转写。

## 输入格式

### TRAJECTORY

- `.json`：OpenCV 脱敏摘要，必须是摘要对象或 `{\"summary\": {...}}`；
- `.csv`：可选列 `person_count`、`motion_area`、`activity_level`、`x`、`y`，
  包装层聚合成已有行为摘要；
- `.mp4`、`.avi`、`.mov`、`.mkv`、`.webm`：包装层以 `--headless` 调用未修改
  的 `behavior_demo.py`，只读取临时脱敏摘要；
- 图片被拒绝，因为单张图片不能证明行为时间序列。

### LANGUAGE

- `.txt`：脱敏/测试转写，适合稳定的后端联调；原文只在进程内读取；
- `.wav`、`.mp3`、`.m4a`、`.flac`、`.ogg`、`.aac`、`.mp4`、`.webm`：调用已有
  Whisper，原始转写不写入日志、metadata、Evidence 或返回值；
- JSON 原始转写文件被拒绝，避免把原文作为持久化接口输入。

## 状态和边界

- `SUCCESS`：完成处理并产生至少一条 Evidence；
- `NO_EVIDENCE`：正常完成但本段没有风险 Evidence，允许 `evidences=[]`；
- `LOW_QUALITY`：行为检出比例低于 0.65，或音频质量低于 0.45；
- `FAILED`：输入、依赖或处理异常，且 `observations=[]`、`evidences=[]`，必须有
  标准 `AdapterError`。

语言回应写入 `diagnostics.resident_response`，其中 `intent` 只会是
`STABLE`、`HELP`、`UNCERTAIN`，`transcript_observation_id` 必须指向本批次的
`asr_transcript_redacted` Observation。无回应不直接判定跌倒。

同一 `job_id` 和同一输入窗口的 Observation/Evidence ID 由确定性命名生成，重试
不会随机变化。Evidence 不包含 `asset_id`，只通过 `observation_ids` 关联本批次
Observation。所有 Observation 继承 Job 的 `resident_id`、`asset_id`、
`source_mode`、`simulated`；Evidence 继承 `resident_id`、`source_mode`、
`simulated`。

## 示例文件

`algorithm_job.trajectory.json` 和 `algorithm_job.language.json` 是脱敏输入；
`trajectory_input.summary.json` 和 `language_input.transcript.txt` 是可直接运行
的测试输入。每个模块均提供：

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
