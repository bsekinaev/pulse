"""Проверки атомарного закрытия обращения несколькими сессиями."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Issue
from app.services.onboarding import AlreadyResolved, resolve_issue


def test_stale_second_session_cannot_replace_resolution(tmp_path, monkeypatch):
    """Две сессии читают одну проблему, но сохранить решение может одна."""
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'two_admins.sqlite3'}",
        secret_key="two-admins-test-secret",
        admin_password="two-admins-test-password",
    )
    with TestClient(app):
        with app.state.sessions() as first, app.state.sessions() as second:
            issue_from_first = first.get(Issue, 1)
            issue_from_second = second.get(Issue, 1)
            assert issue_from_first.status == issue_from_second.status == "open"

            resolved = resolve_issue(
                first, issue_from_first,
                "Первый администратор согласовал и выдал терминал",
            )
            original_time = resolved.resolved_at
            assert resolved.status == "resolved"

            with pytest.raises(AlreadyResolved, match="уже закрыта"):
                resolve_issue(
                    second, issue_from_second,
                    "Второй администратор пытается переписать решение",
                )

        with app.state.sessions() as db:
            stored = db.get(Issue, 1)
            assert stored.status == "resolved"
            assert stored.resolution == (
                "Первый администратор согласовал и выдал терминал"
            )
            assert stored.resolved_at == original_time


def test_stale_closed_issue_can_not_be_reopened_via_service(tmp_path, monkeypatch):
    """Повторная операция не изменяет исходные данные закрытого обращения."""
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'closed.sqlite3'}",
        secret_key="closed-test-secret",
        admin_password="closed-test-password",
    )
    with TestClient(app):
        with app.state.sessions() as db:
            issue = db.get(Issue, 3)
            assert issue.status == "resolved"
            expected_resolution = issue.resolution
            with pytest.raises(AlreadyResolved):
                resolve_issue(db, issue, "Попытка повторного закрытия обращения")
        with app.state.sessions() as db:
            assert db.get(Issue, 3).resolution == expected_resolution
