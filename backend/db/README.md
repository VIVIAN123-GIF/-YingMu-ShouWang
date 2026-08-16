# 数据库模块

该模块使用 `sqlite+aiosqlite` 与 SQLAlchemy 异步会话。模型位于 `models/`，数据库初始化与兼容迁移位于 `init_db.py`。

## 初始化

在仓库根目录执行：

```powershell
python -m backend.db.init_db
python scripts/validate_database.py
```

初始化会创建设备、原始告警、Observation、Evidence、风险事件、干预结果、系统配置、周报、授权资产、规则轨迹以及事件—证据关联表，并写入缺失的默认配置。

## 使用约定

- 路由通过 `get_db()` 获得 `AsyncSession`。
- 业务查询和写入集中在 `backend/service/`，避免重复的通用 CRUD 层与业务 schema 产生字段漂移。
- `models/__init__.py` 统一导出模型，确保初始化时全部表已注册。
- 不要删除已存在的本地数据库；如需重建，先备份后再执行初始化。
