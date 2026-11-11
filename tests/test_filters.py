"""Проверки фильтров и поиска в HR-панели."""

import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Employee
from app.services.filters import employee_state, filter_employees


@pytest.fixture
def logged_in(tmp_path, monkeypatch):
    """Создаёт изолированную авторизованную панель с демоданными."""
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'ui.sqlite3'}",
        secret_key="filter-tests-session-key",
        admin_password="filter-tests-password",
    )
    with TestClient(app) as client:
        page = client.get("/login")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        response = client.post("/login", data={
            "username": "admin", "password": "filter-tests-password", "csrf": csrf,
        }, follow_redirects=False)
        assert response.status_code == 303
        yield client


def test_filter_by_employee_and_department(logged_in):
    """Поиск по имени работает совместно с выбором подразделения."""
    client = logged_in
    result = client.get("/dashboard", params={"q": "ольГА", "department": "Магазин"})
    assert result.status_code == 200
    assert "Ольга Р." in result.text
    assert "Мария К." not in result.text
    assert "Показано 1 из 8" in result.text


def test_filter_by_position_and_open_issues(logged_in):
    """Фильтр состояния показывает сотрудников с открытыми проблемами."""
    client = logged_in
    result = client.get("/dashboard", params={"status": "needs_help"})
    assert result.status_code == 200
    assert "Ольга Р." in result.text
    assert "Елена Т." in result.text
    assert "Павел Н." not in result.text
    assert "Показано 2 из 8" in result.text


def test_filters_keep_global_metrics(logged_in):
    """Фильтрация таблицы не меняет показатели компании."""
    client = logged_in
    before = client.get("/dashboard")
    after = client.get("/dashboard", params={"q": "нет такого сотрудника"})
    assert 'Показано 0 из 8' in after.text
    assert "Сотрудники по выбранным условиям не найдены" in after.text
    assert "<strong>2</strong><small>из них просрочено:" in after.text
    assert "<strong>2</strong><small>из них просрочено:" in before.text


def test_search_escapes_untrusted_query(logged_in):
    """Параметр поиска экранируется и не исполняет HTML пользователя."""
    result = logged_in.get("/dashboard", params={"q": "<script>alert(1)</script>"})
    assert result.status_code == 200
    assert "&lt;script&gt;" in result.text
    assert 'value="<script>' not in result.text


def test_state_predicates_have_disjoint_priority():
    """Статусы исключают друг друга: проблема важнее полученного ответа."""
    today = date(2026, 11, 11)
    person = Employee(id=10, name="Тест", position="Кладовщик",
                      department="Склад", mentor_name="Сергей",
                      demo_key="test", start_date=today - timedelta(days=2))
    assert employee_state(person, {10}, {10: 1}, today) == "needs_help"
    assert employee_state(person, {10}, {}, today) == "answered"
    assert employee_state(person, set(), {}, today) == "awaiting"
    person.start_date = today - timedelta(days=1)
    assert employee_state(person, set(), {}, today) == "not_due"
    assert filter_employees([person], set(), {}, today, state="not_due") == [person]


def test_filter_page_unauthorized(logged_in):
    """Данные доступны только после авторизации."""
    client = logged_in
    dashboard = client.get("/dashboard")
    csrf = re.search(r'name="csrf" value="([^"]+)"', dashboard.text).group(1)
    assert client.post("/logout", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    assert client.get("/dashboard", params={"q": "Ольга"}).status_code == 401
