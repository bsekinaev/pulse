"""Проверка, что production не создаёт схему в обход Alembic."""

import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.db import Base
from app.main import create_app
from scripts.migrate_sqlite import migrate_sqlite


def make_app(url: str):
    """Возвращает тестовое production-приложение с фиксированными секретами."""
    return create_app(
        database_url=url,
        secret_key="production-gate-test-secret-longer-than-32-characters",
        admin_password="production-gate-test-password",
        seed=True,
    )


def test_production_refuses_database_without_alembic(tmp_path, monkeypatch):
    """Запуск запрещён, когда миграция не выполнялась."""
    monkeypatch.setenv("APP_ENV", "production")
    url = f"sqlite:///{tmp_path / 'unmigrated.sqlite3'}"
    app = make_app(url)
    with pytest.raises(RuntimeError, match="требуется миграция Alembic"):
        with TestClient(app):
            pass


def test_production_refuses_legacy_v010_database(tmp_path, monkeypatch):
    """База v0.1.0 требует безопасной миграции, но не пересоздаётся."""
    monkeypatch.setenv("APP_ENV", "production")
    path = tmp_path / "legacy.sqlite3"
    url = f"sqlite:///{path}"
    engine = create_engine(url)
    Base.metadata.create_all(
        engine,
        tables=[Base.metadata.tables[name] for name in ("employees", "checkins", "issues")],
    )
    engine.dispose()
    with pytest.raises(RuntimeError, match="требуется миграция Alembic"):
        with TestClient(make_app(url)):
            pass
    with sqlite3.connect(path) as db:
        assert "alembic_version" not in {
            row[0] for row in db.execute("SELECT name FROM sqlite_master")
        }


def test_production_starts_after_controlled_migration(tmp_path, monkeypatch):
    """После Alembic upgrade приложение стартует и создаёт только демоданные."""
    monkeypatch.setenv("APP_ENV", "production")
    path = tmp_path / "migrated.sqlite3"
    url = f"sqlite:///{path}"
    assert migrate_sqlite(url) == "upgrade"
    with TestClient(make_app(url), base_url="https://testserver") as client:
        assert client.get("/health").json() == {"status": "ok"}
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM employees").fetchone() == (8,)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20261111_0002",
        )
