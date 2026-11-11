"""Безопасное принятие исходной базы v0.1.0 под управление Alembic."""

from __future__ import annotations

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.db import Base
from app import models  # ORM-таблицы должны быть зарегистрированы.

ROOT = Path(__file__).resolve().parent.parent
BASE_REVISION = "20261111_0001"
# Снимок исходной схемы не должен меняться при добавлении таблиц v0.2.0.
BASE_TABLE_NAMES = {"employees", "checkins", "issues"}


def _validate_existing_schema(inspector) -> None:
    """Отказывает в маркировке, если структура не соответствует v0.1.0."""
    expected = BASE_TABLE_NAMES
    actual = set(inspector.get_table_names()) - {"alembic_version"}
    if actual != expected:
        raise ValueError(f"Несовместимый набор таблиц: {sorted(actual)}")

    for name in sorted(BASE_TABLE_NAMES):
        table = Base.metadata.tables[name]
        expected_columns = {column.name for column in table.columns}
        actual_columns = {column["name"] for column in inspector.get_columns(name)}
        if actual_columns != expected_columns:
            raise ValueError(f"Несовместимые поля таблицы {name}")

        expected_foreign_keys = {
            (tuple(fk.column_keys), fk.elements[0].column.table.name)
            for fk in table.foreign_key_constraints
        }
        actual_foreign_keys = {
            (tuple(fk["constrained_columns"]), fk["referred_table"])
            for fk in inspector.get_foreign_keys(name)
        }
        if actual_foreign_keys != expected_foreign_keys:
            raise ValueError(f"Несовместимые внешние ключи таблицы {name}")

        expected_uniques = {
            tuple(constraint.columns.keys())
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        actual_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(name)
        }
        if not expected_uniques <= actual_uniques:
            raise ValueError(f"Несовместимые уникальные ограничения таблицы {name}")


def migrate_sqlite(database_url: str) -> str:
    """Мигрирует пустую БД или принимает строго совместимую существующую.

    Для уже существующей схемы v0.1.0 запрещены операции удаления таблиц.
    Новую базу Alembic создаёт через начальную миграцию, а старую только
    маркирует после сверки структуры. Перед запуском на VPS нужен backup.
    """
    if not database_url.startswith("sqlite:///"):
        raise ValueError("На данном этапе поддерживается только SQLite URL")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        names = set(inspector.get_table_names())
        if names and "alembic_version" not in names:
            _validate_existing_schema(inspector)
            # Не маркируем базу как совместимую, пока данные нарушают связи.
            with engine.connect() as connection:
                integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar()
                if integrity != "ok":
                    raise ValueError("Повреждена целостность существующей SQLite-базы")
                foreign_keys = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if foreign_keys:
                    raise ValueError("Найдены нарушения внешних ключей в SQLite-базе")
            action = "stamp_existing"
        else:
            action = "upgrade"
    finally:
        engine.dispose()

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    if action == "stamp_existing":
        command.stamp(config, BASE_REVISION)
    command.upgrade(config, "head")
    return action


def main() -> None:
    """Запускает контролируемую миграцию по явно заданному адресу БД."""
    parser = argparse.ArgumentParser(description="Перевести SQLite ПУЛЬС под Alembic")
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    action = migrate_sqlite(args.database_url)
    print(f"PULSE_MIGRATION=PASS action={action}")


if __name__ == "__main__":
    main()
