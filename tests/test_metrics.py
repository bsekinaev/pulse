"""Проверки корректности операционных KPI и времени Минска."""

from datetime import date, datetime, timedelta, timezone

from app.db import Base, make_session_factory
from app.models import CheckIn, Employee, Issue
from app.services.metrics import (
    format_minsk, is_issue_overdue, minsk_today,
    operational_metrics, resolution_label,
)

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def build_metrics_db(tmp_path):
    """Создаёт независимую фикстуру с граничными периодами адаптации."""
    engine, factory = make_session_factory(
        f"sqlite:///{tmp_path / 'metrics.sqlite3'}"
    )
    Base.metadata.create_all(engine)
    with factory() as db:
        people = []
        for key, day in (("a", 1), ("b", 2), ("c", 3), ("d", 7), ("e", 8)):
            employee = Employee(
                demo_key=key, name=f"Сотрудник {key}", department="Склад",
                position="Кладовщик", mentor_name="Наставник",
                start_date=date(2026, 11, 11) - timedelta(days=day - 1),
            )
            db.add(employee)
            people.append(employee)
        db.flush()
        checkins = {}
        for key in ("b", "c"):
            employee = next(p for p in people if p.demo_key == key)
            checkin = CheckIn(
                employee_id=employee.id, checkpoint_day=3,
                answers_json='{"equipment":"yes"}',
            )
            db.add(checkin)
            checkins[key] = checkin
        db.flush()

        b, c = checkins["b"], checkins["c"]
        cases = [
            (b, "equipment", "open", 25, None),
            (c, "instructions", "open", 24, None),
            (b, "support", "resolved", 8, 2),
            (c, "equipment", "resolved", 6, 2),
        ]
        for checkin, category, status, created_ago, resolved_ago in cases:
            db.add(Issue(
                employee_id=checkin.employee_id, checkin_id=checkin.id,
                category=category, owner_name="Наставник",
                status=status,
                created_at=NOW - timedelta(hours=created_ago),
                resolved_at=(
                    NOW - timedelta(hours=resolved_ago)
                    if resolved_ago is not None else None
                ),
                resolution="Выполнено" if resolved_ago is not None else None,
            ))
        db.commit()
    return engine, factory


def test_operational_metrics_boundaries(tmp_path):
    """День 7 включён, день 8 нет; ровно 24 часа не является просрочкой."""
    engine, factory = build_metrics_db(tmp_path)
    try:
        with factory() as db:
            result = operational_metrics(db, now=NOW)
            assert result["active"] == 4
            assert result["due_no_answer"] == 2
            assert result["open"] == 2
            assert result["overdue"] == 1
            assert len(result["overdue_issue_ids"]) == 1
            assert result["resolved"] == 2
            assert result["average_resolution_minutes"] == 300.0
            assert resolution_label(result["average_resolution_minutes"]) == "5.0 ч"
    finally:
        engine.dispose()


def test_issue_overdue_boundary(tmp_path):
    """SLA считается строго после 24 часов; решённые проблемы исключаются."""
    engine, factory = build_metrics_db(tmp_path)
    try:
        with factory() as db:
            issues = db.query(Issue).order_by(Issue.id).all()
            assert is_issue_overdue(issues[0], NOW) is True
            assert is_issue_overdue(issues[1], NOW) is False
            assert is_issue_overdue(issues[2], NOW) is False
            assert is_issue_overdue(issues[0], NOW - timedelta(hours=1)) is False
    finally:
        engine.dispose()


def test_empty_metrics_have_no_fake_average(tmp_path):
    """При отсутствии закрытых проблем среднее не подменяется нулём."""
    engine, factory = make_session_factory(
        f"sqlite:///{tmp_path / 'empty.sqlite3'}"
    )
    try:
        Base.metadata.create_all(engine)
        with factory() as db:
            result = operational_metrics(db, now=NOW)
            assert result["active"] == 0
            assert result["due_no_answer"] == 0
            assert result["overdue"] == 0
            assert result["average_resolution_minutes"] is None
            assert resolution_label(None) == "Нет данных"
    finally:
        engine.dispose()


def test_minsk_date_and_utc_conversion():
    """Смена календарных суток определяется временем Минска, не UTC сервера."""
    assert minsk_today(datetime(2026, 11, 11, 22, 30, tzinfo=timezone.utc)) == date(
        2026, 11, 12
    )
    naive_utc = datetime(2026, 11, 11, 14, 0)
    assert format_minsk(naive_utc) == "11.11.2026 17:00"
    assert format_minsk(None) == "—"
