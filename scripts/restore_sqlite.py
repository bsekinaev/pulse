"""Безопасное восстановление SQLite исключительно в новый файл."""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts.backup_sqlite import REQUIRED_TABLES, backup_sqlite


def restore_sqlite(backup: Path, destination: Path) -> Path:
    """Восстанавливает копию в новый файл и независимо проверяет результат.

    Существующая база никогда не перезаписывается. Для проверки восстановления
    используется новый путь на изолированном стенде, не production volume.
    """
    restored = backup_sqlite(backup, destination)
    try:
        with closing(sqlite3.connect(restored.as_uri() + "?mode=ro", uri=True)) as db:
            result = db.execute("PRAGMA integrity_check").fetchone()
            if result != ("ok",):
                raise RuntimeError("Восстановленная SQLite-база повреждена")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RuntimeError("В восстановленной базе нарушены внешние ключи")
            for table in sorted(REQUIRED_TABLES):
                db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
    except Exception:
        restored.unlink(missing_ok=True)
        raise
    return restored


def main() -> None:
    """Восстанавливает резервную копию в указанный новый файл."""
    parser = argparse.ArgumentParser(
        description="Проверить восстановление ПУЛЬС в отдельный SQLite-файл"
    )
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = restore_sqlite(args.backup, args.destination)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        parser.exit(1, f"PULSE_RESTORE_FAILED: {exc}\n")
    print(f"PULSE_RESTORE=PASS path={output}")


if __name__ == "__main__":
    main()
