"""add plans, image_digest on contracts, callback_attempts

Revision ID: d7e2a1b3c4f5
Revises: c4d24c2a3f89
Create Date: 2026-04-26 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d7e2a1b3c4f5"
down_revision: Union[str, Sequence[str], None] = "c4d24c2a3f89"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("intent_id", sa.String(26), nullable=False),
        sa.Column("workflow_id", sa.String(256), nullable=False),
        sa.Column("workflow_version", sa.String(32), nullable=False),
        sa.Column("agent_role", sa.String(256), nullable=True),
        sa.Column("steps", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("policy_snapshot", postgresql.JSONB, nullable=True),
        sa.Column("termination_guard", postgresql.JSONB, nullable=True),
        sa.Column("signed_by", sa.String(256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["intent_id"], ["intents.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_plans_intent_id", "plans", ["intent_id"])

    op.add_column(
        "contracts",
        sa.Column("image_digest", sa.String(256), nullable=True),
    )

    op.create_table(
        "callback_attempts",
        sa.Column(
            "id", sa.BigInteger, primary_key=True, autoincrement=True
        ),
        sa.Column("intent_id", sa.String(26), nullable=False),
        sa.Column("attempt_number", sa.Integer, nullable=True),
        sa.Column("callback_url", sa.Text, nullable=False),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("succeeded", sa.Boolean, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["intent_id"], ["intents.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_callback_attempts_intent_id", "callback_attempts", ["intent_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_callback_attempts_intent_id", table_name="callback_attempts")
    op.drop_table("callback_attempts")
    op.drop_column("contracts", "image_digest")
    op.drop_index("ix_plans_intent_id", table_name="plans")
    op.drop_table("plans")
