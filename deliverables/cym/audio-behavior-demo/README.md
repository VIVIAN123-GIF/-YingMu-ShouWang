# 语音与行为算法最小Demo

| 项目 | 内容 |
|---|---|
| 负责人 | 常易铭 |
| 更新日期 | 2026年8月14日 |
| 分支 | `feature/cym/audio-behavior-demo` |
| 当前状态 | 已完成语音/行为/趋势适配器、后端样例及合成来源验收；实景长期数据和正式阈值仍待统一素材验证 |

## 1. 项目边界

本目录验证两个最小链路：

1. 经授权的本地音频通过Whisper转成中文文本；
2. 摄像头或本地MP4通过OpenCV生成人员框、活动量和人物中心轨迹。

本模块只生成感知结果和Evidence，不直接输出GREEN、YELLOW、ORANGE或RED风险等级，也不作诈骗或心理疾病诊断。

当前公开验收使用TTS合成音频、移动图形MP4和MOCK统计。它们只验证处理链路、契约和接口，不是实际老人音频/行为连续监测。来源分类与允许表述见`docs/8月7日合成音频与行为验收说明.md`。

### 1.1 真实视频检测边界

视频分析保持原始宽高比，并在 `640x480` 画布中加黑边，避免将 C6c 常见的
16:9 画面拉伸为4:3。HOG `detection_quality` 与 HOG 加短时 KCF 的
`tracking_quality` 分开记录；KCF 只在已确认的 HOG 框后最多桥接12帧，质量门槛
仍为 `0.65`，不会把长期失踪帧伪装成检测结果。

固定机位视频必须解析 `AlgorithmJob.scene_config_id` 对应的区域标定。默认从
`scene_configs/<scene_config_id>.json` 读取，也可用 `YINGMU_SCENE_CONFIG_DIR`
指向 Worker 的只读目录。配置的 `scene_config_id` 和 `camera_position_id`
必须与 Job 一致；缺失或错配时返回 `SCENE_CONFIG_MISSING` 或
`SCENE_CONFIG_MISMATCH`。区域切换至少连续3次更新且持续0.4秒才确认，避免边界
抖动制造虚假 `unusual_pacing`。

## 2. 7月25日复现反馈修复

- `behavior_demo.py`现在同时支持摄像头编号和本地MP4；
- 新增`--headless`、`--max-frames`、`--max-seconds`和JSON摘要；
- MOG2只分析未绘制的原始帧，人体框、文字和轨迹不会污染运动区域；
- `camera_test.py`支持自动退出；
- 三条Evidence由代码构造并进行Freeze v1.0校验；
- 7月25日新增9项单元测试，覆盖Evidence错误和分析/绘制分离；
- Whisper新增`--check`，FFmpeg缺失时会给出明确提示；
- 新增不含人物的MP4链路测试视频生成器；
- 新增本地合成测试语音脚本，不提交私人录音。

## 3. 文件结构

```text
.
├─ README.md
├─ requirements.txt
├─ src/
│  ├─ whisper_demo.py
│  ├─ camera_test.py
│  ├─ behavior_demo.py
│  ├─ regions.py
│  ├─ behavior_evidence.py
│  ├─ behavior_adapter.py
│  ├─ generate_behavior_bundle.py
│  ├─ audio_evidence.py
│  ├─ generate_audio_bundle.py
│  ├─ trend_analysis.py
│  ├─ generate_trend_samples.py
│  ├─ observation.py
│  ├─ evidence.py
│  ├─ generate_evidence_samples.py
│  ├─ generate_behavior_evidence.py
│  ├─ submit_to_backend.py
│  └─ generate_trend_samples.py
├─ scripts/
│  ├─ generate_test_video.py
│  └─ generate_test_audio.ps1
├─ tests/
│  ├─ test_behavior.py
│  ├─ test_behavior_adapter.py
│  ├─ test_regions.py
│  ├─ test_behavior_evidence.py
│  ├─ test_backend_submission.py
│  ├─ test_trend_analysis.py
│  ├─ test_evidence.py
│  ├─ test_observation.py
│  ├─ test_whisper_demo.py
│  ├─ test_audio_evidence.py
│  ├─ test_behavior_adapter.py
│  └─ test_trend_analysis.py
├─ samples/
│  ├─ evidence_samples.json
│  ├─ regions.example.json
│  ├─ mock_behavior_statistics.json
│  ├─ mock_daily_activity.json
│  ├─ audio_quality_good.json
│  ├─ audio_quality_low.json
│  ├─ asset-c6c-golden.example.json
│  ├─ audio_bundle.example.json
│  ├─ behavior_bundle.c6c-replay.example.json
│  ├─ trend_evidence_bundle.example.json
│  ├─ behavior_evidence_bundle.example.json
│  ├─ mock_daily_activity.json
│  ├─ trend_evidence_bundle.example.json
│  ├─ test_scam_script.txt
│  └─ test_scam_transcript.txt
├─ logs/
│  ├─ behavior_test_20260724.md
│  ├─ whisper_test_20260725.json
│  ├─ reproduction_fix_20260725.md
│  ├─ trend_backend_submission_20260806.json
│  └─ synthetic_acceptance_20260807.json
└─ docs/
   ├─ 常易铭-7月24日调研交付.md
   ├─ 脱敏测试素材说明.md
   ├─ 降级规则.md
   ├─ 7月31日前任务拆分.md
   ├─ 8月7日前趋势交付.md
   ├─ 8月7日合成音频与行为验收说明.md
   └─ 8.14后常易铭-后端联调交付.md
```

原始录音、人物视频、Whisper模型、`.venv`、`output`和缓存不进入Git。

## 4. 环境安装

已验证环境：

- Windows PowerShell；
- Python 3.13.14；
- FFmpeg 8.1.2；
- `openai-whisper` 20250625；
- `opencv-contrib-python` 5.0.0.93；
- `torch` 2.13.0；
- `numpy` 2.4.6。

安装Python依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

检查Whisper和FFmpeg：

```powershell
python .\src\whisper_demo.py --check
```

如果没有FFmpeg，可尝试：

```powershell
winget install --id Gyan.FFmpeg -e
```

安装后重新打开PowerShell，再运行`ffmpeg -version`和上述`--check`命令。

## 5. 无摄像头自动复现

### 5.1 运行单元测试

```powershell
python -m unittest discover -s .\tests -v
```

预期：全部测试`OK`，其中Observation样例还会通过仓库
`contracts.v1.models.Observation`官方模型校验。

### 5.2 生成本地MP4链路测试视频

```powershell
python .\scripts\generate_test_video.py `
  --output .\output\smoke.mp4 `
  --seconds 4 `
  --fps 15
```

该视频只有移动圆点，不包含人物，仅用于验证MP4读取、运动分析、EOF和自动退出。它不能用于证明HOG人物检测效果。

### 5.3 无窗口处理完整MP4

```powershell
python .\src\behavior_demo.py `
  --input .\output\smoke.mp4 `
  --headless `
  --summary-output .\output\behavior_summary.json `
  --observation-output .\output\behavior_observations.json `
  --resident-id resident-001 `
  --asset-id asset-smoke-0001 `
  --simulated
```

预期摘要关键字段：

```json
{
  "input_type": "VIDEO",
  "source_mode": "RECORDED_REPLAY",
  "simulated": true,
  "frames_processed": 60,
  "stop_reason": "video_eof",
  "threshold_status": "DEMO_UNCALIBRATED"
}
```

### 5.4 验证帧数自动退出

```powershell
python .\src\behavior_demo.py `
  --input .\output\smoke.mp4 `
  --headless `
  --max-frames 30 `
  --summary-output .\output\behavior_30_frames.json `
  --simulated
```

预期：`frames_processed`为30，`stop_reason`为`max_frames`。

### 5.5 自动输出Observation

提供`--observation-output`后，程序会在一次运行结束时自动输出6条
Freeze v1.0 Observation，包括最大人数、人员检出帧比例、主要活动等级、
最大运动面积、轨迹点数和累计像素距离。

当前`confidence`和`data_quality`仍是明确标记为
`DEMO_UNCALIBRATED`的联调值，不代表正式准确率。Observation不输出最终风险等级。

## 6. 摄像头复现

自动读取摄像头5秒，不显示窗口：

```powershell
python .\src\camera_test.py --headless --max-seconds 5
```

显示摄像头行为Demo，最多运行30秒，也可以按`q`提前退出：

```powershell
python .\src\behavior_demo.py --input 0 --max-seconds 30
```

完整、直立、距离约2—3米的人体更容易被HOG检测。近距离、截断、遮挡和非直立姿态仍可能漏检。

### 6.1 人工区域、进入/离开和统计

先按实际画面修改`samples/regions.example.json`中的多边形坐标，然后运行：

```powershell
python .\src\behavior_demo.py `
  --input 0 `
  --max-seconds 30 `
  --region-config .\samples\regions.example.json `
  --region-events-output .\output\region_events.json `
  --statistics-output .\output\region_statistics.json `
  --summary-output .\output\region_summary.json `
  --observation-output .\output\region_observations.json
```

画面会显示门口、客厅和走廊多边形，以及最大HOG人体框中心所在区域。程序输出：

- `ENTER`/`EXIT`及本次停留秒数；
- 访问过的区域数和顺序；
- 每个区域累计停留秒数；
- 区域转换总数及`doorway->living_room`形式的明细；
- 10条行为Observation，其中新增区域数、转换数、最长停留和访问顺序。

录像使用帧号/FPS计算相对时间，因此同一录像可得到一致统计。HOG短暂漏检时不会立刻判断离开；程序结束时才关闭最后一个停留区间。像素轨迹不解释为现实米数。

## 7. Whisper复现

### 7.1 生成无隐私的本地合成音频

Windows PowerShell可执行：

```powershell
& .\scripts\generate_test_audio.ps1
```

输出为`output\synthetic_test.wav`。它读取`samples\test_scam_script.txt`并调用Windows本地语音合成，不包含真人录音；发音效果取决于本机语音包。

该文件必须使用`source_mode: RECORDED_REPLAY`和`simulated: true`。它只用于合成文件回放验收，不得描述为实时收音或真实老人音频监测。

### 7.2 执行转写

```powershell
python .\src\whisper_demo.py .\output\synthetic_test.wav `
  --model tiny `
  --language Chinese `
  --output-dir .\output `
  --observation-output .\output\audio_observations.json `
  --bundle-output .\output\audio_bundle.json `
  --resident-id resident-001 `
  --asset-id asset-synthetic-audio-0001 `
  --simulated
```

也可以换成经过授权的自备音频。输出JSON只记录输入文件名，不记录绝对路径。
提供`--observation-output`后还会生成转写可用状态、转写文本、关键词命中数量和
命中标签Observation。关键词命中只表示高风险交互特征，不直接判断诈骗。

`--bundle-output`会额外生成`fraud_keyword`和/或`audio_quality_low` Evidence：
单一关键词被限制为低置信交互特征；音频质量低于0.45时明确输出不可判定证据。
质量指标只能使用脱敏比例字段，例如：

```powershell
python .\src\whisper_demo.py .\output\synthetic_test.wav `
  --bundle-output .\output\audio_bundle.json `
  --quality-metrics .\samples\audio_quality_good.json `
  --simulated
```

没有音频文件时也可用脱敏转写文本复现后端输入：

```powershell
python .\src\generate_audio_bundle.py `
  --transcript .\samples\test_scam_transcript.txt `
  --output .\output\audio_bundle.json `
  --source-mode RECORDED_REPLAY `
  --simulated
```

## 8. Evidence自动生成与校验

生成三条Freeze v1.0 Evidence：

```powershell
python .\src\generate_evidence_samples.py `
  --output .\output\evidence_samples.json
```

原有三条基础样例：

| evidence_type | 来源 | 边界 |
|---|---|---|
| `activity_range_decline` | `MOCK` | 模拟长期活动范围下降，不作心理诊断 |
| `unauthorized_visitor` | `MOCK` | 模拟授权名单比对，只建议身份核验 |
| `fraud_keyword` | `RECORDED_REPLAY` | 模拟话术转写，不直接判断诈骗 |

`evidence.py`校验：

- 19个Freeze v1.0必填字段；
- 风险方向、时间尺度和输入来源枚举；
- `severity`、`confidence`和`data_quality`必须在0—1；
- 时间必须包含时区；
- 数字或`null`字段类型；
- 重复Observation ID和Evidence ID。

这些分数用于接口联调，尚未经过数据标定，不是实测准确率或正式阈值。

### 8.1 7月30日行为Evidence联调包

以下命令根据脱敏模拟统计生成6条Observation和3条Evidence：

```powershell
python .\src\generate_behavior_evidence.py `
  --input .\samples\mock_behavior_statistics.json `
  --output .\output\behavior_evidence_bundle.json
```

三条Evidence为`activity_range_decline`、`unauthorized_visitor`和
`unusual_dwell_time`。它们都引用联调包内真实存在的Observation ID，且整个包统一为
`source_mode: MOCK`、`simulated: true`。访客结果只表达“授权信息未匹配，建议家属核验身份”；停留结果使用`DEMO_UNCALIBRATED`阈值，二者均不构成诈骗判断。

### 8.2 8月5日多日趋势与昼夜节律

趋势适配器以“前N日为个人基线、最后一日为当前日”的日汇总JSON为输入，把每天的
区域访问、房间转换和昼夜活动汇总转换为标准Observation，并采用冻结方案规定的
滚动中位数和MAD输出可解释Evidence。

前7天形成滚动中位数/MAD个人基线，第8天作为当前日。历史不足时只输出
Observation，不生成长期Evidence；稳定基线时才允许生成
`activity_range_decline`、`room_transition_decline`和
`day_night_rhythm_change`。当前样例为`MOCK`，不能替代真实长期数据。

```powershell
python .\src\generate_trend_samples.py `
  --input .\samples\mock_daily_activity.json `
  --output .\output\trend_evidence_bundle.json
```

当历史日少于3天时标记`INSUFFICIENT`，3至6天标记`PROVISIONAL`，均只输出Observation；达到7个历史日后才标记`STABLE`并允许生成长期Evidence。示例包含7个历史日加1个当前日，会输出：

- `activity_range_decline`；
- `room_transition_decline`；
- `day_night_rhythm_change`。

该功能只提示长期活动或作息变化，不作心理疾病诊断。多日数据和阈值当前均为明确标记的`MOCK`/`DEMO_UNCALIBRATED`接口样例。完整验收见`docs/8月7日前趋势交付.md`。

### 8.3 后端调用行为适配器

OpenCV运行结束后，使用摘要生成后端Bundle。单段视频不会凭空生成长期Evidence；
只有额外提供稳定的多日趋势输入时才会附加长期Evidence：

```powershell
python .\src\generate_behavior_bundle.py `
  --summary .\output\behavior_summary.json `
  --output .\output\behavior_bundle.json `
  --resident-id resident-001 `
  --asset-id asset-c6c-demo-0001 `
  --timestamp 2026-08-08T14:11:55+08:00
```

## 9. FastAPI Mock接口提交

在仓库根目录启动后端：

```powershell
python -m pip install -r backend\requirements.txt
python -m uvicorn backend.main:app --reload
```

回到本Demo目录，先只校验不发送：

```powershell
python .\src\submit_to_backend.py `
  --bundle .\samples\behavior_evidence_bundle.example.json `
  --base-url http://127.0.0.1:8000 `
  --log-output .\output\backend_dry_run.json `
  --dry-run
```

真实提交：

```powershell
python .\src\submit_to_backend.py `
  --bundle .\samples\behavior_evidence_bundle.example.json `
  --base-url http://127.0.0.1:8000 `
  --log-output .\output\backend_submission.json
```

客户端固定先提交Observation，再提交Evidence；某项失败后停止后续提交并返回非零退出码。日志只记录ID、接口、HTTP状态和幂等状态，不保存后端计算的最终风险等级。7月30日本机联调9项均返回HTTP 201，见`logs/backend_submission_success_20260730.json`；服务未启动的降级格式见对应failure日志。

8月6日趋势联调样例同样完成6条Observation和3条Evidence入库，全部返回HTTP 201，见`logs/trend_backend_submission_20260806.json`。

## 10. 行为摘要隐私边界

`--summary-output`只写入：

- 输入类型和不含目录的文件名；
- 输入来源及模拟状态；
- 处理帧数、检测帧数和最大人数；
- 活动量计数、轨迹点数和像素距离；
- 耗时、退出原因和阈值状态。

摘要不保存视频帧、人脸、绝对文件路径、设备序列号或账号信息。

## 11. 当前限制

- 当前使用HOG，不是稳定的多人ID跟踪；
- 已支持人工区域和房间转换，但示例坐标必须按部署画面调整；
- `Travel distance`不是现实米制距离；
- 活动量和行为标签阈值未标定；
- 合成MP4只测试输入链路，不验证人物检测；
- Whisper仍可能出现简繁差异和近音错字；
- 访客授权和异常停留当前仅为MOCK联调，不具备真实身份识别能力；
- 多日趋势使用模拟统计验证接口，尚未接入长期真实数据；
- 异常踱步和正式阈值标定仍未实现。

详细降级逻辑见`docs/降级规则.md`。

## 12. 安全与提交检查

禁止上传：

- Whisper模型权重；
- 原始私人录音和人物视频；
- AccessToken、AppKey、AppSecret、设备验证码和序列号；
- 家庭IP、播放地址和带鉴权信息的日志；
- `.venv`、`output`、缓存和生成媒体。

提交前运行：

```powershell
git status --short --untracked-files=all
```

确认待提交文件与`上传清单.md`一致。未验证的真实效果保持“待统一素材复测”或“待标定”表述。

## 13. AlgorithmJob / AdapterBatch（后端冻结口径）

算法 Worker 的输入是完整 `AlgorithmJob`：`job_id`、`asset_id`、内部
`media_locator` 和带时区的 `captured_at`。行为适配器使用
`build_behavior_batch()`，语音适配器使用 `build_audio_batch()`，返回完整
`AdapterBatch`，其中证据字段统一为复数 `evidences`。`media_locator` 只在
算法进程内使用，不会写入返回 JSON。

Observation 和 Evidence 的 ID 都由稳定 `job_id` 派生，同一窗口重试不会产生
随机 ID。Observation 的时间使用素材采集时间 `captured_at`；算法运行耗时只写
入 `started_at` 和 `completed_at`。

语音结果只保存 `asr_transcript_redacted`、关键词计数、意图、质量分数和模型
版本。原始 Whisper 转写只在进程内参与匹配，不会写入文件、metadata、日志或
Evidence explanation。低质量音频输出 `audio_quality_low`；行为检出比例低时
输出 `tracking_lost`，正常无风险证据时允许 `evidences=[]`。

## 14. 老人回应识别与异常徘徊

### 14.1 老人回应识别

`audio_evidence.py` 在 Worker 的 `job_id` 路径中额外输出：

- `resident_response_intent`：`stable`、`help_requested`、`uncertain`、`no_response` 或 `unavailable`；
- `resident_response_match_count`：命中的回应规则组数量。

同时命中“没事”和“需要帮助”时保守输出 `uncertain`；音频质量低于 0.45
时输出 `unavailable` 和 `audio_quality_low`。回应结果只作为干预反馈特征，
不直接生成风险 Evidence，也不能由算法直接关闭事件。原始转写仍不会写入输出。

使用构造话术验证：

```powershell
python .\src\generate_audio_bundle.py `
  --transcript .\samples\resident_response_stable.txt `
  --output .\output\resident_response_batch.json `
  --resident-id resident-001 `
  --asset-id asset-response-demo-001 `
  --job-id job-response-demo-001 `
  --media-locator mock://resident-response-stable `
  --captured-at 2026-08-15T10:00:00+08:00 `
  --started-at 2026-08-15T10:00:01+08:00 `
  --completed-at 2026-08-15T10:00:02+08:00 `
  --source-mode MOCK `
  --simulated
```

### 14.2 异常徘徊

`pacing.py` 使用区域进入序列计算重复访问数、A-B-A 交替次数和演示级模式分数。
当前规则要求序列长度至少 5、区域转换至少 4 次、A-B-A 模式至少 3 次。
追踪质量低于 0.65 时禁止生成 `unusual_pacing`，改为保留 `tracking_lost`。

该规则只表示反复往返活动模式，不构成心理疾病诊断，阈值固定标记为
`DEMO_UNCALIBRATED`。运行 MOCK 样例：

```powershell
python .\src\generate_behavior_bundle.py `
  --summary .\samples\unusual_pacing_summary.example.json `
  --output .\output\unusual_pacing_batch.json `
  --resident-id resident-001 `
  --asset-id asset-pacing-demo-001 `
  --job-id job-pacing-demo-001 `
  --media-locator mock://unusual-pacing `
  --captured-at 2026-08-15T10:00:00+08:00 `
  --started-at 2026-08-15T10:00:01+08:00 `
  --completed-at 2026-08-15T10:00:02+08:00
```

真实视频验证仍需固定机位和人工区域标定，并准备正常通行、单次往返、反复
往返三类对照素材。
