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
    AgentExplanationJob,
    ForewarningSnapshot,
    SceneCalibrationRecord,
)
from backend.config import ENV_MODE, EZVIZ_CHANNEL_NO, EZVIZ_DEVICE_SERIAL, EZVIZ_RESIDENT_ID, RULESET_VERSION


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
        config_value=RULESET_VERSION,
        desc="当前确定性状态机版本",
    ),
]

SCHEMA_REQUIREMENTS = {
    "forewarning_snapshot": {
        "snapshot_id", "resident_id", "phase", "event_id",
        "intervention_result_id", "source_mode", "simulated",
    },
    "risk_event": {"source_mode", "simulated", "recovery_started_at"},
    "intervention_result": {"risk_after", "resolved", "source_mode", "simulated"},
    "rule_trace": {"previous_status", "next_status", "trace_payload"},
    "scene_calibration": {"scene_config_id", "calibration_payload"},
}


async def assert_schema_ready(conn) -> None:
    tables = {
        row[0]
        for row in (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ))).all()
    }
    missing_tables = sorted(set(SCHEMA_REQUIREMENTS) - tables)
    missing_columns = {}
    for table, required in SCHEMA_REQUIREMENTS.items():
        if table not in tables:
            continue
        columns = {
            row[1]
            for row in (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
        }
        missing = sorted(required - columns)
        if missing:
            missing_columns[table] = missing
    if missing_tables or missing_columns:
        raise RuntimeError(
            f"DATABASE_SCHEMA_INCOMPLETE tables={missing_tables} columns={missing_columns}"
        )


async def init_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        columns = {row[1] for row in (await conn.execute(text("PRAGMA table_info(risk_event)"))).all()}
        if "source_mode" not in columns:
            await conn.execute(text("ALTER TABLE risk_event ADD COLUMN source_mode VARCHAR(32) NOT NULL DEFAULT 'MOCK'"))
        if "simulated" not in columns:
            await conn.execute(text("ALTER TABLE risk_event ADD COLUMN simulated BOOLEAN NOT NULL DEFAULT 1"))
        if "recovery_started_at" not in columns:
            await conn.execute(text("ALTER TABLE risk_event ADD COLUMN recovery_started_at DATETIME"))
        intervention_columns = {row[1] for row in (await conn.execute(
            text("PRAGMA table_info(intervention_result)"))).all()}
        if "source_mode" not in intervention_columns:
            await conn.execute(text(
                "ALTER TABLE intervention_result ADD COLUMN source_mode VARCHAR(32) NOT NULL DEFAULT 'MOCK'"))
        if "simulated" not in intervention_columns:
            await conn.execute(text(
                "ALTER TABLE intervention_result ADD COLUMN simulated BOOLEAN NOT NULL DEFAULT 1"))
        trace_columns = {row[1] for row in (await conn.execute(
            text("PRAGMA table_info(rule_trace)"))).all()}
        if "previous_status" not in trace_columns:
            await conn.execute(text("ALTER TABLE rule_trace ADD COLUMN previous_status VARCHAR(16)"))
        if "next_status" not in trace_columns:
            await conn.execute(text("ALTER TABLE rule_trace ADD COLUMN next_status VARCHAR(16)"))
        if "trace_payload" not in trace_columns:
            await conn.execute(text("ALTER TABLE rule_trace ADD COLUMN trace_payload TEXT"))
        asset_columns = {row[1] for row in (await conn.execute(
            text("PRAGMA table_info(asset)"))).all()}
        asset_migrations = {
            "device_ref": "VARCHAR(128)",
            "device_model": "VARCHAR(64)",
            "camera_position_id": "VARCHAR(128)",
            "authorization_status": "VARCHAR(32) NOT NULL DEFAULT 'PENDING'",
            "authorization_record_id": "VARCHAR(128)",
            "retention_until": "DATETIME",
            "content_sha256": "VARCHAR(64)",
            "content_type": "VARCHAR(128)",
            "byte_size": "BIGINT",
            "storage_key": "VARCHAR(256)",
        }
        for column, definition in asset_migrations.items():
            if column not in asset_columns:
                await conn.execute(text(f"ALTER TABLE asset ADD COLUMN {column} {definition}"))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_asset_content_sha256 ON asset(content_sha256)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_asset_storage_key "
            "ON asset(storage_key) WHERE storage_key IS NOT NULL"
        ))
        alarm_task_columns = {row[1] for row in (await conn.execute(
            text("PRAGMA table_info(alarm_processing_task)"))).all()}
        alarm_task_migrations = {
            "capture_completed_at": "DATETIME",
            "algorithm_attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "algorithm_started_at": "DATETIME",
            "algorithm_completed_at": "DATETIME",
            "algorithm_summary": "TEXT",
            "error_stage": "VARCHAR(32)",
        }
        for column, definition in alarm_task_migrations.items():
            if column not in alarm_task_columns:
                await conn.execute(text(
                    f"ALTER TABLE alarm_processing_task ADD COLUMN {column} {definition}"
                ))
        await assert_schema_ready(conn)
    print("所有数据表创建完成：设备/观测/证据/预警快照/风险事件/干预/原始告警/配置/周报/事件证据关联表")


async def init_default_config() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SystemConfig.config_key))
        existing_keys = set(result.scalars().all())

        to_insert = [cfg for cfg in DEFAULT_CONFIGS if cfg.config_key not in existing_keys]
        if to_insert:
            db.add_all(to_insert)
            await db.commit()

        ruleset_config = (await db.execute(select(SystemConfig).where(
            SystemConfig.config_key == "ruleset_version"
        ))).scalar_one_or_none()
        if ruleset_config and ruleset_config.config_value != RULESET_VERSION:
            ruleset_config.config_value = RULESET_VERSION
            await db.commit()

        if ENV_MODE == "live" and EZVIZ_DEVICE_SERIAL and EZVIZ_RESIDENT_ID:
            device = (await db.execute(select(DeviceInfo).where(
                DeviceInfo.device_sn == EZVIZ_DEVICE_SERIAL))).scalar_one_or_none()
            if not device:
                db.add(DeviceInfo(
                    resident_id=EZVIZ_RESIDENT_ID,
                    device_sn=EZVIZ_DEVICE_SERIAL,
                    channel_no=EZVIZ_CHANNEL_NO,
                    device_name="ezviz-live-device",
                    is_online=False,
                    adapter_mode="LIVE_DEVICE",
                ))
                await db.commit()

    print("规范配套默认阈值配置写入成功（已自动跳过重复项）")


if __name__ == "__main__":
    asyncio.run(init_tables())
    asyncio.run(init_default_config())
