"""Animation and keyframe tools."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server import Server

    from ..blender_client import BlenderClient


def register_animation_tools(server: "Server", get_client: "callable") -> None:
    """Register animation tools with the MCP server."""

    @server.call_tool()
    async def blender_keyframe_insert(arguments: dict) -> list:
        """Insert a keyframe for an object property."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "keyframe_insert",
            {
                "object_name": arguments["object_name"],
                "data_path": arguments["data_path"],  # e.g., "location", "rotation_euler"
                "frame": arguments.get("frame"),  # None = current frame
                "index": arguments.get("index", -1),  # -1 = all, 0/1/2 = specific axis
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_keyframe_delete(arguments: dict) -> list:
        """Delete a keyframe from an object property."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "keyframe_delete",
            {
                "object_name": arguments["object_name"],
                "data_path": arguments["data_path"],
                "frame": arguments.get("frame"),
                "index": arguments.get("index", -1),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_action_create(arguments: dict) -> list:
        """Create a new action (animation data container)."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "action_create",
            {
                "name": arguments.get("name", "Action"),
                "object_name": arguments.get("object_name"),  # Assign to object if provided
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_animation_play(arguments: dict) -> list:
        """Play or pause the animation."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "animation_play",
            {"play": arguments.get("play", True)},
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_animation_goto_frame(arguments: dict) -> list:
        """Jump to a specific frame."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "animation_goto_frame",
            {"frame": arguments["frame"]},
        )
        return [{"type": "text", "text": str(result)}]
