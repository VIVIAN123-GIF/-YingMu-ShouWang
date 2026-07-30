import asyncio
from sqlalchemy import select, text

from backend.db.database import engine, Base, AsyncSessionLocal
from backend.db.models import (
    DeviceInfo,
    Observation,
    Evidence,
    RiskEvent,
    RiskEventEvidence,
    InterventionResult,
    RiskAlarm,
    SystemConfig,
    WeeklyStat,
    RuleTrace,
)


DEFAULT_CONFIGS = [
    SystemConfig(
        config_key="gait_severity_threshold",
        config_value="0.6",
        desc="步态证据严重度门槛",
    ),
    SystemConfig(
        config_key="mental_long_days",
        config_value="3",
        desc="连续3天心理趋势触发黄色",
    ),
    SystemConfig(
        config_key="fraud_min_evidence_count",
        config_value="3",
        desc="诈骗需三类证据才触发橙色",
    ),
    SystemConfig(
        config_key="stream_max_channel",
        config_value="2",
        desc="最大并发拉流",
    ),
    SystemConfig(
        config_key="intervention_retry_times",
        config_value="1",
        desc="萤石干预仅重试一次",
    ),
    SystemConfig(
        config_key="ruleset_version",
        config_value="ruleset-v1.0",
        desc="固定状态机版本",
    ),
]


async def init_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        columns = {row[1] for row in (await conn.execute(text("PRAGMA table_info(risk_event)"))).all()}
        if "source_mode" not in columns:
            await conn.execute(text("ALTER TABLE risk_event ADD COLUMN source_mode VARCHAR(32) NOT NULL DEFAULT 'MOCK'"))
        if "simulated" not in columns:
            await conn.execute(text("ALTER TABLE risk_event ADD COLUMN simulated BOOLEAN NOT NULL DEFAULT 1"))
        intervention_columns = {row[1] for row in (await conn.execute(
            text("PRAGMA table_info(intervention_result)"))).all()}
        if "source_mode" not in intervention_columns:
            await conn.execute(text(
                "ALTER TABLE intervention_result ADD COLUMN source_mode VARCHAR(32) NOT NULL DEFAULT 'MOCK'"))
        if "simulated" not in intervention_columns:
            await conn.execute(text(
                "ALTER TABLE intervention_result ADD COLUMN simulated BOOLEAN NOT NULL DEFAULT 1"))
    print("所有数据表创建完成：设备/观测/证据/风险事件/干预/原始告警/配置/周报/事件证据关联表")


async def init_default_config() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SystemConfig.config_key))
        existing_keys = set(result.scalars().all())

        to_insert = [cfg for cfg in DEFAULT_CONFIGS if cfg.config_key not in existing_keys]
        if to_insert:
            db.add_all(to_insert)
            await db.commit()

    print("规范配套默认阈值配置写入成功（已自动跳过重复项）")


if __name__ == "__main__":
    asyncio.run(init_tables())
    asyncio.run(init_default_config())
