"""Проверка управляемой схемы перед запуском production ПУЛЬС."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parent.parent


def require_current_schema(engine: Engine) -> str:
    """Не запускает production без однозначной актуальной миграции Alembic."""
    config = Config(str(ROOT / "alembic.ini"))
    required = ScriptDirectory.from_config(config).get_current_head()
    if not required:
        raise RuntimeError("У Alembic отсутствует единственная головная ревизия")

    with engine.connect() as connection:
        if not inspect(connection).has_table("alembic_version"):
            raise RuntimeError(
                "Схема SQLite не подготовлена: требуется миграция Alembic"
            )
        revisions = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalars().all()
        if revisions != [required]:
            raise RuntimeError(
                "Версия SQLite не соответствует приложению: требуется миграция Alembic"
            )
    return required
