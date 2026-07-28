"""Validate the delivery database schema without reading business records."""

import os
import sqlite3


REQUIRED_TABLES = {
    "asset", "device_info", "evidence", "intervention_result", "observation",
    "risk_alarm", "risk_event", "system_config", "weekly_stat",
}


def main() -> int:
    path = os.getenv("YINGMU_DB_PATH", "ezviz_system.db")
    connection = sqlite3.connect(path)
    try:
        names = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        connection.close()
    missing = sorted(REQUIRED_TABLES - names)
    if missing:
        print(f"database_validation=FAILED missing={','.join(missing)}")
        return 1
    print(f"database_validation=SUCCESS table_count={len(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
