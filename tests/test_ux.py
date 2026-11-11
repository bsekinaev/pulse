"""Проверки пользовательских действий в карточках ПУЛЬС."""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Запускает отдельное приложение для проверки интерфейса."""
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'ui2.sqlite3'}",
        secret_key="ui-test-secure-secret",
        admin_password="ui-test-password",
    )
    with TestClient(app) as client:
        page = client.get("/login")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        response = client.post("/login", data={
            "username": "admin", "password": "ui-test-password", "csrf": csrf,
        }, follow_redirects=False)
        assert response.status_code == 303
        yield client


def test_copy_button_and_script_are_available(client):
    """Кнопка копирования подключает локальный JS и живое уведомление."""
    page = client.get("/employees/1")
    assert page.status_code == 200
    assert 'id="copy-checkin-link"' in page.text
    assert 'id="checkin-url"' in page.text
    assert 'role="status"' in page.text
    assert 'src="/static/clipboard.js"' in page.text
    assert "onclick=" not in page.text

    script = client.get("/static/clipboard.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert "navigator.clipboard.writeText" in script.text
    assert "Ссылка скопирована." in script.text


def test_employee_history_and_issue_sla_are_visible(client):
    """История показывает ответственного, время и статус срока решения."""
    person = client.get("/employees/4")
    assert person.status_code == 200
    assert "Ответственный:" in person.text
    assert "Открыто:" in person.text
    issue = client.get("/issues/1")
    assert issue.status_code == 200
    assert "Решение в течение 24 часов" in issue.text
    assert "Статус SLA" in issue.text
    assert "Минск" in issue.text


def test_personal_link_not_accessible_to_unauthorized_user(client):
    """Закрытый интерфейс не раскрывает ссылку на анкету без сессии."""
    dashboard = client.get("/dashboard")
    csrf = re.search(r'name="csrf" value="([^"]+)"', dashboard.text).group(1)
    assert client.post("/logout", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    assert client.get("/employees/1").status_code == 401
