"""Правила чек-инов и жизненного цикла проблем."""
import json
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CheckIn, Employee, Issue

CATEGORIES = ("equipment", "instructions", "support")
CATEGORY_NAMES = {
    "equipment": "Оборудование и доступы",
    "instructions": "Задачи и инструкции",
    "support": "Помощь наставника",
}


class InvalidAnswers(ValueError):
    pass


class AlreadyResolved(ValueError):
    pass


def submit_checkin(
    db: Session, employee: Employee, answers: dict[str, str],
    comment: str = "", checkpoint_day: int = 3,
) -> tuple[CheckIn, bool]:
    """Атомарно сохраняет чек-ин и препятствия без дубликатов."""
    if set(answers) != set(CATEGORIES) or any(value not in ("yes", "no") for value in answers.values()):
        raise InvalidAnswers("Необходимо ответить на все три вопроса")
    if len(comment) > 500:
        raise InvalidAnswers("Комментарий слишком длинный")
    existing = db.scalar(select(CheckIn).where(
        CheckIn.employee_id == employee.id, CheckIn.checkpoint_day == checkpoint_day,
    ))
    if existing:
        return existing, False

    checkin = CheckIn(
        employee_id=employee.id, checkpoint_day=checkpoint_day,
        answers_json=json.dumps(answers, ensure_ascii=False), comment=comment.strip(),
    )
    try:
        db.add(checkin)
        db.flush()
        for category, value in answers.items():
            if value == "no":
                db.add(Issue(
                    employee_id=employee.id, checkin_id=checkin.id,
                    category=category, status="open", owner_name=employee.mentor_name,
                ))
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(CheckIn).where(
            CheckIn.employee_id == employee.id, CheckIn.checkpoint_day == checkpoint_day,
        ))
        if existing:
            return existing, False
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(checkin)
    return checkin, True


def resolve_issue(db: Session, issue: Issue, resolution: str) -> Issue:
    """Сохраняет подтверждённое решение, не переписывая закрытую проблему."""
    resolution = resolution.strip()
    if not 5 <= len(resolution) <= 500:
        raise ValueError("Укажите результат устранения: от 5 до 500 символов")
    # Условное обновление атомарно: второе закрытие не перепишет первое,
    # даже если оба администратора загрузили открытую проблему заранее.
    try:
        result = db.execute(
            update(Issue)
            .where(Issue.id == issue.id, Issue.status == "open")
            .values(
                status="resolved",
                resolved_at=datetime.now(timezone.utc),
                resolution=resolution,
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise AlreadyResolved("Проблема уже закрыта")
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(issue)
    return issue


def dashboard_counts(db: Session) -> dict[str, int]:
    """Считает реальные показатели из базы данных."""
    total = db.scalar(select(func.count(Employee.id))) or 0
    submitted = db.scalar(select(func.count(func.distinct(CheckIn.employee_id)))) or 0
    opened = db.scalar(select(func.count(Issue.id)).where(Issue.status == "open")) or 0
    resolved = db.scalar(select(func.count(Issue.id)).where(Issue.status == "resolved")) or 0
    return {"total": total, "no_answer": total - submitted, "open": opened, "resolved": resolved}
