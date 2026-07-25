# 四对象契约 v1.0

本目录是7月31日前算法、智能体、后端和前端共同使用的唯一核心数据契约。

## 单一来源

- `models.py`：Pydantic v2唯一代码来源，未知字段一律拒绝；
- `schemas/`：由模型导出的JSON Schema，供前端和文档核对；
- `examples/`：四对象样例及固定跌倒Mock序列；
- `engine.py`：只用于一期Mock联调的确定性状态机；
- `rehearsal.py`：可复用的GREEN到RESOLVED演练流程。

重新导出Schema和样例：

```powershell
python scripts/export_contract_schemas.py
```

运行15项以上自动校验：

```powershell
python -m unittest discover -s tests -v
```

连续复现三次固定闭环：

```powershell
python scripts/run_mock_sequence.py --runs 3
```

## 核心对象与页面模型的边界

`title`、`timeline`、`risk_history`、`interventions`、`observations`等是前端组合展示字段，不属于RiskEvent核心契约。前端可以由四对象构建ViewModel，但不得修改核心枚举、字段含义或自行计算风险等级。

字段变更需由张薇和冷雨彤共同批准，并同步更新模型、Schema、样例、测试和冻结记录。

