"""Rendering tools."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server import Server

    from ..blender_client import BlenderClient


def register_render_tools(server: "Server", get_client: "callable") -> None:
    """Register render tools with the MCP server."""

    @server.call_tool()
    async def blender_render_image(arguments: dict) -> list:
        """Render the current frame to a file."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "render_image",
            {
                "output_path": arguments["output_path"],
                "file_format": arguments.get("file_format", "PNG"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_render_animation(arguments: dict) -> list:
        """Render the animation to files."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "render_animation",
            {
                "output_path": arguments["output_path"],
                "file_format": arguments.get("file_format", "PNG"),
                "start_frame": arguments.get("start_frame"),
                "end_frame": arguments.get("end_frame"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_render_set_engine(arguments: dict) -> list:
        """Set the render engine (CYCLES, BLENDER_EEVEE_NEXT, BLENDER_WORKBENCH)."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "render_set_engine",
            {"engine": arguments["engine"]},
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_render_set_resolution(arguments: dict) -> list:
        """Set the render resolution."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "render_set_resolution",
            {
                "width": arguments["width"],
                "height": arguments["height"],
                "percentage": arguments.get("percentage", 100),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_render_screenshot(arguments: dict) -> list:
        """Capture the current viewport as an image."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "render_screenshot",
            {"output_path": arguments["output_path"]},
        )
        return [{"type": "text", "text": str(result)}]
