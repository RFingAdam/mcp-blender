"""Scene management tools."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server import Server

    from ..blender_client import BlenderClient


def register_scene_tools(server: "Server", get_client: "callable") -> None:
    """Register scene management tools with the MCP server."""

    @server.call_tool()
    async def blender_scene_info(arguments: dict) -> list:
        """Get current scene information including name, frame range, and object count."""
        client: BlenderClient = await get_client()
        result = await client.send_command("scene_info", {})
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_scene_new(arguments: dict) -> list:
        """Create a new scene."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "scene_new",
            {"name": arguments.get("name", "New Scene")},
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_scene_clear(arguments: dict) -> list:
        """Remove all objects from the current scene."""
        client: BlenderClient = await get_client()
        result = await client.send_command("scene_clear", {})
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_scene_set_frame_range(arguments: dict) -> list:
        """Set the animation frame range."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "scene_set_frame_range",
            {
                "start": arguments.get("start", 1),
                "end": arguments.get("end", 250),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_get_version(arguments: dict) -> list:
        """Get Blender version information."""
        client: BlenderClient = await get_client()
        result = await client.send_command("get_version", {})
        return [{"type": "text", "text": str(result)}]
