"""Сквозные проверки жизненного цикла адаптации."""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import CheckIn, Employee, Issue
from app.services.onboarding import dashboard_counts


@pytest.fixture
def setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}",
        secret_key="testing-secret-key-safely-isolated-from-prod",
        admin_password="test-secure-password",
    )
    with TestClient(app) as client:
        yield client, app


def login(client):
    page = client.get("/login")
    assert page.status_code == 200
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    response = client.post("/login", data={
        "username": "admin", "password": "test-secure-password", "csrf": csrf,
    }, follow_redirects=False)
    assert response.status_code == 303
    return csrf


def alex_url(client):
    login(client)
    page = client.get("/employees/1")
    assert page.status_code == 200
    match = re.search(r'href="(http://testserver/checkin/[^"]+)"', page.text)
    assert match, page.text[:500]
    return match.group(1)


def test_health_and_seed(setup_app):
    client, app = setup_app
    assert client.get("/health").json() == {"status": "ok"}
    with app.state.sessions() as db:
        assert dashboard_counts(db) == {
            "total": 8, "no_answer": 4, "open": 2, "resolved": 1,
        }


def test_protected_dashboard_and_login(setup_app):
    client, _ = setup_app
    assert client.get("/dashboard").status_code == 401
    bad_page = client.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', bad_page.text).group(1)
    failed = client.post("/login", data={
        "username": "admin", "password": "wrong", "csrf": csrf,
    })
    assert failed.status_code == 401
    login(client)
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "Первые дни под контролем" in page.text


def test_negative_checkin_is_atomic_and_idempotent(setup_app):
    client, app = setup_app
    url = alex_url(client)
    form = client.get(url)
    assert form.status_code == 200
    payload = {
        "equipment": "no", "instructions": "yes", "support": "no",
        "comment": "Не выдали терминал, не могу найти наставника.",
    }
    created = client.post(url, data=payload, follow_redirects=False)
    assert created.status_code == 303
    again = client.post(url, data=payload, follow_redirects=False)
    assert again.status_code == 303
    with app.state.sessions() as db:
        person = db.scalar(select(Employee).where(Employee.demo_key == "alex"))
        checkins = db.scalars(select(CheckIn).where(CheckIn.employee_id == person.id)).all()
        issues = db.scalars(select(Issue).where(Issue.employee_id == person.id)).all()
        assert len(checkins) == 1
        assert {item.category for item in issues} == {"equipment", "support"}
        assert dashboard_counts(db)["open"] == 4


def test_positive_checkin_does_not_create_issue(setup_app):
    client, app = setup_app
    login(client)
    person = None
    with app.state.sessions() as db:
        person = db.scalar(select(Employee).where(Employee.demo_key == "igor"))
        employee_id = person.id
    page = client.get(f"/employees/{employee_id}")
    url = re.search(r'href="(http://testserver/checkin/[^"]+)"', page.text).group(1)
    result = client.post(url, data={
        "equipment": "yes", "instructions": "yes", "support": "yes", "comment": "",
    }, follow_redirects=False)
    assert result.status_code == 303
    with app.state.sessions() as db:
        assert db.scalars(select(Issue).where(Issue.employee_id == employee_id)).all() == []
        assert db.scalar(select(CheckIn).where(CheckIn.employee_id == employee_id))


def test_invalid_answers_do_not_write(setup_app):
    client, app = setup_app
    url = alex_url(client)
    response = client.post(url, data={
        "equipment": "bad", "instructions": "yes", "support": "yes", "comment": "",
    })
    assert response.status_code == 422
    with app.state.sessions() as db:
        assert db.scalar(select(CheckIn).where(CheckIn.employee_id == 1)) is None


def test_bad_token_is_rejected(setup_app):
    client, _ = setup_app
    assert client.get("/checkin/forged-token").status_code == 404
    assert client.post("/checkin/forged-token", data={
        "equipment": "no", "instructions": "yes", "support": "yes",
    }).status_code == 404


def test_closing_issue_requires_admin_and_csrf(setup_app):
    client, app = setup_app
    unauth = client.post("/issues/1/resolve", data={"resolution": "Терминал выдан", "csrf": "x"})
    assert unauth.status_code == 401
    login(client)
    bad_csrf = client.post("/issues/1/resolve", data={
        "resolution": "Терминал выдан", "csrf": "bad",
    })
    assert bad_csrf.status_code == 403
    issue_page = client.get("/issues/1")
    csrf = re.search(r'name="csrf" value="([^"]+)"', issue_page.text).group(1)
    short = client.post("/issues/1/resolve", data={"resolution": "ok", "csrf": csrf})
    assert short.status_code == 422
    resolved = client.post("/issues/1/resolve", data={
        "resolution": "График смен согласован с руководителем", "csrf": csrf,
    }, follow_redirects=False)
    assert resolved.status_code == 303
    repeated = client.post("/issues/1/resolve", data={
        "resolution": "Другое решение, не должно сохраниться", "csrf": csrf,
    })
    assert repeated.status_code == 409
    with app.state.sessions() as db:
        issue = db.get(Issue, 1)
        assert issue.status == "resolved"
        assert issue.resolution == "График смен согласован с руководителем"
        assert issue.resolved_at is not None


def test_demo_seed_is_idempotent(setup_app):
    client, app = setup_app
    from scripts.seed_demo import seed_demo
    with app.state.sessions() as db:
        first = dashboard_counts(db)
        assert seed_demo(db) == 0
        assert dashboard_counts(db) == first


def test_missing_resources_and_csrf_login(setup_app):
    client, _ = setup_app
    assert client.get("/employees/999").status_code == 401
    assert client.post("/login", data={
        "username": "admin", "password": "test-secure-password", "csrf": "invalid",
    }).status_code == 403
    login(client)
    assert client.get("/employees/999").status_code == 404
    assert client.get("/issues/999").status_code == 404

def test_css_link_works_behind_https_proxy(setup_app):
    """Стили загружаются по относительному пути, даже если ASGI видит HTTP."""
    client, _ = setup_app
    response = client.get("/login", headers={"host": "pulse.bsekinaev.ru"})
    assert response.status_code == 200
    assert 'href="/static/styles.css?v=2"' in response.text
    assert "http://pulse.bsekinaev.ru/static" not in response.text
    stylesheet = client.get("/static/styles.css")
    assert stylesheet.status_code == 200
    assert "text/css" in stylesheet.headers["content-type"]
    assert ".metrics" in stylesheet.text


def test_public_employee_link_is_https(tmp_path, monkeypatch):
    """Персональная ссылка остаётся HTTPS за обратным прокси."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://pulse.bsekinaev.ru")
    application = create_app(
        database_url=f"sqlite:///{tmp_path / 'prod-test.sqlite3'}",
        secret_key="a-secure-production-test-secret-more-than-32",
        admin_password="password-for-production-test",
    )
    with TestClient(application, base_url="https://testserver") as client:
        page = client.get("/login")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        signed_in = client.post("/login", data={
            "username": "admin", "password": "password-for-production-test",
            "csrf": csrf,
        }, follow_redirects=False)
        assert signed_in.status_code == 303
        employee = client.get("/employees/1")
        assert employee.status_code == 200
        assert 'value="https://pulse.bsekinaev.ru/checkin/' in employee.text
        assert 'href="https://pulse.bsekinaev.ru/checkin/' in employee.text
