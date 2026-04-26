"""create api_keys and audit_log tables

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-04-26 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("app_id", sa.String(128), nullable=False),
        sa.Column("caller_type", sa.String(32), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.Text, nullable=False),
        sa.Column("capabilities", JSONB, nullable=False, server_default="[]"),
        sa.Column("budget_pool", sa.String(64), nullable=False, server_default="default"),
        sa.Column("rate_limit_per_minute", sa.Integer, nullable=False, server_default="60"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_app_id", "api_keys", ["app_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("app_id", sa.String(128), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_app_created", "audit_log", ["app_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_app_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_api_keys_app_id", table_name="api_keys")
    op.drop_table("api_keys")
