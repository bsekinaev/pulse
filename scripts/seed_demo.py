"""Воспроизводимый набор вымышленных сотрудников и ситуаций."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Employee, Issue
from app.services.onboarding import resolve_issue, submit_checkin

EMPLOYEES = [
    ("alex", "Алексей М.", "Склад", "Кладовщик", 3, "Сергей К."),
    ("maria", "Мария К.", "Магазин", "Продавец-консультант", 5, "Наталья П."),
    ("denis", "Денис С.", "Офис", "Специалист продаж", 1, "Елена Т."),
    ("olga", "Ольга Р.", "Магазин", "Кассир", 7, "Наталья П."),
    ("igor", "Игорь В.", "Склад", "Комплектовщик", 2, "Сергей К."),
    ("elena", "Елена Т.", "Офис", "Менеджер", 3, "Андрей Л."),
    ("pavel", "Павел Н.", "Склад", "Кладовщик", 6, "Сергей К."),
    ("anna", "Анна Л.", "Магазин", "Продавец", 1, "Наталья П."),
]

SCENARIOS = [
    ("maria", ("yes", "yes", "yes"), ""),
    ("olga", ("yes", "no", "yes"), "Неясно, как согласовать график смен."),
    ("elena", ("yes", "yes", "no"), "Не знаю, к кому обратиться за доступом."),
    ("pavel", ("no", "yes", "yes"), "Не был выдан терминал для комплектации."),
]


def seed_demo(session: Session, today: date | None = None) -> int:
    """Заполняет только отсутствующие записи; данные демо не сбрасываются."""
    today = today or date.today()
    existing = set(session.scalars(select(Employee.demo_key)).all())
    added = 0
    for key, name, dept, position, day, mentor in EMPLOYEES:
        if key in existing:
            continue
        session.add(Employee(
            demo_key=key, name=name, department=dept, position=position,
            start_date=today - timedelta(days=day - 1), mentor_name=mentor,
        ))
        added += 1
    session.commit()

    people = {e.demo_key: e for e in session.scalars(select(Employee)).all()}
    for key, values, comment in SCENARIOS:
        answers = dict(zip(("equipment", "instructions", "support"), values))
        checkin, created = submit_checkin(session, people[key], answers, comment)
        if key == "pavel" and created:
            issue = session.scalar(select(Issue).where(Issue.checkin_id == checkin.id))
            if issue:
                resolve_issue(session, issue, "Терминал выдан, доступ проверен.")
    return added
