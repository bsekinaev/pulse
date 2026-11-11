"""Конфигурация базы данных."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_session_factory(url: str):
    """Создаёт независимую фабрику сессий для приложения или тестов."""
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, **kwargs)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
