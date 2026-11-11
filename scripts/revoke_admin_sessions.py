"""Отзыв всех административных сессий ПУЛЬС после смены пароля."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from app.models import AdminSession


def revoke_all_sessions(database_url: str) -> int:
    """Отзывает все активные сессии, не затрагивая анкеты и сотрудников."""
    if not database_url.startswith("sqlite:///"):
        raise ValueError("На данном этапе разрешён только SQLite")
    engine = create_engine(database_url)
    try:
        with Session(engine) as db:
            result = db.execute(
                update(AdminSession)
                .where(AdminSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(timezone.utc))
            )
            db.commit()
            return result.rowcount
    finally:
        engine.dispose()


def main() -> None:
    """Запускает массовый отзыв только после явного подтверждения оператора."""
    parser = argparse.ArgumentParser(
        description="Отозвать все административные сессии после смены пароля"
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--confirm-revoke-all", action="store_true")
    args = parser.parse_args()
    if not args.confirm_revoke_all:
        parser.error("Для отзыва необходим --confirm-revoke-all")
    count = revoke_all_sessions(args.database_url)
    print(f"PULSE_REVOKED_ADMIN_SESSIONS={count}")


if __name__ == "__main__":
    main()
