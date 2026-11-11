"""Проверки атомарности и целостности резервных копий SQLite."""

import os
import sqlite3
import stat

import pytest

from scripts.backup_sqlite import backup_sqlite


def create_pulse_database(path):
    """Создаёт небольшую проверочную БД, соответствующую основным таблицам."""
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE checkins (
                id INTEGER PRIMARY KEY,
                employee_id INTEGER REFERENCES employees(id)
            );
            CREATE TABLE issues (
                id INTEGER PRIMARY KEY,
                checkin_id INTEGER REFERENCES checkins(id)
            );
            INSERT INTO employees (id, name) VALUES (1, 'Алексей');
            INSERT INTO checkins (id, employee_id) VALUES (1, 1);
            INSERT INTO issues (id, checkin_id) VALUES (1, 1);
        """)


def test_backup_is_consistent_and_private(tmp_path):
    """Созданная копия содержит данные и доступна только владельцу."""
    source = tmp_path / "live.sqlite3"
    destination = tmp_path / "backup.sqlite3"
    create_pulse_database(source)

    result = backup_sqlite(source, destination)
    assert result == destination
    assert source.exists()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600

    with sqlite3.connect(destination) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT name FROM employees WHERE id=1").fetchone() == ("Алексей",)
        assert db.execute("SELECT count(*) FROM issues").fetchone()[0] == 1


def test_backup_refuses_to_replace_existing_file(tmp_path):
    """Предыдущая резервная копия не должна быть перезаписана."""
    source = tmp_path / "live.sqlite3"
    destination = tmp_path / "backup.sqlite3"
    create_pulse_database(source)
    destination.write_text("не перезаписывать", encoding="utf-8")

    with pytest.raises(FileExistsError):
        backup_sqlite(source, destination)

    assert destination.read_text(encoding="utf-8") == "не перезаписывать"
    assert not list(tmp_path.glob("*.partial"))


def test_backup_rejects_empty_and_corrupted_databases(tmp_path):
    """Неподходящая БД не выдаётся за успешную копию ПУЛЬС."""
    empty = tmp_path / "empty.sqlite3"
    with sqlite3.connect(empty) as db:
        db.execute("CREATE TABLE other (id INTEGER)")

    with pytest.raises(RuntimeError, match="обязательных таблиц"):
        backup_sqlite(empty, tmp_path / "empty-backup.sqlite3")
    assert not (tmp_path / "empty-backup.sqlite3").exists()

    corrupted = tmp_path / "corrupted.sqlite3"
    corrupted.write_bytes(b"this is not a SQLite database")
    with pytest.raises(sqlite3.DatabaseError):
        backup_sqlite(corrupted, tmp_path / "corrupted-backup.sqlite3")
    assert not (tmp_path / "corrupted-backup.sqlite3").exists()


def test_backup_rejects_missing_source_and_same_path(tmp_path):
    """Нельзя копировать несуществующий файл или перезаписать исходник."""
    source = tmp_path / "live.sqlite3"
    with pytest.raises(FileNotFoundError):
        backup_sqlite(source, tmp_path / "backup.sqlite3")

    create_pulse_database(source)
    with pytest.raises(ValueError, match="различаться"):
        backup_sqlite(source, source)
