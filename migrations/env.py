"""Среда миграций схемы SQLite приложения ПУЛЬС."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import Base
from app import models  # Регистрация ORM-таблиц в метаданных.

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Подготавливает SQL без подключения к базе данных."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Применяет миграции в отдельном транзакционном подключении."""
    engine = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
