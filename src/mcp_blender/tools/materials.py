"""Material and shader tools."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server import Server

    from ..blender_client import BlenderClient


def register_material_tools(server: "Server", get_client: "callable") -> None:
    """Register material tools with the MCP server."""

    @server.call_tool()
    async def blender_material_create(arguments: dict) -> list:
        """Create a new material."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "material_create",
            {
                "name": arguments.get("name", "Material"),
                "use_nodes": arguments.get("use_nodes", True),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_material_assign(arguments: dict) -> list:
        """Assign a material to an object."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "material_assign",
            {
                "object_name": arguments["object_name"],
                "material_name": arguments["material_name"],
                "slot_index": arguments.get("slot_index"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_material_set_color(arguments: dict) -> list:
        """Set the base color of a material (RGBA, values 0-1)."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "material_set_color",
            {
                "material_name": arguments["material_name"],
                "color": arguments["color"],  # [r, g, b, a]
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_material_set_principled(arguments: dict) -> list:
        """Configure Principled BSDF parameters (metallic, roughness, etc.)."""
        client: BlenderClient = await get_client()
        params = {"material_name": arguments["material_name"]}
        for key in [
            "base_color",
            "metallic",
            "roughness",
            "specular_ior_level",
            "specular_tint",
            "anisotropic",
            "sheen_weight",
            "coat_weight",
            "emission_color",
            "emission_strength",
            "alpha",
        ]:
            if key in arguments:
                params[key] = arguments[key]
        result = await client.send_command("material_set_principled", params)
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_material_add_texture(arguments: dict) -> list:
        """Add an image texture node to a material."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "material_add_texture",
            {
                "material_name": arguments["material_name"],
                "image_path": arguments["image_path"],
                "connect_to": arguments.get("connect_to", "Base Color"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_material_list(arguments: dict) -> list:
        """List all materials in the file."""
        client: BlenderClient = await get_client()
        result = await client.send_command("material_list", {})
        return [{"type": "text", "text": str(result)}]
