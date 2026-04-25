"""Add telegram chat id to agent runs

Revision ID: 0002_add_agent_run_chat_telegram_id
Revises: 0001_initial
Create Date: 2026-04-25 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_add_agent_run_chat_telegram_id"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("chat_telegram_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_agent_runs_chat_telegram_id",
        "agent_runs",
        ["chat_telegram_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_chat_telegram_id", table_name="agent_runs")
    op.drop_column("agent_runs", "chat_telegram_id")
