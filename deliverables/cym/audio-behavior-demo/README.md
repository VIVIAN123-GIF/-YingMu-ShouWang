# 语音与行为算法最小Demo

负责人：常易铭  
交付日期：2026年7月25日  
建议分支：`feature/cym/audio-behavior-demo`

## 当前结论

> 语音识别和轨迹方案已形成可行性结论，已提供Evidence样例；实际速度、中文识别效果和人物检测稳定性等待负责人本地复现。

本目录用于复现两个最小链路：

1. 授权本地音频经过Whisper转成中文文本；
2. 摄像头画面经过OpenCV HOG与MOG2生成人员框、活动量和人物中心轨迹。

当前代码只生成感知结果和Evidence样例，不直接输出GREEN、YELLOW、ORANGE或RED风险等级，也不作诈骗或心理疾病诊断。

## 文件结构

```text
.
├─ README.md
├─ requirements.txt
├─ src/
│  ├─ whisper_demo.py
│  ├─ camera_test.py
│  └─ behavior_demo.py
├─ samples/
│  ├─ evidence_samples.json
│  └─ test_scam_transcript.txt
├─ logs/
│  ├─ whisper_test_20260725.json
│  └─ behavior_test_20260724.md
└─ docs/
   ├─ 常易铭-7月24日调研交付.md
   ├─ 脱敏测试素材说明.md
   ├─ 降级规则.md
   └─ 7月31日前任务拆分.md
```

原始录音、视频、Whisper模型权重、`.venv`和生成目录均不在上传包中。

## 环境

已验证环境：

- Windows PowerShell；
- Python 3.13.14；
- FFmpeg 8.1.2；
- `openai-whisper` 20250625；
- `opencv-contrib-python` 5.0.0.93；
- `torch` 2.13.0；
- `numpy` 2.4.6。

FFmpeg不是Python包，需要先在系统中安装，并确认以下命令可运行：

```powershell
ffmpeg -version
```

## 安装

在本目录打开PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

首次运行Whisper时会下载所选模型。模型文件只保存在本机缓存中，不应提交到GitHub。

## 运行Whisper Demo

请使用经过授权、无敏感信息的本地音频：

```powershell
python .\src\whisper_demo.py "C:\path\to\authorized_test_audio.m4a" `
  --model tiny `
  --language Chinese `
  --output-dir .\output
```

预期生成：

```text
output/<音频文件名>.txt
output/<音频文件名>.json
```

JSON记录模型、语言、处理耗时和转写文本，不记录输入文件的绝对路径。

本机模拟录音的脱敏输出见`samples/test_scam_transcript.txt`，实测记录见`logs/whisper_test_20260725.json`。测试录音本身不上传。

## 运行OpenCV Demo

先确认摄像头可读取：

```powershell
python .\src\camera_test.py
```

再运行为何检测与轨迹Demo：

```powershell
python .\src\behavior_demo.py
```

按`q`退出窗口。预期画面包含：

- `Persons`：当前帧人员数；
- `Motion area`和`Activity`：画面活动量；
- 紫色圆点与轨迹：最大人体框几何中心的平滑轨迹；
- `Travel distance`：本次运行的累计像素移动距离；
- `Behavior`：未经正式标定的STILL/WALKING/HIGH MOVEMENT标签。

建议测试步骤：

1. 距离摄像头约2—3米，让完整直立人体进入画面；
2. 站立不动约10秒；
3. 左右走动约10秒；
4. 走出画面，再重新走回；
5. 记录人员数、活动量和轨迹变化。

## Evidence样例

`samples/evidence_samples.json`包含三条Freeze v1.0样例：

| evidence_type | 来源 | 说明 |
|---|---|---|
| `activity_range_decline` | `MOCK` | 模拟长期活动范围相对个人基线下降 |
| `unauthorized_visitor` | `MOCK` | 模拟访客未匹配授权名单，只建议身份核验 |
| `fraud_keyword` | `RECORDED_REPLAY` | 授权模拟录音的Whisper转写和高风险词样例 |

快速检查JSON：

```powershell
python -m json.tool .\samples\evidence_samples.json > $null
```

样例分数用于接口联调，尚未经过数据集标定，不得作为实测准确率或正式阈值。

## 当前限制

- HOG适合完整、直立、距离适中的人体，近距离、截断、遮挡和非直立姿态容易漏检；
- 当前只跟踪面积最大的一个人体框，不是稳定的多人ID跟踪；
- 当前轨迹是像素坐标，尚未完成人工区域标定和房间转换；
- 当前行为标签阈值只用于Demo；
- Whisper可能出现简繁差异、同音错字和近音误识别；
- 单个关键词和单个人体框都不能独立生成最终风险判断；
- OpenCV Demo目前只支持摄像头，本地MP4输入列入7月28日前任务。

详细降级逻辑见`docs/降级规则.md`。

## 安全与隐私

禁止上传：

- Whisper模型权重；
- 原始私人录音和人物视频；
- AccessToken、AppKey、AppSecret、设备验证码和序列号；
- 家庭IP、播放地址和带鉴权信息的日志；
- `.venv`、缓存和生成的`output`目录。

需要共享测试素材时，只能使用经过授权的模拟素材或脱敏片段，并标明`source_mode`和`simulated`。

## 验收方式

- [ ] 根据本README完成环境安装；
- [ ] 使用自备授权音频运行Whisper并看到TXT/JSON输出；
- [ ] 运行摄像头测试；
- [ ] 完整站立人体能够出现HOG检测框；
- [ ] 走动时活动量和紫色轨迹发生变化；
- [ ] `evidence_samples.json`可被JSON解析；
- [ ] 没有模型、媒体文件、密钥或设备隐私信息；
- [ ] 未验证内容保持“待复现”或“待标定”表述。

