"""Авторизация ПУЛЬС: ограничение перебора и отзыв административных сессий."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AdminSession, LoginFailure

LOGIN_LIMIT = 5
LOGIN_WINDOW = timedelta(minutes=15)
SESSION_LIFETIME = timedelta(hours=4)


def _utc(value: datetime) -> datetime:
    """Нормализует время SQLite, которое может возвращаться без UTC-смещения."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    """Возвращает единое UTC-время для проверки периодов."""
    return datetime.now(timezone.utc)


def client_source(request, trusted_proxy_cidrs: tuple[str, ...] = ()) -> str:
    """Определяет адрес источника, не доверяя произвольному X-Forwarded-For.

    Адрес из заголовка учитывается только тогда, когда непосредственный peer
    принадлежит явно разрешённой подсети прокси. Без настройки используется
    адрес peer; за Caddy это может быть общий адрес самого прокси.
    """
    peer = request.client.host if request.client else "unknown"
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer

    trusted = any(
        peer_ip in ipaddress.ip_network(cidr, strict=False)
        for cidr in trusted_proxy_cidrs
    )
    if trusted:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return str(peer_ip)


def source_digest(source: str, secret: str) -> str:
    """Хеширует адрес источника: сам IP не записывается в базу."""
    return hmac.new(
        secret.encode("utf-8"), source.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def blocked_seconds(db: Session, key: str, now: datetime | None = None) -> int:
    """Возвращает время блокировки после пяти неуспешных попыток за 15 минут."""
    now = now or _now()
    cutoff = now - LOGIN_WINDOW
    failures = list(db.scalars(
        select(LoginFailure)
        .where(LoginFailure.source_hash == key, LoginFailure.attempted_at >= cutoff)
        .order_by(LoginFailure.attempted_at)
    ))
    if len(failures) < LOGIN_LIMIT:
        return 0
    first = _utc(failures[-LOGIN_LIMIT].attempted_at)
    return max(1, math.ceil((first + LOGIN_WINDOW - now).total_seconds()))


def register_failed_login(db: Session, key: str) -> None:
    """Сохраняет неудачный вход, не записывая пароль и исходный IP."""
    db.add(LoginFailure(source_hash=key, attempted_at=_now()))
    db.commit()


def reset_failed_logins(db: Session, key: str) -> None:
    """Сбрасывает счётчик после успешной аутентификации источника."""
    db.execute(delete(LoginFailure).where(LoginFailure.source_hash == key))
    db.commit()


def create_admin_session(db: Session) -> str:
    """Выдаёт одноразовый случайный идентификатор с серверным хранением хеша."""
    token = secrets.token_urlsafe(32)
    db.add(AdminSession(
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        created_at=_now(),
        expires_at=_now() + SESSION_LIFETIME,
    ))
    db.commit()
    return token


def valid_admin_session(db: Session, session_data: dict) -> bool:
    """Проверяет не только подпись cookie, но и отзыв на стороне сервера."""
    if session_data.get("admin") is not True:
        return False
    token = session_data.get("sid")
    if not isinstance(token, str) or len(token) > 128:
        return False
    stored = db.get(AdminSession, hashlib.sha256(token.encode("utf-8")).hexdigest())
    return bool(
        stored is not None
        and stored.revoked_at is None
        and _utc(stored.expires_at) > _now()
    )


def revoke_admin_session(db: Session, session_data: dict) -> None:
    """Отзывает активный идентификатор даже при повторном предъявлении cookie."""
    token = session_data.get("sid")
    if not isinstance(token, str):
        return
    stored = db.get(AdminSession, hashlib.sha256(token.encode("utf-8")).hexdigest())
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = _now()
        db.commit()
