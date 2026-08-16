# 四项阻塞解除验收说明（2026-08-01）

## 当前结论

仓库开发与自动化验收已完成；真实黄金包和个人初步基线尚等待8月1—3日授权 C6c 素材，因此当前诚实状态为：

- 代码与测试：`PASS`
- 公开数据黄金回归包：`PENDING_ASSET`
- 真实授权黄金包：`PENDING_ASSET`
- 个人同机位基线：`INSUFFICIENT / 样本不足`

不得把上述两个待素材状态改写为真实验收完成，也不得提交视频、设备凭证、授权原件或含隐私的本地路径。

## 已解除的技术阻塞

1. FastAPI 对 `RECORDED_REPLAY` 跌倒 Evidence 实施完整409门禁；一键工具按 Asset、Observation、Evidence 顺序提交。
2. `posture_recovered.current_value` 唯一表示连续稳定秒数，角度使用独立 `stable_trunk_angle_deg` Observation；旧角度语义返回422。
3. 智能体和FastAPI调用同一个无数据库决策核心，规则阈值只读取 `ruleset-v1.0.json`，风险分动态计算，RuleTrace作为数据库/API/日志/页面唯一事实。
4. 基线仅接纳授权C6c、同居民/设备/机位、GREEN且质量不低于0.70的安全样本；三项指标同机位覆盖3日后才为“初步基线”。

## 已执行自动化验收

```powershell
python -m pytest -q
cd frontend
npm test -- --run
npm run build
python scripts/run_api_evidence.py
```

后端三轮闭环材料位于 `deliverables/e2e-2026-07-31/`；浏览器三轮材料位于 `deliverables/frontend-api-2026-07-31/`。材料均为明确标记的Mock自动化回归，不是实机录像。

## 现场接入只需提供

- 匿名 `resident_id`
- 脱敏 `device_ref`
- 固定 `camera_position_id`
- 8月1、2、3日带时区拍摄时间
- `AUTHORIZED` 状态、授权记录非敏感引用、保留期限
- Git外的正常动作与受保护黄金片段本地路径

随后使用 `deliverables/zy/pose-demo/integration/README.md` 中的生成与提交命令；不足三日继续显示“样本不足”。
