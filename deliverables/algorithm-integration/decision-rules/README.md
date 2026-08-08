# 智能决策规则索引（张薇成果已合并）

张薇负责的规则不再放在本目录重复维护，正式来源已合并到：

- `contracts/v1/rulesets/ruleset-v1.0.json`：规则版本、时间窗、门槛、权重及规则编号；
- `contracts/v1/engine.py`：确定性状态机（证据→事件→干预→观察→回落）；
- `contracts/v1/memory.py`：短时 30 秒、中时 24 小时、长时 7 天记忆与基线准入；
- `tests/test_memory_and_ruleset.py`：规则与回落的回归验收；
- `scripts/run_memory_ruleset_rehearsal.py --runs 3`：可复现演练。

后端服务只把这一来源适配为持久化的 Evidence、RiskEvent 和 RuleTrace；不得在
`backend/` 或本目录重新复制阈值、权重或五步规则。

常易铭的 `fraud_keyword` 与 `activity_range_decline` 样例已被保留为统一 Evidence
输入。当前 ruleset-v1.0 的 P0 自动升级规则覆盖跌倒主闭环；心理和诈骗的具体升级
条件仍应由张薇在同一 ruleset 及测试中确认后再扩展，不能由后端或算法自行猜测。
