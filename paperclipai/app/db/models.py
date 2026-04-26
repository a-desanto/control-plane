from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Intent(Base):
    """Immutable record of every POST /intent received. Replay anchor."""

    __tablename__ = "intents"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    caller_type: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_outcome: Mapped[str] = mapped_column(String(256), nullable=False)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    constraints: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    callback_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="accepted")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    contracts: Mapped[list["Contract"]] = relationship(
        "Contract", back_populates="intent", order_by="Contract.created_at"
    )

    __table_args__ = (
        UniqueConstraint("caller_type", "idempotency_key", name="uq_intent_dedup"),
    )


class Contract(Base):
    """Append-only execution contract. Never updated, never deleted."""

    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    parent_contract_id: Mapped[str | None] = mapped_column(
        String(26), ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=True
    )
    intent_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("intents.id", ondelete="RESTRICT"), nullable=False
    )
    plan_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    workflow_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    step_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    tool_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agent_role: Mapped[str | None] = mapped_column(String(256), nullable=True)
    model_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_schema_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    output_schema_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    instruction: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    intent: Mapped["Intent"] = relationship("Intent", back_populates="contracts")
    parent: Mapped["Contract | None"] = relationship(
        "Contract", remote_side="Contract.id", foreign_keys=[parent_contract_id]
    )

    __table_args__ = (
        Index("ix_contracts_intent_created", "intent_id", "created_at"),
        Index("ix_contracts_workflow", "workflow_id"),
    )
