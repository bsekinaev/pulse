"""Негативные сценарии защиты входа, токенов и сессий ПУЛЬС."""

import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import AdminSession, LoginFailure
from app.security import (
    LOGIN_LIMIT, blocked_seconds, client_source, source_digest,
    parse_trusted_proxy_hosts,
)


@pytest.fixture
def secure_app(tmp_path, monkeypatch):
    """Подготавливает изолированную базу и повторяемый секрет для проверки входа."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("PULSE_TRUSTED_PROXY_CIDRS", raising=False)
    secret = "security-test-secret-long-enough-for-hmac"
    password = "demo-secure-password"
    url = f"sqlite:///{tmp_path / 'security.sqlite3'}"
    app = create_app(database_url=url, secret_key=secret, admin_password=password)
    with TestClient(app) as client:
        yield client, app, url, secret, password


def csrf_for(client):
    """Извлекает CSRF из формы без изменения сессии."""
    response = client.get("/login")
    assert response.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


def attempt(client, csrf, username, password):
    """Отправляет форму входа без автоматического перехода."""
    return client.post("/login", data={
        "csrf": csrf, "username": username, "password": password,
    }, follow_redirects=False)


def test_five_failed_logins_block_subsequent_attempts(secure_app):
    """Пять ошибок блокируют и неверный, и правильный пароль на 15 минут."""
    client, app, _, secret, password = secure_app
    csrf = csrf_for(client)
    for _ in range(LOGIN_LIMIT):
        assert attempt(client, csrf, "admin", "wrong").status_code == 401
    blocked = attempt(client, csrf, "admin", "wrong")
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 900
    assert attempt(client, csrf, "admin", password).status_code == 429

    with app.state.sessions() as db:
        records = db.scalars(select(LoginFailure)).all()
        assert len(records) == LOGIN_LIMIT
        assert all(len(item.source_hash) == 64 for item in records)
        assert all("testclient" not in item.source_hash for item in records)
        key = source_digest("testclient", secret)
        assert blocked_seconds(db, key) > 0


def test_wrong_username_does_not_reveal_account(secure_app):
    """Ошибки логина и пароля не должны выдавать существование администратора."""
    client, _, _, _, _ = secure_app
    csrf = csrf_for(client)
    first = attempt(client, csrf, "unknown", "wrong")
    second = attempt(client, csrf, "admin", "wrong")
    assert first.status_code == second.status_code == 401
    assert "Неверный логин или пароль" in first.text
    assert "Неверный логин или пароль" in second.text


def test_counter_is_reset_after_successful_login(secure_app):
    """Успешная авторизация удаляет накопившиеся неудачные попытки."""
    client, app, _, _, password = secure_app
    csrf = csrf_for(client)
    for _ in range(3):
        assert attempt(client, csrf, "admin", "bad").status_code == 401
    assert attempt(client, csrf, "admin", password).status_code == 303
    assert client.get("/dashboard").status_code == 200
    with app.state.sessions() as db:
        assert db.scalars(select(LoginFailure)).all() == []


def test_login_limit_survives_application_restart(secure_app):
    """Блокировка хранится в SQLite, а не только в памяти процесса."""
    client, _, url, secret, password = secure_app
    csrf = csrf_for(client)
    for _ in range(LOGIN_LIMIT):
        assert attempt(client, csrf, "admin", "bad").status_code == 401

    second_app = create_app(
        database_url=url, secret_key=secret, admin_password=password,
    )
    with TestClient(second_app) as second:
        second_csrf = csrf_for(second)
        assert attempt(second, second_csrf, "admin", password).status_code == 429


def test_logout_revokes_replayed_session_cookie(secure_app):
    """Выход запрещает повторный вход по ранее скопированной cookie."""
    client, app, _, _, password = secure_app
    csrf = csrf_for(client)
    assert attempt(client, csrf, "admin", password).status_code == 303
    cookie = client.cookies.get("pulse_admin")
    assert cookie
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    logout_csrf = re.search(
        r'name="csrf" value="([^"]+)"', dashboard.text
    ).group(1)
    logout = client.post(
        "/logout", data={"csrf": logout_csrf}, follow_redirects=False
    )
    assert logout.status_code == 303
    client.cookies.set("pulse_admin", cookie)
    assert client.get("/dashboard").status_code == 401
    with app.state.sessions() as db:
        stored = db.scalars(select(AdminSession)).all()
        assert len(stored) == 1
        assert stored[0].revoked_at is not None


def test_expired_server_session_is_denied(secure_app):
    """Подписанная cookie не даёт доступ после серверного истечения сессии."""
    client, app, _, _, password = secure_app
    csrf = csrf_for(client)
    assert attempt(client, csrf, "admin", password).status_code == 303
    assert client.get("/dashboard").status_code == 200
    with app.state.sessions() as db:
        stored = db.scalars(select(AdminSession)).first()
        stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.get("/dashboard").status_code == 401


def test_spoofed_proxy_headers_not_trusted(secure_app):
    """Без доверенного peer внешний X-Forwarded-For не меняет ключ лимита."""
    client, _, _, _, _ = secure_app
    csrf = csrf_for(client)
    for i in range(LOGIN_LIMIT):
        result = client.post("/login", headers={"X-Forwarded-For": f"203.0.113.{i+1}"}, data={
            "csrf": csrf, "username": "admin", "password": "bad",
        })
        assert result.status_code == 401
    blocked = client.post("/login", headers={"X-Forwarded-For": "198.51.100.14"}, data={
        "csrf": csrf, "username": "admin", "password": "bad",
    })
    assert blocked.status_code == 429


def test_proxy_header_accepted_only_from_explicit_subnet():
    """Доверенная подсеть разрешает X-Forwarded-For, посторонняя — нет."""
    request = SimpleNamespace(
        client=SimpleNamespace(host="172.22.0.3"),
        headers={"x-forwarded-for": "203.0.113.21, 172.22.0.3"},
    )
    assert client_source(request) == "172.22.0.3"
    # Цепочку заголовков не принимаем даже от доверенного peer.
    assert client_source(request, ("172.22.0.3/32",)) == "172.22.0.3"
    request.headers = {"x-forwarded-for": "203.0.113.21"}
    assert client_source(request, ("172.22.0.3/32",)) == "203.0.113.21"
    assert client_source(request, ("172.22.0.4/32",)) == "172.22.0.3"
    request.headers = {"x-forwarded-for": "not-an-ip"}
    assert client_source(request, ("172.22.0.3/32",)) == "172.22.0.3"


def test_security_headers_and_no_inline_handlers(secure_app):
    """Личные страницы запрещают кеш, iframe и утечку токена через referer."""
    client, _, _, _, password = secure_app
    login = client.get("/login")
    assert login.headers["cache-control"] == "no-store"
    assert login.headers["referrer-policy"] == "no-referrer"
    assert login.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in login.headers["content-security-policy"]
    assert "script-src 'self'" in login.headers["content-security-policy"]
    assert login.headers["x-content-type-options"] == "nosniff"

    csrf = csrf_for(client)
    assert attempt(client, csrf, "admin", password).status_code == 303
    employee = client.get("/employees/1")
    assert employee.status_code == 200
    assert 'onclick=' not in employee.text
    assert employee.headers["cache-control"] == "no-store"


def test_trusted_proxy_configuration_rejects_wide_networks(monkeypatch, tmp_path):
    """Защита не доверяет всей общей Docker-сети и внешнему интернету."""
    assert parse_trusted_proxy_hosts("172.20.0.3/32") == ("172.20.0.3/32",)
    assert parse_trusted_proxy_hosts("172.20.0.3") == ("172.20.0.3/32",)
    assert parse_trusted_proxy_hosts("") == ()
    for network in ("172.20.0.0/16", "0.0.0.0/0", "::/0"):
        with pytest.raises(ValueError, match="только /32 или /128"):
            parse_trusted_proxy_hosts(network)

        monkeypatch.setenv("PULSE_TRUSTED_PROXY_CIDRS", network)
        with pytest.raises(ValueError):
            create_app(
                database_url=f"sqlite:///{tmp_path / 'refused.sqlite3'}",
                secret_key="secret-for-tests-only",
                admin_password="password-for-tests",
            )
    monkeypatch.delenv("PULSE_TRUSTED_PROXY_CIDRS", raising=False)


def test_backend_does_not_trust_proxy_headers_implicitly():
    """Запущенный Uvicorn не подменяет реальный peer заголовком клиента."""
    from pathlib import Path
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    assert "--no-proxy-headers" in dockerfile.read_text(encoding="utf-8")


def test_untrusted_neighbor_cannot_rotate_forwarded_for_to_bypass_limit():
    """Подмена XFF от соседнего контейнера не меняет ключ блокировки."""
    request = SimpleNamespace(
        client=SimpleNamespace(host="172.20.0.4"),
        headers={"x-forwarded-for": "198.51.100.1"},
    )
    allowed_proxy = ("172.20.0.3/32",)
    assert client_source(request, allowed_proxy) == "172.20.0.4"
    request.headers = {"x-forwarded-for": "203.0.113.25"}
    assert client_source(request, allowed_proxy) == "172.20.0.4"
