"""Подготовка воспроизводимых синтетических данных для демонстрации."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Employee

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


def seed_demo(session: Session, today: date | None = None) -> int:
    """Добавляет отсутствующие профили, не затрагивая ответы и решения."""
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
    return added
