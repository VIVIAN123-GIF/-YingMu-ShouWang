# 赵勇 GAIT v4.2 算法与后端联调验收

验收日期：2026-08-24

## 结论

赵勇负责的 GAIT 部分已完成算法到后端的完整联调，验收结果为 `PASSED`。

本次使用 v4.2 新增的授权黄金回放片段，在当前主干等价代码树和项目 `.venv` 中通过正式后端 Worker 执行。GAIT 同时生成 `rapid_rise`、`trunk_sway` 和 `relative_speed_change`，后端命中 `R-FALL-02`，完成 `GREEN -> ORANGE`，创建 `ORANGE / INTERVENING` RiskEvent 和 Agent Job。

## 本机复跑结果

| 验收项 | 结果 |
|---|---|
| Worker | `COMPLETED` |
| GAIT Adapter | `SUCCESS` |
| Observation | 11 条 |
| Evidence | 3 条 |
| Evidence 类型 | `rapid_rise`、`trunk_sway`、`relative_speed_change` |
| RuleTrace | 命中 `R-FALL-02` |
| RiskEvent | 1 条，`ORANGE / INTERVENING` |
| Agent Job | 1 条，`FALLBACK` 完成 |
| 相同任务重跑 | Observation、Evidence、RiskEvent、Agent Job 数量不增加 |

`FALLBACK` 表示验收时有意关闭外部模型 Provider，持久化 Agent Job 已通过仓库内置模板解释正常完成，不属于失败。

重复执行后 RuleTrace 从 3 条增加为 6 条。新增记录是每条重复 Evidence 对应的 `R-SYSTEM-01` 幂等审计轨迹，不是业务对象重复写入。

## 范围边界

- 本批次固定为 `module_scope=GAIT`、`source_mode=RECORDED_REPLAY`、`simulated=true`。
- 未执行 TRAJECTORY；常同学负责的算法材料和既有闭环结论保持独立，不与赵勇材料混用。
- 本结论证明授权录制回放链路，不将其表述为实时设备算法闭环。
- ZIP、MP4、SQLite、绝对路径、凭证、设备号和播放地址均未进入 Git。

## 证据索引

- `upstream_adapter_rerun.json`：赵勇侧 adapter 预检结果的脱敏副本。
- `upstream_r_fall_02_result.json`：赵勇侧 `R-FALL-02` 规则结果的脱敏副本。
- `backend_worker_e2e_result.json`：负责人机器上正式 Worker、持久化、Agent 与幂等验收结果。
- `h264_normal_compatibility_result.json`：赵勇原生 H.264 与常一鸣 720p H.264 派生正常样本的机器可读回归结果。
- `h264_normal_compatibility.md`：H.264 正常样本兼容性回归结论与真实标准流验收边界。

最终验收以 `backend_worker_e2e_result.json` 为准。
