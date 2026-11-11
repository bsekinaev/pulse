"""Начальная схема ПУЛЬС: исходная структура v0.1.0.

Revision ID: 20261111_0001
Revises:
"""

from alembic import op
import sqlalchemy as sa


revision = "20261111_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создаёт исходные таблицы для новой базы данных."""
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("demo_key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("department", sa.String(length=40), nullable=False),
        sa.Column("position", sa.String(length=100), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("mentor_name", sa.String(length=100), nullable=False),
        sa.UniqueConstraint("demo_key"),
    )
    op.create_table(
        "checkins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("checkpoint_day", sa.Integer(), nullable=False),
        sa.Column("answers_json", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("employee_id", "checkpoint_day", name="uq_checkin_employee_day"),
    )
    op.create_table(
        "issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("checkin_id", sa.Integer(), sa.ForeignKey("checkins.id"), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("owner_name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.UniqueConstraint("checkin_id", "category", name="uq_issue_checkin_category"),
    )


def downgrade() -> None:
    """Удаляет все таблицы; в production откат данных запрещён."""
    raise RuntimeError("Откат базовой миграции с удалением данных запрещён")
