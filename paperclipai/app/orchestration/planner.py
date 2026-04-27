import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.contracts.workflow_plan import (
    CircuitState,
    ExecutionMode,
    KillSwitch,
    Model as WorkflowPlan,
    PolicySnapshot,
    Step,
)
from app.db.models import Intent, Plan

logger = logging.getLogger(__name__)

_KNOWN_WORKFLOWS: dict[str, tuple[str, str]] = {
    "echo_test": ("echo_test", "1.0.0"),
}


def _build_echo_plan(intent: Intent) -> WorkflowPlan:
    return WorkflowPlan(
        plan_id=ULID(),
        intent_id=ULID.from_str(intent.id),
        workflow_id="echo_test",
        workflow_version="1.0.0",
        policy_snapshot=PolicySnapshot(
            capabilities_granted=["echo"],
            budget_class="default",
            kill_switch=KillSwitch.off,
            circuit_state=CircuitState.closed,
        ),
        steps=[
            Step(
                step_id="step_1",
                tool_name="echo",
                tool_version="1.0.0",
                execution_mode=ExecutionMode.deterministic,
                input_schema_ref="echo_input@v1",
                output_schema_ref="tool_output@v3.3",
            )
        ],
        created_at=datetime.now(UTC),
        signed_by="paperclipai@0.1.0",
    )


_BUILDERS = {
    "echo_test": _build_echo_plan,
}


async def plan_for_intent(intent: Intent, db: AsyncSession) -> WorkflowPlan:
    builder = _BUILDERS.get(intent.requested_outcome)
    if builder is None:
        raise ValueError(
            f"No planner for requested_outcome='{intent.requested_outcome}'"
        )

    plan = builder(intent)

    row = Plan(
        id=str(plan.plan_id),
        intent_id=intent.id,
        workflow_id=plan.workflow_id,
        workflow_version=plan.workflow_version,
        agent_role=plan.agent_role,
        steps=[s.model_dump() for s in plan.steps],
        policy_snapshot=(
            plan.policy_snapshot.model_dump() if plan.policy_snapshot else None
        ),
        termination_guard=(
            plan.termination_guard.model_dump() if plan.termination_guard else None
        ),
        signed_by=plan.signed_by,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    logger.info("Created plan plan_id=%s for intent_id=%s", plan.plan_id, intent.id)
    return plan
