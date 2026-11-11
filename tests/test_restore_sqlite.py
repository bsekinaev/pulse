"""Тесты восстановления SQLite без доступа к рабочему Docker volume."""

import sqlite3
from datetime import date

import pytest

from app.db import make_session_factory
from app.services.onboarding import dashboard_counts
from scripts.backup_sqlite import backup_sqlite
from scripts.restore_sqlite import restore_sqlite
from scripts.seed_demo import seed_demo
from app.db import Base


def test_backup_restore_preserves_full_demo_dataset(tmp_path):
    """После восстановления все сотрудники и состояния проблем сохраняются."""
    live = tmp_path / "live.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    restored = tmp_path / "restored.sqlite3"
    engine, factory = make_session_factory(f"sqlite:///{live}")
    try:
        Base.metadata.create_all(engine)
        with factory() as session:
            seed_demo(session, today=date(2026, 11, 11))
            baseline = dashboard_counts(session)
    finally:
        engine.dispose()
    assert baseline == {"total": 8, "no_answer": 4, "open": 2, "resolved": 1}

    backup_sqlite(live, backup)
    assert restore_sqlite(backup, restored) == restored

    restored_engine, restored_factory = make_session_factory(f"sqlite:///{restored}")
    try:
        with restored_factory() as session:
            assert dashboard_counts(session) == baseline
    finally:
        restored_engine.dispose()

    # Восстановленную копию можно изменять независимо от архива.
    with sqlite3.connect(restored) as db:
        db.execute("UPDATE employees SET name='Проверено' WHERE demo_key='alex'")
    with sqlite3.connect(backup) as db:
        assert db.execute(
            "SELECT name FROM employees WHERE demo_key='alex'"
        ).fetchone() == ("Алексей М.",)


def test_restore_refuses_to_replace_existing_database(tmp_path):
    """Рабочий файл нельзя затереть даже корректной резервной копией."""
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "existing.sqlite3"
    engine, _ = make_session_factory(f"sqlite:///{source}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    destination.write_bytes(b"existing-keep-me")

    with pytest.raises(FileExistsError):
        restore_sqlite(source, destination)
    assert destination.read_bytes() == b"existing-keep-me"


def test_restore_rejects_invalid_backup_without_artifacts(tmp_path):
    """Ошибочная копия не должна создавать восстановленную БД."""
    damaged = tmp_path / "damaged.sqlite3"
    damaged.write_bytes(b"invalid-sqlite")
    target = tmp_path / "restored.sqlite3"
    with pytest.raises(sqlite3.DatabaseError):
        restore_sqlite(damaged, target)
    assert not target.exists()
    assert not list(tmp_path.glob("*.partial"))


def test_restore_does_not_overwrite_own_source(tmp_path):
    """Исходная резервная копия защищена от восстановления поверх себя."""
    path = tmp_path / "backup.sqlite3"
    engine, _ = make_session_factory(f"sqlite:///{path}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    with pytest.raises(ValueError, match="различаться"):
        restore_sqlite(path, path)
