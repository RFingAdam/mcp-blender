"""Modifier tools."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server import Server

    from ..blender_client import BlenderClient


def register_modifier_tools(server: "Server", get_client: "callable") -> None:
    """Register modifier tools with the MCP server."""

    @server.call_tool()
    async def blender_modifier_add(arguments: dict) -> list:
        """Add a modifier to an object (subdivision, bevel, solidify, array, mirror, boolean)."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "modifier_add",
            {
                "object_name": arguments["object_name"],
                "modifier_type": arguments["modifier_type"],
                "modifier_name": arguments.get("modifier_name"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_modifier_remove(arguments: dict) -> list:
        """Remove a modifier from an object."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "modifier_remove",
            {
                "object_name": arguments["object_name"],
                "modifier_name": arguments["modifier_name"],
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_modifier_apply(arguments: dict) -> list:
        """Apply a modifier to the mesh."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "modifier_apply",
            {
                "object_name": arguments["object_name"],
                "modifier_name": arguments["modifier_name"],
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_modifier_configure(arguments: dict) -> list:
        """Configure modifier parameters."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "modifier_configure",
            {
                "object_name": arguments["object_name"],
                "modifier_name": arguments["modifier_name"],
                "properties": arguments["properties"],
            },
        )
        return [{"type": "text", "text": str(result)}]
