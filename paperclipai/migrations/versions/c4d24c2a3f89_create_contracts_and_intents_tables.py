"""create contracts and intents tables

Revision ID: c4d24c2a3f89
Revises:
Create Date: 2026-04-26 15:41:41.820750

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c4d24c2a3f89"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intents",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("caller_type", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("requested_outcome", sa.String(256), nullable=False),
        sa.Column("target", sa.Text, nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("constraints", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("callback_url", sa.Text, nullable=True),
        sa.Column("correlation_id", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="accepted"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_intent_dedup", "intents", ["caller_type", "idempotency_key"]
    )

    op.create_table(
        "contracts",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("parent_contract_id", sa.String(26), nullable=True),
        sa.Column("intent_id", sa.String(26), nullable=False),
        sa.Column("plan_id", sa.String(26), nullable=True),
        sa.Column("workflow_id", sa.String(256), nullable=True),
        sa.Column("workflow_version", sa.String(32), nullable=True),
        sa.Column("step_id", sa.String(256), nullable=True),
        sa.Column("tool_name", sa.String(256), nullable=True),
        sa.Column("tool_version", sa.String(32), nullable=True),
        sa.Column("agent_role", sa.String(256), nullable=True),
        sa.Column("model_class", sa.String(64), nullable=True),
        sa.Column("execution_mode", sa.String(32), nullable=True),
        sa.Column("input_schema_ref", sa.String(256), nullable=True),
        sa.Column("output_schema_ref", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("instruction", postgresql.JSONB, nullable=True),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["intent_id"], ["intents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["parent_contract_id"], ["contracts.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_contracts_intent_created", "contracts", ["intent_id", "created_at"]
    )
    op.create_index("ix_contracts_workflow", "contracts", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_contracts_workflow", table_name="contracts")
    op.drop_index("ix_contracts_intent_created", table_name="contracts")
    op.drop_table("contracts")
    op.drop_constraint("uq_intent_dedup", "intents", type_="unique")
    op.drop_table("intents")
