# main误删除恢复记录

## 发现

`fb90ad6`合并后端PR时，相对合并前主线`47223b8`出现196个文件变化、2215行新增、18282行删除，其中118个既有文件被删除。受影响范围包括contracts、frontend、scripts、原测试、算法交付物和部分正式材料。

## 恢复原则

- 从`47223b8`只恢复被删除的既有文件，不覆盖`fb90ad6`新增的FastAPI、SQLAlchemy和萤石适配代码；
- 保留后端新增的`tests/test_risk_api.py`，同时恢复原37项智能体契约与规则测试；
- 所有恢复和后端整改在`fix/main-restore-and-risk-api`完成，通过PR进入main；
- 不把异常main直接合入张薇当前存在未提交修改的`feature/zw/agent`。

## 同步整改

- 后端质量和置信门槛从独立0.60改为读取`contracts/v1/rulesets/ruleset-v1.0.json`中的0.70；
- 低质量Evidence生成`SYSTEM/quality_gate_failed`并命中R-FALL-03；
- 重复Evidence命中R-SYSTEM-01，保留原event_id，不新增事件或干预；
- 基线只读取GREEN、高质量、安全基线Evidence，统一状态为INSUFFICIENT、PROVISIONAL、STABLE；
- Windows初始化输出不再依赖Emoji编码。
- 清除后端合并重新带入文档的完整AppKey和AccessToken，统一替换为`<REDACTED>`；该凭证按已泄露处理，必须在萤石开放平台撤销或轮换，Git脱敏不能代替平台侧处置；
- `.env.example`只保留空凭证字段，并将质量、置信度示例门槛同步为0.70。

## 验证

- 后端API：6项通过；
- 原四对象、Mock闭环：22项通过；
- 三层记忆与ruleset：15项通过；
- 四项HTTP固定验收：通过，数据库仅1个ORANGE事件、0条干预；
- 前端单元测试27项通过，生产构建成功；`npm audit`报告6项高危依赖告警，当前不使用`--force`进行破坏性升级，登记后单独评估兼容性。
