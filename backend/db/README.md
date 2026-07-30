# backend/db README.md
## 项目数据库模块说明
本模块为项目异步SQLAlchemy数据库底层，包含ORM模型、通用CRUD、数据库初始化脚本，基于 `sqlite+aiosqlite` 异步方案，适配FastAPI异步架构。

## 目录结构
```
backend/db/
├── database.py        # 数据库引擎、会话工厂、ORM基类Base、get_db依赖
├── init_db.py         # 一键建表 + 初始化系统默认配置（自动去重不重复插入）
├── crud/              # 通用增删改查层
│   ├── __init__.py    # 统一导出所有crud实例与CRUDBase基类
│   ├── base.py        # CRUD泛型基类，封装通用get/create/update/remove
│   ├── crud_device.py
│   ├── crud_obs.py
│   ├── crud_evidence.py
│   ├── crud_risk_event.py
│   └── crud_intervene.py
└── models/            # 全部数据表ORM实体
    ├── __init__.py    # 统一导出所有模型类，供外部一键导入
    ├── device.py      # 设备表 DeviceInfo
    ├── observation.py # 观测数据表 Observation
    ├── evidence.py    # 证据表 Evidence
    ├── risk_event.py  # 风险事件表 RiskEvent
    ├── risk_event_evidence.py # 风险事件-证据 多对多中间关联表
    ├── intervention_result.py # 干预记录表 InterventionResult
    ├── alarm.py       # 萤石原始告警 RiskAlarm
    └── system_weekly.py # 系统配置表 + 周统计表
```

## 环境依赖
```bash
pip install sqlalchemy[asyncio] aiosqlite pydantic
```

## 数据库初始化运行命令
项目根目录 PowerShell 执行（必须携带PYTHONPATH识别backend模块）
```powershell
$env:PYTHONPATH="$PWD"; python backend/db/init_db.py
```
执行成功输出：
```
✅ 所有数据表创建完成：设备/观测/证据/风险事件/干预/原始告警/配置/周报/事件证据关联表
✅ 规范配套默认阈值配置写入成功（已自动跳过重复项）
```
运行后项目根目录生成 `ezviz_system.db` SQLite数据库文件。

## 分层职责说明
1. **database.py**
    - 创建异步数据库引擎、会话工厂 `AsyncSessionLocal`
    - 提供全局ORM父类 `Base`，所有models表继承该类
    - 提供FastAPI依赖注入函数 `get_db()`，接口直接注入数据库会话

2. **models/**
    - 定义全部数据表结构、字段、外键、关联关系、联合唯一约束
    - 包含业务表、多对多中间表、系统配置表、统计报表表
    - 统一在 `models/__init__.py` 导出，外部可一次性导入所有模型

3. **crud/**
    - `base.py`：通用CRUD泛型模板，封装单条查询、分页查询、新增、更新、删除
    - crud_xxx.py：每张表独立创建/更新Pydantic模型，实例化CRUD操作对象
    - 业务接口直接导入crud实例，无需重复编写数据库ORM语句

4. **init_db.py**
    - 自动创建全部数据表（Base.metadata.create_all）
    - 初始化系统阈值配置，自动判断已存在key，避免重复插入数据

## 使用示例（接口中调用CRUD）
```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from backend.db.database import get_db
from backend.db.crud import crud_device

# 新增设备
@router.post("/device/add")
async def add_device(db: AsyncSession = Depends(get_db)):
    new_device = await crud_device.create(db, DeviceCreate(...))
    return new_device
```

## 已知待优化清单（当前不影响运行，后续出问题再修改）
### 高优先级（联调易报错）
1. Observation表 `extra_metadata` 与数据库列名 `metadata` 别名冲突，读写易字段不匹配
2. SQLite不支持SQLAlchemy原生Enum校验，非法字符串可直接入库，建议改用Pydantic Literal做入参拦截
3. 多对多关系默认 `lazy="selectin"`，批量查询存在N+1性能问题

### 中优先级（规范/长期维护）
1. 所有DateTime字段未存储时区，不满足ISO8601带时间戳规范
2. `evidence_ids` / `observation_ids` 使用逗号拼接文本存储数组，仅作兼容，新业务统一使用多对多中间表
3. 风险等级、风险域、设备来源等枚举字符串硬编码分散，缺少全局统一常量文件

### 低优先级（代码美化、工具增强）
1. ORM反向关联命名风格不统一
2. SystemConfig配置值未统一JSON序列化存储
3. CRUD缺少批量更新封装函数
4. init_db无参数开关控制是否清空旧表
5. 索引、唯一约束缺少业务注释

## 补充说明
1. VSCode内黄色导入波浪线为Pylance对Conda环境索引bug，**仅编辑器提示，不影响代码运行**，无需处理；
2. 所有模型、CRUD、初始化脚本已完整调通，可直接支撑后端业务接口开发；
3. 多对多关联采用独立中间表 `risk_event_evidence`，替代逗号分割字符串，规范关联查询。