# 语音与行为算法最小Demo

| 项目 | 内容 |
|---|---|
| 负责人 | 常易铭 |
| 更新日期 | 2026年7月25日 |
| 分支 | `feature/cym/audio-behavior-demo` |
| 当前状态 | 代码与接口样例可自动复现；真实人物效果和正式阈值仍待统一素材验证 |

## 1. 项目边界

本目录验证两个最小链路：

1. 经授权的本地音频通过Whisper转成中文文本；
2. 摄像头或本地MP4通过OpenCV生成人员框、活动量和人物中心轨迹。

本模块只生成感知结果和Evidence，不直接输出GREEN、YELLOW、ORANGE或RED风险等级，也不作诈骗或心理疾病诊断。

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
│  ├─ observation.py
│  ├─ evidence.py
│  └─ generate_evidence_samples.py
├─ scripts/
│  ├─ generate_test_video.py
│  └─ generate_test_audio.ps1
├─ tests/
│  ├─ test_behavior.py
│  ├─ test_evidence.py
│  ├─ test_observation.py
│  └─ test_whisper_demo.py
├─ samples/
│  ├─ evidence_samples.json
│  ├─ test_scam_script.txt
│  └─ test_scam_transcript.txt
├─ logs/
│  ├─ behavior_test_20260724.md
│  ├─ whisper_test_20260725.json
│  └─ reproduction_fix_20260725.md
└─ docs/
   ├─ 常易铭-7月24日调研交付.md
   ├─ 脱敏测试素材说明.md
   ├─ 降级规则.md
   └─ 7月31日前任务拆分.md
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

预期：当前16项测试全部`OK`，其中Observation样例还会通过仓库
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

## 7. Whisper复现

### 7.1 生成无隐私的本地合成音频

Windows PowerShell可执行：

```powershell
& .\scripts\generate_test_audio.ps1
```

输出为`output\synthetic_test.wav`。它读取`samples\test_scam_script.txt`并调用Windows本地语音合成，不包含真人录音；发音效果取决于本机语音包。

### 7.2 执行转写

```powershell
python .\src\whisper_demo.py .\output\synthetic_test.wav `
  --model tiny `
  --language Chinese `
  --output-dir .\output `
  --observation-output .\output\audio_observations.json `
  --resident-id resident-001 `
  --asset-id asset-synthetic-audio-0001 `
  --simulated
```

也可以换成经过授权的自备音频。输出JSON只记录输入文件名，不记录绝对路径。
提供`--observation-output`后还会生成转写可用状态、转写文本、关键词命中数量和
命中标签Observation。关键词命中只表示高风险交互特征，不直接判断诈骗。

## 8. Evidence自动生成与校验

生成三条Freeze v1.0 Evidence：

```powershell
python .\src\generate_evidence_samples.py `
  --output .\output\evidence_samples.json
```

当前三条样例：

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

## 9. 行为摘要隐私边界

`--summary-output`只写入：

- 输入类型和不含目录的文件名；
- 输入来源及模拟状态；
- 处理帧数、检测帧数和最大人数；
- 活动量计数、轨迹点数和像素距离；
- 耗时、退出原因和阈值状态。

摘要不保存视频帧、人脸、绝对文件路径、设备序列号或账号信息。

## 10. 当前限制

- 当前使用HOG，不是稳定的多人ID跟踪；
- 当前只有人物中心像素轨迹，尚未完成人工区域标定和房间转换；
- `Travel distance`不是现实米制距离；
- 活动量和行为标签阈值未标定；
- 合成MP4只测试输入链路，不验证人物检测；
- Whisper仍可能出现简繁差异和近音错字；
- 访客授权、异常停留、异常踱步和多日趋势仍未实现；
- 当前Evidence生成器构造联调样例，尚未连接实时Demo输出。

详细降级逻辑见`docs/降级规则.md`。

## 11. 安全与提交检查

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
