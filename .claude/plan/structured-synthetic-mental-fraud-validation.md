# 心理趋势与诈骗核验结构化虚拟场景验证

## 目标

- 保持跌倒风险为真实数据与准确率指标的主方向。
- 心理趋势与诈骗核验各提供 12 组可复现的结构化虚拟场景。
- 所有场景明确标记 `source_mode=MOCK`、`simulated=true`、`scenario_kind=STRUCTURED_SYNTHETIC` 和生成器版本。
- 验证 Evidence 生成、领域规则、事件状态闭环、可追溯性、幂等与处理时延，不宣称临床或真实诈骗准确率。

## 实施任务

- [x] 在合同层增加 MENTAL/FRAUD 纯决策策略与规则集声明，保留 FALL 行为。
- [x] 风险服务按 Evidence 领域分发，并按 resident + domain 隔离活动事件。
- [x] 支持心理关怀/趋势恢复与诈骗身份核验/误报确认的状态闭环。
- [x] 新增心理 12 组、诈骗 12 组确定性场景生成器。
- [x] 新增隔离数据库批量验收脚本，输出逐场景 JSON、领域汇总和 Markdown 报告。
- [x] 增加纯策略、服务集成、来源标签、低质量、困难负样本和幂等测试。
- [x] 运行聚焦测试、完整后端测试及已有前端测试，检查生成报告口径。

## 依赖与约束

- 复用 v1 Evidence/Observation/RiskEvent/RuleTrace 合同，不增加数据库字段。
- `scenario_kind` 与 `generator_version` 放在场景包和 Observation metadata；Evidence 使用 `adapter_version` 记录生成器版本。
- 非跌倒领域不复用跌倒的 no-response、持续不稳与 60 秒恢复调度。
- 不修改现有心理与诈骗页面设计，不接入真实老人或真实访客素材。

## 验收标准

- 24/24 场景结果与声明的预期一致。
- 心理正常场景无事件；下降/节律场景按规则进入 YELLOW；恢复场景全部闭环。
- 诈骗单项/双项证据不进入 ORANGE；三项风险组合进入 ORANGE；核验场景全部闭环。
- Evidence 到 Observation、Event 到 Evidence、Trace 到规则版本完整可追溯。
- 同一场景重复提交不新增 Evidence 或事件，返回幂等结果。
- 报告只包含场景触发、错误升级、完整率、闭环、幂等与时延指标，并显著注明非真实准确率验证。
- 现有 FALL 测试无回归。

## 状态

- 当前：已完成。后端 240 项、前端 98 项测试和前端生产构建均通过；24 组场景验收 PASS。
