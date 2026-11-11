"""Read-only аудит структуры и целостности SQLite без вывода содержимого."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

TABLES = ("employees", "checkins", "issues")
REQUIRED_COLUMNS = {
    "employees": {"id", "demo_key", "name", "department", "position", "start_date", "mentor_name"},
    "checkins": {"id", "employee_id", "checkpoint_day", "answers_json", "comment", "submitted_at"},
    "issues": {
        "id", "employee_id", "checkin_id", "category", "status",
        "owner_name", "created_at", "resolved_at", "resolution",
    },
}


def audit_sqlite_readonly(source: Path) -> dict[str, object]:
    """Проверяет базу в режиме read-only, показывая только агрегаты и хеш схемы."""
    source = Path(source).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("Источник не является файлом SQLite")

    uri = source.as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        connection.execute("PRAGMA query_only=ON")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise RuntimeError("Не пройдена проверка целостности SQLite")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise RuntimeError("Обнаружены нарушения внешних ключей")

        schema = list(connection.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ))
        table_names = {name for name, _ in schema}
        if not set(TABLES) <= table_names:
            raise RuntimeError("В базе отсутствуют обязательные таблицы ПУЛЬС")

        for table in TABLES:
            columns = {
                item[1] for item in connection.execute(
                    f'PRAGMA table_info("{table}")'
                )
            }
            if not REQUIRED_COLUMNS[table] <= columns:
                raise RuntimeError(f"В таблице {table} отсутствуют обязательные столбцы")

        revisions = []
        if "alembic_version" in table_names:
            revisions = [
                row[0] for row in connection.execute(
                    "SELECT version_num FROM alembic_version"
                )
            ]
        counts = {
            table: connection.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]
            for table in TABLES
        }
        digest = hashlib.sha256(
            "\n".join(f"{name}:{ddl}" for name, ddl in schema).encode("utf-8")
        ).hexdigest()
        return {
            "integrity": "PASS",
            "foreign_keys": "PASS",
            "schema_sha256": digest,
            "alembic_revision": revisions[0] if len(revisions) == 1 else "none",
            "table_counts": counts,
        }


def main() -> None:
    """Запускает проверку без права обновления SQLite."""
    parser = argparse.ArgumentParser(description="Read-only аудит SQLite ПУЛЬС")
    parser.add_argument("--database", type=Path, required=True)
    arguments = parser.parse_args()

    try:
        report = audit_sqlite_readonly(arguments.database)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        parser.exit(1, f"PULSE_SQLITE_AUDIT=FAIL: {exc}\n")

    print("PULSE_SQLITE_AUDIT=PASS")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
