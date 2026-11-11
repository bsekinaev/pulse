"""Проверки диагностического инструмента SQLite без изменения базы."""

import sqlite3

import pytest

from app.db import Base, make_session_factory
from scripts.audit_sqlite_readonly import audit_sqlite_readonly


def test_readonly_audit_returns_aggregates_and_schema_hash(tmp_path):
    """Аудит сообщает только структуру и счётчики, не меняя содержимое."""
    file = tmp_path / "pulse.sqlite3"
    engine, _ = make_session_factory(f"sqlite:///{file}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    before = file.read_bytes()
    result = audit_sqlite_readonly(file)
    assert result["integrity"] == "PASS"
    assert result["foreign_keys"] == "PASS"
    assert result["alembic_revision"] == "none"
    assert result["table_counts"] == {
        "employees": 0, "checkins": 0, "issues": 0,
    }
    assert len(result["schema_sha256"]) == 64
    assert file.read_bytes() == before


def test_readonly_audit_rejects_orphan_record(tmp_path):
    """База с нарушенными связями не получает ложный статус PASS."""
    file = tmp_path / "broken.sqlite3"
    engine, _ = make_session_factory(f"sqlite:///{file}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    with sqlite3.connect(file) as db:
        db.execute(
            "INSERT INTO checkins "
            "(employee_id, checkpoint_day, answers_json, comment, submitted_at) "
            "VALUES (999, 3, '{}', '', '2026-11-11 12:00:00')"
        )
    with pytest.raises(RuntimeError, match="внешних ключей"):
        audit_sqlite_readonly(file)


def test_readonly_audit_rejects_unknown_or_corrupted_database(tmp_path):
    """Нельзя признать успешным аудит постороннего или повреждённого файла."""
    unknown = tmp_path / "unknown.sqlite3"
    with sqlite3.connect(unknown) as db:
        db.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(RuntimeError, match="обязательные таблицы"):
        audit_sqlite_readonly(unknown)

    damaged = tmp_path / "damaged.sqlite3"
    damaged.write_bytes(b"invalid database file")
    with pytest.raises(sqlite3.DatabaseError):
        audit_sqlite_readonly(damaged)


def test_readonly_audit_fails_on_missing_file_without_creating_it(tmp_path):
    """Аудит не создаёт SQLite при отсутствии файла."""
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        audit_sqlite_readonly(missing)
    assert not missing.exists()
