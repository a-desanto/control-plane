"""Unit tests for the echo-mcp server.

Runs echo_mcp.py directly as a subprocess through the MCP stdio protocol.
No Docker, no database required.
"""

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.asyncio(loop_scope="function")

ECHO_MCP_PATH = (
    Path(__file__).parent.parent.parent / "mcp-servers" / "cli" / "echo-mcp" / "echo_mcp.py"
)

_SKIP_MSG = "echo_mcp.py not found"


def _server_params() -> StdioServerParameters:
    if not ECHO_MCP_PATH.exists():
        pytest.skip(_SKIP_MSG)
    return StdioServerParameters(command=sys.executable, args=[str(ECHO_MCP_PATH)])


async def test_echo_returns_text_and_length() -> None:
    import json
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("echo", {"text": "hello"})
    assert not getattr(result, "isError", False)
    assert result.content
    data = json.loads(result.content[0].text)
    assert data == {"text": "hello", "length": 5}


async def test_echo_empty_string() -> None:
    import json
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("echo", {"text": ""})
    assert not getattr(result, "isError", False)
    data = json.loads(result.content[0].text)
    assert data["text"] == ""
    assert data["length"] == 0


async def test_echo_unicode() -> None:
    import json
    text = "héllo"  # 5 chars but >5 bytes
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("echo", {"text": text})
    assert not getattr(result, "isError", False)
    data = json.loads(result.content[0].text)
    assert data["text"] == text
    assert data["length"] == len(text)


async def test_echo_tool_listed() -> None:
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
    names = [t.name for t in tools.tools]
    assert "echo" in names


async def test_echo_missing_text_arg_raises_error() -> None:
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("echo", {})
    assert getattr(result, "isError", False), "Expected isError=True for missing required arg"
