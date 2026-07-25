# 7月25日复现问题修复记录

## 1. 复现环境

- 日期：2026年7月25日
- 系统：Windows PowerShell
- Python：3.13.14
- FFmpeg：8.1.2
- openai-whisper：20250625
- OpenCV：5.0.0.93

本记录中的生成视频和合成语音只用于验证输入、自动退出、转写和 Evidence 链路，不包含私人录音、真人视频或设备信息。

## 2. OpenCV复现结果

使用 `scripts/generate_test_video.py` 生成了60帧、仅含移动图形的本地MP4。

完整处理视频时：

- `frames_processed`：60
- `stop_reason`：`video_eof`
- `detected_frames`：0
- 进程返回码：0

该结果证明本地MP4能够读取，并能在视频正常结束时成功退出。`detected_frames` 为0符合预期，因为素材不包含人物，不能据此评价HOG人物检测效果。

设置 `--max-frames 30` 时：

- `frames_processed`：30
- `stop_reason`：`max_frames`
- 进程返回码：0

摄像头无窗口测试设置 `--max-seconds 5` 时：

- 实际读取：143帧
- 退出原因：`max_seconds`
- 进程返回码：0

代码检查确认MOG2和HOG接收的是未绘制的 `analysis_frame`，人员框、文字和紫色轨迹只绘制在其副本上，不会进入运动区域计算。

## 3. Evidence复现结果

`generate_evidence_samples.py` 已通过统一构造函数生成三条 Freeze v1.0 样例：

- `activity_range_decline`：`MENTAL + LONG + MOCK`，`simulated: true`
- `unauthorized_visitor`：`FRAUD + SHORT + MOCK`，`simulated: true`
- `fraud_keyword`：`FRAUD + SHORT + RECORDED_REPLAY`，`simulated: true`

单元测试覆盖合法样例、缺少必填字段、非法枚举、分数越界、时间缺少时区和重复 Evidence ID；校验器还会拒绝单条 Evidence 内重复的 Observation ID。共9项测试，全部通过。

这些样例不输出最终风险等级。`fraud_keyword` 仅表示出现高风险交互特征，不表示已经确认诈骗。

## 4. Whisper复现结果

`python .\src\whisper_demo.py --check` 检查通过，能够明确报告Whisper和FFmpeg状态。

使用 `samples/test_scam_script.txt` 和 Windows 本地语音合成生成无隐私测试音频，再用 Whisper `tiny` 中文模型转写。实际结果为：

> 您好,我是社區健康服務人員現在有一個免費的楊老投資項目可以保證收益請把驗證馬告訴我並馬上完成轉帳

关键语义“保证收益”和“马上完成转账”被保留；同时存在简繁差异及“养老→杨老”“验证码→验证马”等同音误识别。这说明当前Demo可验证转写链路，但关键词不能单独触发风险升级，后续需要结合上下文、音频质量和其他 Evidence。

## 5. 当前结论与边界

- MP4输入、视频EOF、按帧退出、按时间退出均可自动复现。
- 分析帧与绘制帧已经分离。
- 三条Evidence由代码统一构造和校验，不再只依赖手写JSON。
- Whisper会在正式解码前检查FFmpeg并提供安装提示。
- 当前阈值仍未标定；HOG真人效果仍是成员本机实测，待负责人使用统一素材复测。
- 本轮未实现区域轨迹、访客身份识别、多日趋势和最终风险分级。
