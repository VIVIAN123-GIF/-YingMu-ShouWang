# backend/db/database.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator
import os

# 数据库文件路径
DB_PATH = os.getenv("YINGMU_DB_PATH", "ezviz_system.db")
DB_URL = os.getenv("YINGMU_DB_URL", f"sqlite+aiosqlite:///{DB_PATH}")

# 创建异步引擎
engine = create_async_engine(
    DB_URL,
    connect_args={"check_same_thread": False},
    echo=False
)

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession
)

# 所有数据表ORM父类（models里所有表继承这个Base）
class Base(DeclarativeBase):
    pass

# FastAPI依赖注入，获取数据库会话
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
