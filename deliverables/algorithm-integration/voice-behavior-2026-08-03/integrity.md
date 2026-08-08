# 常易铭语音/行为接口样例：完整性与使用边界

## 来源校验

- 文件：`常易铭-语音行为接口样例-20260803.zip`
- 提供 SHA-256：`0DF660E40329C614EC5235B7CA7AADE5D009183E8633A4E34CE8E21D72BD73D9`
- 本次导入计算结果：一致。
- `source/常易铭-语音行为接口样例-20260803/` 是该压缩包的原样解包副本；请勿在其中修改算法输入、Schema、生成脚本或既有验收日志。

## 接口顺序

```text
voice/01-observation-transcript.json
→ voice/02-observation-keyword-count.json
→ voice/03-evidence-fraud-keyword.json
→ behavior/01-observation-baseline-range.json
→ behavior/02-observation-current-range.json
→ behavior/03-evidence-activity-range-decline.json
```

每条 Observation 先于其关联 Evidence 提交。统一入口为
`/api/v1/observations` 与 `/api/v1/evidence`；算法不直接写 SQLite，也不提交
`risk_level`。

整理前的手工拆包副本已删除；当前目录只保留哈希核验通过的原始压缩包和原样解包
副本，避免出现两个可被误用的算法来源。
