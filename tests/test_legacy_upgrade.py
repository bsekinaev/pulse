"""Интеграционная репетиция миграции полного набора v0.1.0 без потери данных."""

from datetime import date
import sqlite3

from fastapi.testclient import TestClient

from app.db import Base, make_session_factory
from app.main import create_app
from app.schema import require_current_schema
from scripts.audit_sqlite_readonly import audit_sqlite_readonly
from scripts.backup_sqlite import backup_sqlite
from scripts.migrate_sqlite import migrate_sqlite
from scripts.restore_sqlite import restore_sqlite
from scripts.seed_demo import seed_demo

LEGACY_TABLES = ("employees", "checkins", "issues")


def snapshot_rows(path):
    """Фиксирует строки исходных бизнес-таблиц для точного сравнения после миграции."""
    with sqlite3.connect(path) as db:
        return {
            table: db.execute(f'SELECT * FROM "{table}" ORDER BY id').fetchall()
            for table in LEGACY_TABLES
        }


def test_complete_legacy_dataset_survives_backup_restore_migration(tmp_path, monkeypatch):
    """Все анкеты, обращения и решения сохраняются при переходе v0.1.0 → v0.2.0."""
    original = tmp_path / "pulse-v010.sqlite3"
    backup = tmp_path / "pulse-backup.sqlite3"
    restored = tmp_path / "pulse-restored.sqlite3"

    engine, factory = make_session_factory(f"sqlite:///{original}")
    try:
        Base.metadata.create_all(
            engine, tables=[Base.metadata.tables[name] for name in LEGACY_TABLES]
        )
        with factory() as db:
            assert seed_demo(db, today=date(2026, 11, 11)) == 8
    finally:
        engine.dispose()

    initial = snapshot_rows(original)
    assert len(initial["employees"]) == 8
    assert len(initial["checkins"]) == 4
    assert len(initial["issues"]) == 3

    expected = audit_sqlite_readonly(original)
    assert expected["alembic_revision"] == "none"
    backup_sqlite(original, backup)
    restore_sqlite(backup, restored)
    assert snapshot_rows(restored) == initial

    url = f"sqlite:///{restored}"
    assert migrate_sqlite(url) == "stamp_existing"
    assert snapshot_rows(restored) == initial
    assert snapshot_rows(original) == initial
    assert snapshot_rows(backup) == initial

    with sqlite3.connect(restored) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20261111_0002",
        )
        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"admin_sessions", "login_failures"} <= tables

    assert audit_sqlite_readonly(restored)["foreign_keys"] == "PASS"

    monkeypatch.setenv("APP_ENV", "production")
    app = create_app(
        database_url=url,
        secret_key="production-test-migration-secret-more-than-32",
        admin_password="production-migration-test-password",
    )
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/health").status_code == 200

    # Повторный запуск production не изменяет импортированные бизнес-записи.
    assert snapshot_rows(restored) == initial
