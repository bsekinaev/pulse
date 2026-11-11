"""Таблицы защиты входа и отзыва сессий администратора.

Revision ID: 20261111_0002
Revises: 20261111_0001
"""

from alembic import op
import sqlalchemy as sa


revision = "20261111_0002"
down_revision = "20261111_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляет таблицы защиты без изменения данных сотрудников."""
    op.create_table(
        "login_failures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_login_failures_source_hash", "login_failures", ["source_hash"]
    )
    op.create_table(
        "admin_sessions",
        sa.Column("token_hash", sa.String(length=64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Запрещает удалять сведения об авторизации на работающей базе."""
    raise RuntimeError("Откат таблиц авторизации с потерей данных запрещён")
