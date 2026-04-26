import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_REGISTRY_DIR = Path(__file__).parent.parent.parent.parent / "tool-registry"


class McpTransport(BaseModel):
    transport: str
    command: list[str] | None = None
    tool_call: str
    url: str | None = None


class ToolRegistryEntry(BaseModel):
    tool_name: str
    tool_version: str
    mcp: McpTransport
    input_schema: str
    output_schema: str
    declared_side_effects: list[str] = []
    risk_level: str = "low"
    requires_capabilities: list[str] = []
    notes: str | None = None


def load_tool_registry(registry_dir: Path | None = None) -> list[ToolRegistryEntry]:
    directory = registry_dir or _REGISTRY_DIR
    entries: list[ToolRegistryEntry] = []
    for yaml_file in sorted(directory.glob("*.yaml")):
        with yaml_file.open() as f:
            raw: list[dict[str, Any]] = yaml.safe_load(f)
        for item in raw:
            entries.append(ToolRegistryEntry.model_validate(item))
    logger.info("Loaded %d tools from registry", len(entries))
    return entries
