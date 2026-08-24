# H.264 正常样本兼容性回归

回归日期：2026-08-24

## 结论

利用赵勇和常一鸣同学已经交付的授权材料完成 H.264 正常样本兼容性回归，结果为 `PASSED`。

两组测试均通过正式后端 Worker 和隔离数据库执行；未连接真实设备，未修改正式数据库，未调用外部 Agent Provider。

## 赵勇材料

选用 v3 包中的原生 H.264 正常行走样本 `D2_WALK_02_right_to_left.mp4`：

- 编码为 `H.264/avc1`，分辨率 `568x320`，15 FPS；
- Worker 为 `COMPLETED`；
- GAIT 为 `SUCCESS`；
- 写入 9 条 Observation 和 2 条 Evidence；
- 未创建 RiskEvent 或 Agent Job；
- 同任务重跑后 Observation、Evidence、RiskEvent、Agent Job 数量不增加。

该结果证明 GAIT 能正确读取原生 H.264 正常视频。由于分辨率只有 `568x320`，它不单独承担 720p 规格验收。

## 常一鸣材料

选用负责人私下交付包中的授权正常样本 `tracking_control_full_body_01.mp4`。源文件为 `1280x720 H.265/HEVC`，在临时目录派生为：

```text
H.264 High / avc1 / yuv420p / 1280x720 / 15 FPS / no audio / faststart
```

派生文件通过 Worker 同时调用 GAIT 和 TRAJECTORY：

- Worker 为 `COMPLETED`；
- GAIT 为 `LOW_QUALITY`，与该源样本已有的低质量口径一致；
- TRAJECTORY 为 `NO_EVIDENCE`；
- 两模块均未 `FAILED`；
- 共写入 23 条 Observation；
- 仅生成 `tracking_lost` 和后端质量门产生的 `quality_gate_failed`；
- 未创建 RiskEvent 或 Agent Job；
- 同任务重跑后业务对象数量不增加。

该结果证明 720p H.264 派生正常视频能够通过 GAIT、TRAJECTORY 和后端持久化链路，不会误升为 ORANGE/RED。

## 判定边界

本轮完成的是授权材料的 H.264 算法兼容性回归，不等同于萤石真实标准流验收。下一步仍需从已恢复的 H.264 标准流录制一段授权人员正常走动视频，重复相同 Worker 检查，以确认萤石取流、FFmpeg 封装和算法输入的完整链路。

机器可读结果见 `h264_normal_compatibility_result.json`。
