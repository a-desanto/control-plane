import json
import logging
from datetime import UTC, datetime

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from ulid import ULID

from app.contracts.tool_output import (
    Category,
    ToolError,
    ToolOutputFailure,
    ToolOutputSuccess,
)
from app.tool_registry import ToolRegistryEntry

logger = logging.getLogger(__name__)


def _failure(
    contract_id: str,
    schema_ref: str,
    code: str,
    message: str,
    category: Category,
    retriable: bool,
) -> ToolOutputFailure:
    return ToolOutputFailure(
        contract_id=ULID.from_str(contract_id),
        status="failure",
        schema_ref=schema_ref,
        error=ToolError(
            code=code,
            message=message,
            category=category,
            retriable=retriable,
        ),
        completed_at=datetime.now(UTC),
    )


async def invoke_tool(
    registry_entry: ToolRegistryEntry,
    contract_id: str,
    input_data: dict,
) -> ToolOutputSuccess | ToolOutputFailure:
    schema_ref = registry_entry.output_schema

    if registry_entry.mcp.transport != "stdio":
        return _failure(
            contract_id,
            schema_ref,
            "UNSUPPORTED_TRANSPORT",
            f"Transport '{registry_entry.mcp.transport}' is not supported",
            Category.permanent,
            False,
        )

    command = registry_entry.mcp.command
    if not command:
        return _failure(
            contract_id,
            schema_ref,
            "MISCONFIGURED_TOOL",
            "stdio transport requires a command list",
            Category.permanent,
            False,
        )

    server_params = StdioServerParameters(command=command[0], args=command[1:])

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    registry_entry.mcp.tool_call, arguments=input_data
                )
    except Exception as exc:
        logger.exception("MCP invocation failed for tool=%s", registry_entry.tool_name)
        return _failure(
            contract_id,
            schema_ref,
            "INVOCATION_ERROR",
            str(exc),
            Category.transient,
            True,
        )

    if getattr(result, "isError", False):
        error_text = (
            result.content[0].text
            if result.content and hasattr(result.content[0], "text")
            else "tool reported an error"
        )
        return _failure(
            contract_id,
            schema_ref,
            "TOOL_ERROR",
            error_text,
            Category.transient,
            True,
        )

    if not result.content:
        return _failure(
            contract_id,
            schema_ref,
            "SCHEMA_VIOLATION",
            "MCP tool returned empty content",
            Category.schema,
            False,
        )

    content_block = result.content[0]
    raw_text = getattr(content_block, "text", None)
    if raw_text is None:
        return _failure(
            contract_id,
            schema_ref,
            "SCHEMA_VIOLATION",
            f"Content block has no text field: {content_block!r}",
            Category.schema,
            False,
        )

    try:
        data = json.loads(raw_text)
        if not isinstance(data, dict):
            raise ValueError(f"Expected JSON object, got {type(data).__name__}")
    except (json.JSONDecodeError, ValueError) as exc:
        return _failure(
            contract_id,
            schema_ref,
            "SCHEMA_VIOLATION",
            f"Failed to parse MCP response as JSON object: {exc}",
            Category.schema,
            False,
        )

    return ToolOutputSuccess(
        contract_id=ULID.from_str(contract_id),
        status="success",
        schema_ref=schema_ref,
        data=data,
        completed_at=datetime.now(UTC),
    )
