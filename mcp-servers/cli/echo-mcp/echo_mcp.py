from mcp.server.fastmcp import FastMCP

mcp = FastMCP("echo")


@mcp.tool()
def echo(text: str) -> dict:
    """Echo back text with its character length."""
    return {"text": text, "length": len(text)}


if __name__ == "__main__":
    mcp.run()
