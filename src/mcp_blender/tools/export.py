"""Import/export tools."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server import Server

    from ..blender_client import BlenderClient


def register_export_tools(server: "Server", get_client: "callable") -> None:
    """Register export/import tools with the MCP server."""

    @server.call_tool()
    async def blender_export_gltf(arguments: dict) -> list:
        """Export scene or selected objects to glTF/GLB format."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "export_gltf",
            {
                "filepath": arguments["filepath"],
                "export_format": arguments.get("export_format", "GLB"),
                "selected_only": arguments.get("selected_only", False),
                "export_animations": arguments.get("export_animations", True),
                "export_materials": arguments.get("export_materials", True),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_export_fbx(arguments: dict) -> list:
        """Export scene or selected objects to FBX format."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "export_fbx",
            {
                "filepath": arguments["filepath"],
                "selected_only": arguments.get("selected_only", False),
                "apply_modifiers": arguments.get("apply_modifiers", True),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_export_obj(arguments: dict) -> list:
        """Export scene or selected objects to OBJ format."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "export_obj",
            {
                "filepath": arguments["filepath"],
                "selected_only": arguments.get("selected_only", False),
                "apply_modifiers": arguments.get("apply_modifiers", True),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_export_stl(arguments: dict) -> list:
        """Export scene or selected objects to STL format."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "export_stl",
            {
                "filepath": arguments["filepath"],
                "selected_only": arguments.get("selected_only", False),
                "apply_modifiers": arguments.get("apply_modifiers", True),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_import_file(arguments: dict) -> list:
        """Import a file (auto-detects format by extension)."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "import_file",
            {"filepath": arguments["filepath"]},
        )
        return [{"type": "text", "text": str(result)}]
