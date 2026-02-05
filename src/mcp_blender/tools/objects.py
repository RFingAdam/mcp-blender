"""Object CRUD tools."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server import Server

    from ..blender_client import BlenderClient


def register_object_tools(server: "Server", get_client: "callable") -> None:
    """Register object management tools with the MCP server."""

    @server.call_tool()
    async def blender_object_create(arguments: dict) -> list:
        """Create a primitive object (cube, sphere, cylinder, plane, cone, torus, monkey)."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "object_create",
            {
                "type": arguments.get("type", "cube"),
                "name": arguments.get("name"),
                "location": arguments.get("location", [0, 0, 0]),
                "rotation": arguments.get("rotation", [0, 0, 0]),
                "scale": arguments.get("scale", [1, 1, 1]),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_object_delete(arguments: dict) -> list:
        """Delete an object by name."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "object_delete",
            {"name": arguments["name"]},
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_object_list(arguments: dict) -> list:
        """List all objects in the scene."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "object_list",
            {"type_filter": arguments.get("type_filter")},
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_object_get(arguments: dict) -> list:
        """Get detailed properties of an object."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "object_get",
            {"name": arguments["name"]},
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_object_transform(arguments: dict) -> list:
        """Set the location, rotation, and/or scale of an object."""
        client: BlenderClient = await get_client()
        params = {"name": arguments["name"]}
        if "location" in arguments:
            params["location"] = arguments["location"]
        if "rotation" in arguments:
            params["rotation"] = arguments["rotation"]
        if "scale" in arguments:
            params["scale"] = arguments["scale"]
        result = await client.send_command("object_transform", params)
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_object_duplicate(arguments: dict) -> list:
        """Duplicate an object."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "object_duplicate",
            {
                "name": arguments["name"],
                "new_name": arguments.get("new_name"),
                "linked": arguments.get("linked", False),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_object_join(arguments: dict) -> list:
        """Join multiple objects into one."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "object_join",
            {"names": arguments["names"]},
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_object_separate(arguments: dict) -> list:
        """Separate an object by loose parts."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "object_separate",
            {
                "name": arguments["name"],
                "mode": arguments.get("mode", "LOOSE"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_object_parent(arguments: dict) -> list:
        """Set parent-child relationship between objects."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "object_parent",
            {
                "child": arguments["child"],
                "parent": arguments.get("parent"),  # None to clear parent
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_object_select(arguments: dict) -> list:
        """Select objects by name or pattern."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "object_select",
            {
                "names": arguments.get("names"),
                "pattern": arguments.get("pattern"),
                "deselect_others": arguments.get("deselect_others", True),
            },
        )
        return [{"type": "text", "text": str(result)}]
