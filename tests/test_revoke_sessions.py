"""Контроль массового отзыва сессий и очистки старых попыток входа."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import LoginFailure
from app.security import LOGIN_WINDOW, register_failed_login, source_digest
from scripts.revoke_admin_sessions import revoke_all_sessions


def test_revoke_all_sessions_invalidates_signed_cookies(tmp_path, monkeypatch):
    """Все ранее выданные cookie отклоняются сразу после отзыва."""
    monkeypatch.setenv("APP_ENV", "test")
    url = f"sqlite:///{tmp_path / 'auth.sqlite3'}"
    app = create_app(
        database_url=url, secret_key="revoke-test-secret-32-bytes-plus",
        admin_password="revoke-password",
    )
    with TestClient(app) as first, TestClient(app) as second:
        for client in (first, second):
            page = client.get("/login")
            csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
            signed_in = client.post("/login", data={
                "username": "admin", "password": "revoke-password", "csrf": csrf,
            }, follow_redirects=False)
            assert signed_in.status_code == 303
            assert client.get("/dashboard").status_code == 200

        assert revoke_all_sessions(url) == 2
        assert first.get("/dashboard").status_code == 401
        assert second.get("/dashboard").status_code == 401
        assert revoke_all_sessions(url) == 0

        # После отзыва новая авторизация по актуальному паролю разрешена.
        page = first.get("/login")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        result = first.post("/login", data={
            "username": "admin", "password": "revoke-password", "csrf": csrf,
        }, follow_redirects=False)
        assert result.status_code == 303
        assert first.get("/dashboard").status_code == 200


def test_old_failed_logins_are_pruned(tmp_path, monkeypatch):
    """Регулярная проверка удаляет просроченные записи без роста таблицы."""
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'limit.sqlite3'}",
        secret_key="prune-test-secret-32-bytes-plus",
        admin_password="prune-password",
    )
    with TestClient(app):
        with app.state.sessions() as db:
            db.add(LoginFailure(
                source_hash="old",
                attempted_at=datetime.now(timezone.utc) - LOGIN_WINDOW * 3,
            ))
            db.commit()
            register_failed_login(db, source_digest("active", "secret"))
            assert len(db.scalars(select(LoginFailure)).all()) == 1
