"""Операционные показатели адаптации и отображение времени Минска."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CheckIn, Employee, Issue

MINSK = ZoneInfo("Europe/Minsk")
ADAPTATION_DAYS = 7
CHECKPOINT_DAY = 3
ISSUE_SLA = timedelta(hours=24)


def as_utc(value: datetime) -> datetime:
    """Приводит время к UTC; наивное значение SQLite трактует как UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def minsk_today(now: datetime | None = None):
    """Возвращает локальную дату компании без зависимости от TZ контейнера."""
    return as_utc(now or datetime.now(timezone.utc)).astimezone(MINSK).date()


def format_minsk(value: datetime | None) -> str:
    """Преобразует UTC из SQLite в дату и время Минска для интерфейса."""
    if value is None:
        return "—"
    return as_utc(value).astimezone(MINSK).strftime("%d.%m.%Y %H:%M")


def is_issue_overdue(issue: Issue, now: datetime | None = None) -> bool:
    """Считает открытое обращение просроченным строго после 24 часов."""
    if issue.status != "open":
        return False
    moment = as_utc(now or datetime.now(timezone.utc))
    return as_utc(issue.created_at) + ISSUE_SLA < moment


def operational_metrics(db: Session, now: datetime | None = None) -> dict:
    """Рассчитывает KPI из базы: период адаптации, просрочки и время решения.

    Сотрудник вне семидневного периода не входит в показатель «В адаптации»,
    но его просроченный ответ на день 3 остаётся требующим внимания.
    """
    now = as_utc(now or datetime.now(timezone.utc))
    today = minsk_today(now)

    people = db.scalars(select(Employee)).all()
    received = set(db.scalars(select(CheckIn.employee_id).where(
        CheckIn.checkpoint_day == CHECKPOINT_DAY
    )).all())
    issues = db.scalars(select(Issue)).all()

    active = sum(
        1 for person in people
        if 1 <= (today - person.start_date).days + 1 <= ADAPTATION_DAYS
    )
    due_no_answer = sum(
        1 for person in people
        if (today - person.start_date).days + 1 >= CHECKPOINT_DAY
        and person.id not in received
    )
    opened = [item for item in issues if item.status == "open"]
    resolved = [item for item in issues if item.status == "resolved"]
    overdue_ids = {
        item.id for item in opened if is_issue_overdue(item, now)
    }
    durations = [
        (as_utc(item.resolved_at) - as_utc(item.created_at)).total_seconds() / 60
        for item in resolved if item.resolved_at is not None
        and as_utc(item.resolved_at) >= as_utc(item.created_at)
    ]
    average_minutes = round(sum(durations) / len(durations), 1) if durations else None

    return {
        "active": active,
        "due_no_answer": due_no_answer,
        "open": len(opened),
        "overdue": len(overdue_ids),
        "resolved": len(resolved),
        "average_resolution_minutes": average_minutes,
        "overdue_issue_ids": overdue_ids,
    }


def resolution_label(average_minutes: float | None) -> str:
    """Возвращает понятную подпись среднего времени решения."""
    if average_minutes is None:
        return "Нет данных"
    if average_minutes < 60:
        return f"{average_minutes:.0f} мин"
    return f"{average_minutes / 60:.1f} ч"
