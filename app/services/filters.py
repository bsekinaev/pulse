"""Поиск и фильтрация сотрудников в HR-панели ПУЛЬС."""

from __future__ import annotations

from datetime import date

from app.models import Employee

ALLOWED_STATES = {"all", "needs_help", "answered", "awaiting", "not_due"}


def employee_state(
    person: Employee,
    checkins: set[int],
    open_counts: dict[int, int],
    today: date,
) -> str:
    """Возвращает взаимоисключающий статус для фильтра HR-панели."""
    if open_counts.get(person.id, 0):
        return "needs_help"
    if person.id in checkins:
        return "answered"
    if (today - person.start_date).days + 1 < 3:
        return "not_due"
    return "awaiting"


def filter_employees(
    people: list[Employee],
    checkins: set[int],
    open_counts: dict[int, int],
    today: date,
    query: str = "",
    department: str = "",
    state: str = "all",
) -> list[Employee]:
    """Фильтрует готовый список, сохраняя порядок по срочности обращения."""
    phrase = query.strip().casefold()
    if state not in ALLOWED_STATES:
        state = "all"

    result = []
    for person in people:
        if department and person.department != department:
            continue
        if phrase and phrase not in f"{person.name} {person.position}".casefold():
            continue
        if state != "all" and employee_state(
            person, checkins, open_counts, today
        ) != state:
            continue
        result.append(person)
    return result
