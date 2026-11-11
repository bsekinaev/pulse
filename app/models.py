"""Модели данных адаптации."""
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    demo_key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    department: Mapped[str] = mapped_column(String(40))
    position: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    mentor_name: Mapped[str] = mapped_column(String(100))
    checkins: Mapped[list["CheckIn"]] = relationship(back_populates="employee")


class CheckIn(Base):
    __tablename__ = "checkins"
    __table_args__ = (UniqueConstraint("employee_id", "checkpoint_day", name="uq_checkin_employee_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    checkpoint_day: Mapped[int] = mapped_column(Integer, default=3)
    answers_json: Mapped[str] = mapped_column(Text)
    comment: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    employee: Mapped[Employee] = relationship(back_populates="checkins")
    issues: Mapped[list["Issue"]] = relationship(back_populates="checkin")


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("checkin_id", "category", name="uq_issue_checkin_category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    checkin_id: Mapped[int] = mapped_column(ForeignKey("checkins.id"))
    category: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(12), default="open")
    owner_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkin: Mapped[CheckIn] = relationship(back_populates="issues")
    employee: Mapped[Employee] = relationship()
