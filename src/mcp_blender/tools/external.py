"""External integration tools (Poly Haven, AI model generation)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server import Server

    from ..blender_client import BlenderClient


def register_external_tools(server: "Server", get_client: "callable") -> None:
    """Register external integration tools with the MCP server."""

    @server.call_tool()
    async def blender_polyhaven_search(arguments: dict) -> list:
        """Search Poly Haven for HDRIs, textures, or models."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "polyhaven_search",
            {
                "query": arguments.get("query", ""),
                "asset_type": arguments.get("asset_type"),  # hdris, textures, models
                "categories": arguments.get("categories"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_polyhaven_download(arguments: dict) -> list:
        """Download and apply a Poly Haven asset."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "polyhaven_download",
            {
                "asset_id": arguments["asset_id"],
                "resolution": arguments.get("resolution", "2k"),
                "apply_to": arguments.get("apply_to"),  # For textures: material name
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_generate_model(arguments: dict) -> list:
        """Generate a 3D model using Hyper3D Rodin AI."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_generate_model",
            {
                "prompt": arguments["prompt"],
                "style": arguments.get("style"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_model_status(arguments: dict) -> list:
        """Check the status of an AI model generation job."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_model_status",
            {"job_id": arguments["job_id"]},
        )
        return [{"type": "text", "text": str(result)}]
