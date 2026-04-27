"""Tests for the MCP client layer (paperclipai/app/mcp_client/client.py).

Uses the echo MCP server directly via Python (no Docker required).
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.contracts.tool_output import ToolOutputFailure, ToolOutputSuccess
from app.mcp_client.client import invoke_tool
from app.tool_registry import McpTransport, ToolRegistryEntry

pytestmark = pytest.mark.asyncio(loop_scope="module")

ECHO_MCP_PATH = (
    Path(__file__).parent.parent.parent / "mcp-servers" / "cli" / "echo-mcp" / "echo_mcp.py"
)

_ECHO_ENTRY = ToolRegistryEntry(
    tool_name="echo",
    tool_version="1.0.0",
    mcp=McpTransport(
        transport="stdio",
        command=[sys.executable, str(ECHO_MCP_PATH)],
        tool_call="echo",
    ),
    input_schema="echo_input@v1",
    output_schema="tool_output@v3.3",
)

_CONTRACT_ID = "01HXTEST000000000000000020"


async def test_invoke_echo_returns_success() -> None:
    if not ECHO_MCP_PATH.exists():
        pytest.skip(f"echo_mcp.py not found at {ECHO_MCP_PATH}")

    result = await invoke_tool(_ECHO_ENTRY, _CONTRACT_ID, {"text": "world"})
    assert isinstance(result, ToolOutputSuccess)
    assert result.status == "success"
    assert result.data == {"text": "world", "length": 5}
    assert result.schema_ref == "tool_output@v3.3"
    assert str(result.contract_id) == _CONTRACT_ID


async def test_invoke_echo_empty_text() -> None:
    if not ECHO_MCP_PATH.exists():
        pytest.skip(f"echo_mcp.py not found at {ECHO_MCP_PATH}")

    result = await invoke_tool(_ECHO_ENTRY, _CONTRACT_ID, {"text": ""})
    assert isinstance(result, ToolOutputSuccess)
    assert result.data["length"] == 0


async def test_unsupported_transport_returns_failure() -> None:
    entry = ToolRegistryEntry(
        tool_name="http_tool",
        tool_version="1.0.0",
        mcp=McpTransport(transport="http", url="http://example.com", tool_call="do_thing"),
        input_schema="echo_input@v1",
        output_schema="tool_output@v3.3",
    )
    result = await invoke_tool(entry, _CONTRACT_ID, {})
    assert isinstance(result, ToolOutputFailure)
    assert result.error.code == "UNSUPPORTED_TRANSPORT"
    assert result.error.retriable is False


async def test_bad_command_returns_invocation_error() -> None:
    entry = ToolRegistryEntry(
        tool_name="bad",
        tool_version="1.0.0",
        mcp=McpTransport(
            transport="stdio",
            command=["this-binary-does-not-exist-xyz"],
            tool_call="bad",
        ),
        input_schema="echo_input@v1",
        output_schema="tool_output@v3.3",
    )
    result = await invoke_tool(entry, _CONTRACT_ID, {})
    assert isinstance(result, ToolOutputFailure)
    assert result.error.code == "INVOCATION_ERROR"
    assert result.error.retriable is True


async def test_schema_violation_non_json_response() -> None:
    """If the MCP server returns non-JSON text, the client returns SCHEMA_VIOLATION."""
    from mcp.types import CallToolResult, TextContent

    fake_result = CallToolResult(
        content=[TextContent(type="text", text="not-json-at-all")],
        isError=False,
    )

    with patch("app.mcp_client.client.stdio_client") as mock_ctx:
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=fake_result)

        with patch("app.mcp_client.client.ClientSession", return_value=mock_session):
            result = await invoke_tool(_ECHO_ENTRY, _CONTRACT_ID, {"text": "x"})

    assert isinstance(result, ToolOutputFailure)
    assert result.error.code == "SCHEMA_VIOLATION"
    assert result.error.retriable is False
