# backend/README.md
## 项目后端模块｜YingMu-ShouWang 幕目守望后端
基于 FastAPI + SQLAlchemy 2.0 异步架构，SQLite异步存储，面向老人居家风险监测预警系统。

## 目录结构
```
backend/
├── api/                 # 接口路由层，存放所有业务接口Router
├── db/                  # 数据库ORM模块（单独内置README）
│   ├── database.py      # 数据库异步引擎、会话、Base父类、依赖
│   ├── init_db.py       # 一键建表 & 初始化系统默认配置
│   ├── crud/            # 通用数据表增删改查封装
│   └── models/          # 所有数据表ORM实体模型
├── service/             # 业务服务层，复杂业务逻辑、状态机、算法调度
├── utils/               # 通用工具函数
│   ├── config.py        # 全局配置读取
│   └── link_replace.py  # 链接、地址处理工具
├── main.py              # FastAPI项目入口，挂载路由、启动服务
└── requirements.txt     # Python依赖清单
```

## 环境部署
### 1. 安装依赖
```powershell
pip install -r requirements.txt
```
核心依赖：
- fastapi
- uvicorn
- sqlalchemy[asyncio]
- aiosqlite
- pydantic

### 2. 数据库初始化（首次启动前必须执行）
项目根目录执行：
```powershell
$env:PYTHONPATH="$PWD"; python backend/db/init_db.py
```
执行成功后生成 `ezviz_system.db` 数据库文件。

### 3. 启动后端服务
```powershell
uvicorn backend.main:app --reload
```
启动成功后访问文档：
- Swagger文档：http://127.0.0.1:8000/docs
- ReDoc文档：http://127.0.0.1:8000/redoc

## 分层架构规范（严格遵循）
1. **api 接口层**
只负责：请求参数校验、响应封装、调用service；
禁止直接写数据库操作，不存放复杂业务逻辑。

2. **service 业务层**
存放核心业务逻辑：风险状态机、干预流程、数据聚合、周报统计；
调用 `db.crud` 操作数据库。

3. **db 数据层**
models：数据表定义
crud：通用增删改查
只做数据读写，不包含业务判断。

4. **utils 工具层**
配置、字符串处理、时间工具、json工具等通用函数。

## 模块调用链路
> HTTP请求 → api路由 → service业务逻辑 → crud → models（数据库）

## 数据库相关说明
- 使用异步SQLAlchemy2.0 + aiosqlite，全程异步，适配FastAPI；
- 所有数据表、初始化脚本位于 `backend/db/`，内部自带独立README；
- 多对多关联采用独立中间表，规范风险事件与证据关联关系。

## 已知事项
1. VSCode编辑器sqlalchemy黄色导入警告为Pylance+Miniconda索引bug，**不影响运行，可以忽略**；
2. db模块存在一份【后续按需优化清单】，当前代码可正常开发，出现对应业务问题再迭代优化；
3. `backend/db/README.md` 包含数据表结构、CRUD使用示例、初始化命令。

## 开发注意事项
1. 新增数据表：在 `db/models/` 创建模型，在 `models/__init__.py` 导出；
2. 新增接口：api文件夹新建路由，在main.py注册；
3. 复杂逻辑不要写在api内，迁移至service；
4. 数据库操作统一使用crud封装，禁止到处手写重复ORM语句；
5. 所有接口优先使用异步async函数。

## 待建设模块（后续开发）
- 鉴权中间件
- 日志统一封装
- 定时任务（周报统计、过期数据清理）
- 萤石平台对接service
- 视频流调度模块

如果你想要，我可以同步帮你生成一份标准 `requirements.txt` 内容一并补齐。