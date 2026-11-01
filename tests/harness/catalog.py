"""Load the MCP tool input schemas keyed by bare tool name."""

from __future__ import annotations

PREFIX = "blender_"


def load_tools() -> dict[str, dict]:
    from mcp_blender.server import TOOLS

    out: dict[str, dict] = {}
    for tool in TOOLS:
        name = tool.name.removeprefix(PREFIX)
        out[name] = tool.input_schema
    return out
