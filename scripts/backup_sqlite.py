"""Безопасное резервное копирование базы ПУЛЬС средствами SQLite."""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


REQUIRED_TABLES = {"employees", "checkins", "issues"}


def backup_sqlite(source: Path, destination: Path) -> Path:
    """Создаёт согласованную копию, не перезаписывая существующий файл.

    Временный файл и конечная копия размещаются в одном каталоге.
    Публикация через жёсткую ссылку исключает перезапись готовой копии.
    Для активной базы применяется SQLite Online Backup API, а не копирование файла.
    """
    source = Path(source).expanduser().resolve(strict=True)
    destination = Path(destination).expanduser().absolute()

    if not source.is_file():
        raise ValueError("Источник не является обычным файлом SQLite")
    if source == destination:
        raise ValueError("Источник и назначение должны различаться")
    if destination.exists():
        raise FileExistsError(f"Резервная копия уже существует: {destination}")
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"Каталог резервной копии отсутствует: {destination.parent}")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)

    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(temporary)) as saved:
                original.backup(saved, pages=128, sleep=0.05)

                integrity = saved.execute("PRAGMA integrity_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    raise RuntimeError("Проверка целостности SQLite не пройдена")

                foreign_key_errors = saved.execute("PRAGMA foreign_key_check").fetchall()
                if foreign_key_errors:
                    raise RuntimeError("Обнаружены нарушения внешних ключей SQLite")

                tables = {
                    row[0] for row in saved.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if not REQUIRED_TABLES <= tables:
                    raise RuntimeError("Источник не содержит обязательных таблиц ПУЛЬС")

        # На Windows fsync требует дескриптор, открытый для записи.
        # Данные уже сохранены SQLite: здесь ничего не перезаписываем.
        os.chmod(temporary, 0o600)
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())

        # В отличие от os.replace(), os.link() не затирает готовую копию.
        os.link(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    """Запускает безопасное резервное копирование из командной строки."""
    parser = argparse.ArgumentParser(
        description="Создать целостную резервную копию SQLite ПУЛЬС"
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()

    try:
        result = backup_sqlite(args.source, args.destination)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        parser.exit(1, f"PULSE_BACKUP_FAILED: {exc}\n")
    print(f"PULSE_BACKUP=PASS path={result}")


if __name__ == "__main__":
    main()
