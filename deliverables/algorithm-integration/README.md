# 算法与决策联调交付物

这里仅保存可审计的**输入样例、接口验收材料和规则索引**；算法实现、前端
实现和张薇的规则核心均保持在各自原目录，不在这里复制或改写。

```text
deliverables/algorithm-integration/
├── voice-behavior-2026-08-03/   # 常易铭交付物；原压缩包及解包副本
├── pose/                         # 赵勇提供的步态样例（保留原目录）
└── decision-rules/               # 张薇已合并规则的索引，不复制规则
```

## 常易铭：语音/行为样例

原始压缩包位于 `voice-behavior-2026-08-03/`，SHA-256 为：

```text
0DF660E40329C614EC5235B7CA7AADE5D009183E8633A4E34CE8E21D72BD73D9
```

解包后的原样文件在 `source/常易铭-语音行为接口样例-20260803/`。其中有 6 个
独立请求：语音的两条 Observation 和一条 `fraud_keyword` Evidence，以及行为的
两条 Observation 和一条 `activity_range_decline` Evidence。它们均为模拟或回放
素材，不能写成真实识别结果。

请用以下命令做隔离校验；脚本使用临时 SQLite，不会写入你的正式数据库，也不会
修改算法文件：

```powershell
python scripts/validate_voice_behavior_package.py
```

## 决策边界

算法只能依次调用 `POST /api/v1/observations`、`POST /api/v1/evidence`。
后端读取张薇维护的 `ruleset-v1.0` 执行状态机和事件持久化；算法、前端都不计算
或提交最终 `risk_level`。
