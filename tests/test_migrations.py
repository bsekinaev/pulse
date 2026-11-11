"""Проверки совместимости миграции SQLite и сохранности записей."""

import sqlite3
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, make_session_factory
from app.models import CheckIn, Employee
from scripts.migrate_sqlite import BASE_REVISION, migrate_sqlite


def test_new_database_created_with_alembic(tmp_path):
    """Начальная миграция создаёт все таблицы новой базы."""
    path = tmp_path / "empty.sqlite3"
    url = f"sqlite:///{path}"

    assert migrate_sqlite(url) == "upgrade"
    with sqlite3.connect(path) as db:
        names = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"employees", "checkins", "issues", "alembic_version"} <= names
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20261111_0002",
        )


def test_existing_v010_schema_stamped_without_data_loss(tmp_path):
    """Структура v0.1.0 принимается без удаления и изменения сотрудников."""
    path = tmp_path / "existing.sqlite3"
    url = f"sqlite:///{path}"
    engine = create_engine(url)
    Base.metadata.create_all(
        engine,
        tables=[Base.metadata.tables[name] for name in ("employees", "checkins", "issues")],
    )
    with Session(engine) as db:
        db.add(Employee(
            demo_key="test", name="Алексей", department="Склад",
            position="Кладовщик", start_date=date(2026, 11, 11),
            mentor_name="Сергей",
        ))
        db.commit()
    engine.dispose()

    assert migrate_sqlite(url) == "stamp_existing"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM employees").fetchone() == ("Алексей",)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20261111_0002",
        )
        assert db.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE name IN ('login_failures', 'admin_sessions')"
        ).fetchone() == (2,)


def test_incompatible_existing_schema_rejected(tmp_path):
    """Некорректную существующую базу нельзя маркировать как совместимую."""
    path = tmp_path / "wrong.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY)")

    with pytest.raises(ValueError, match="Несовместимый"):
        migrate_sqlite(f"sqlite:///{path}")

    with sqlite3.connect(path) as db:
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "alembic_version" not in tables


def test_second_migration_keeps_data(tmp_path):
    """Повторный запуск не создаёт вторую схему и не теряет данные."""
    path = tmp_path / "repeat.sqlite3"
    url = f"sqlite:///{path}"
    migrate_sqlite(url)
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO employees (demo_key,name,department,position,start_date,mentor_name)"
            " VALUES ('x','Анна','Магазин','Кассир','2026-11-11','Сергей')"
        )
    assert migrate_sqlite(url) == "upgrade"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM employees").fetchone() == (1,)


def test_application_rejects_orphan_checkin(tmp_path):
    """Каждое подключение приложения проверяет внешние ключи SQLite."""
    path = tmp_path / "protected.sqlite3"
    engine, session_factory = make_session_factory(f"sqlite:///{path}")
    try:
        Base.metadata.create_all(engine)
        with session_factory() as db:
            db.add(CheckIn(employee_id=9999, checkpoint_day=3, answers_json="{}"))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
    finally:
        engine.dispose()


def test_existing_orphan_data_refused_before_alembic_stamp(tmp_path):
    """Alembic не маркирует старую базу с повреждёнными связями."""
    path = tmp_path / "orphan.sqlite3"
    url = f"sqlite:///{path}"
    engine = create_engine(url)
    Base.metadata.create_all(
        engine,
        tables=[Base.metadata.tables[name] for name in ("employees", "checkins", "issues")],
    )
    engine.dispose()
    # Имитируем существующее подключение v0.1.0 без PRAGMA foreign_keys.
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO checkins "
            "(employee_id, checkpoint_day, answers_json, comment, submitted_at) "
            "VALUES (9999, 3, '{}', '', '2026-11-11 12:00:00')"
        )
    with pytest.raises(ValueError, match="внешних ключей"):
        migrate_sqlite(url)
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT count(*) FROM sqlite_master WHERE name = 'alembic_version'"
        ).fetchone()[0] == 0
