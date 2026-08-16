# 步态联调材料（待赵勇提供）

已收到赵勇提供的回放样例，原始文件归档于 `incoming/`，不直接修改。该文件已使用 `FALL + tracking_lost`，符合冻结契约。

`manifest.json` 记录当前场景和验证状态；`results/` 用于保存后端提交响应。新增场景时保留原始批量文件，并更新清单，不覆盖既有结果。

待收到后补入并按场景命名：

1. 正常步态的 Observation/Evidence JSON 对；
2. `rapid_rise`、`trunk_sway` 或 `gait_instability` 异常场景的 JSON 对；
3. 低质量或目标跟踪丢失场景的 JSON 对。

每对文件必须通过冻结 v1.0 Schema，并保留 `confidence`、`data_quality`、`source_mode` 和 `simulated`。
