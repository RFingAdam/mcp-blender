"""MCP server for Blender - main entry point."""

import argparse
import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .blender_client import BlenderClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-blender")

# Global client instance
_client: BlenderClient | None = None
_client_lock = asyncio.Lock()


async def get_client(host: str = "127.0.0.1", port: int = 9876) -> BlenderClient:
    """Get or create the Blender client connection."""
    global _client
    async with _client_lock:
        if _client is None or not _client.connected:
            _client = BlenderClient(host, port)
            await _client.connect()
        return _client


# Tool definitions with JSON schemas
TOOLS: list[Tool] = [
    # Scene Tools
    Tool(
        name="blender_scene_info",
        description="Get current scene information including name, frame range, render settings, and object count",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="blender_scene_new",
        description="Create a new scene",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name for the new scene"},
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_scene_clear",
        description="Remove all objects from the current scene",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="blender_scene_set_frame_range",
        description="Set the animation frame range",
        inputSchema={
            "type": "object",
            "properties": {
                "start": {"type": "integer", "description": "Start frame"},
                "end": {"type": "integer", "description": "End frame"},
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_get_version",
        description="Get Blender version information",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    # Object Tools
    Tool(
        name="blender_object_create",
        description="Create a primitive object (cube, sphere, cylinder, plane, cone, torus, monkey, circle, grid, empty, camera, light)",
        inputSchema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["cube", "sphere", "cylinder", "plane", "cone", "torus", "monkey", "circle", "grid", "empty", "camera", "light"],
                    "description": "Type of primitive to create",
                },
                "name": {"type": "string", "description": "Optional name for the object"},
                "location": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Location [x, y, z]",
                },
                "rotation": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Rotation in degrees or radians [x, y, z]",
                },
                "scale": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Scale [x, y, z]",
                },
            },
            "required": ["type"],
        },
    ),
    Tool(
        name="blender_object_delete",
        description="Delete an object by name",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the object to delete"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="blender_object_list",
        description="List all objects in the scene",
        inputSchema={
            "type": "object",
            "properties": {
                "type_filter": {
                    "type": "string",
                    "enum": ["MESH", "CURVE", "SURFACE", "META", "FONT", "ARMATURE", "LATTICE", "EMPTY", "CAMERA", "LIGHT"],
                    "description": "Filter by object type",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_object_get",
        description="Get detailed properties of an object",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the object"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="blender_object_transform",
        description="Set the location, rotation, and/or scale of an object",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the object"},
                "location": {"type": "array", "items": {"type": "number"}, "description": "Location [x, y, z]"},
                "rotation": {"type": "array", "items": {"type": "number"}, "description": "Rotation [x, y, z]"},
                "scale": {"type": "array", "items": {"type": "number"}, "description": "Scale [x, y, z]"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="blender_object_duplicate",
        description="Duplicate an object",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the object to duplicate"},
                "new_name": {"type": "string", "description": "Name for the duplicate"},
                "linked": {"type": "boolean", "description": "Create a linked duplicate (shares mesh data)"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="blender_object_join",
        description="Join multiple objects into one",
        inputSchema={
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of objects to join",
                },
            },
            "required": ["names"],
        },
    ),
    Tool(
        name="blender_object_separate",
        description="Separate an object by loose parts, materials, or selection",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the object"},
                "mode": {
                    "type": "string",
                    "enum": ["LOOSE", "MATERIAL", "SELECTED"],
                    "description": "Separation mode",
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="blender_object_parent",
        description="Set parent-child relationship between objects",
        inputSchema={
            "type": "object",
            "properties": {
                "child": {"type": "string", "description": "Name of the child object"},
                "parent": {"type": "string", "description": "Name of the parent object (omit to clear parent)"},
            },
            "required": ["child"],
        },
    ),
    Tool(
        name="blender_object_select",
        description="Select objects by name or pattern",
        inputSchema={
            "type": "object",
            "properties": {
                "names": {"type": "array", "items": {"type": "string"}, "description": "Object names to select"},
                "pattern": {"type": "string", "description": "Glob pattern to match (e.g., 'Cube*')"},
                "deselect_others": {"type": "boolean", "description": "Deselect other objects first"},
            },
            "required": [],
        },
    ),
    # Material Tools
    Tool(
        name="blender_material_create",
        description="Create a new material",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Material name"},
                "use_nodes": {"type": "boolean", "description": "Use shader nodes (default: true)"},
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_material_assign",
        description="Assign a material to an object",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "material_name": {"type": "string", "description": "Name of the material"},
                "slot_index": {"type": "integer", "description": "Material slot index (optional)"},
            },
            "required": ["object_name", "material_name"],
        },
    ),
    Tool(
        name="blender_material_set_color",
        description="Set the base color of a material",
        inputSchema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the material"},
                "color": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "RGBA color values (0-1), e.g., [1, 0, 0, 1] for red",
                },
            },
            "required": ["material_name", "color"],
        },
    ),
    Tool(
        name="blender_material_set_principled",
        description="Configure Principled BSDF shader parameters",
        inputSchema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the material"},
                "base_color": {"type": "array", "items": {"type": "number"}, "description": "Base color RGBA"},
                "metallic": {"type": "number", "description": "Metallic (0-1)"},
                "roughness": {"type": "number", "description": "Roughness (0-1)"},
                "specular_ior_level": {"type": "number", "description": "Specular IOR level"},
                "emission_color": {"type": "array", "items": {"type": "number"}, "description": "Emission color RGB"},
                "emission_strength": {"type": "number", "description": "Emission strength"},
                "alpha": {"type": "number", "description": "Alpha (0-1)"},
            },
            "required": ["material_name"],
        },
    ),
    Tool(
        name="blender_material_add_texture",
        description="Add an image texture to a material",
        inputSchema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the material"},
                "image_path": {"type": "string", "description": "Path to the image file"},
                "connect_to": {"type": "string", "description": "Input to connect to (e.g., 'Base Color')"},
            },
            "required": ["material_name", "image_path"],
        },
    ),
    Tool(
        name="blender_material_list",
        description="List all materials in the file",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    # Modifier Tools
    Tool(
        name="blender_modifier_add",
        description="Add a modifier to an object with optional preset configuration",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "modifier_type": {
                    "type": "string",
                    "description": "Type of modifier (SUBSURF, BEVEL, SOLIDIFY, ARRAY, MIRROR, BOOLEAN, etc.)",
                },
                "modifier_name": {"type": "string", "description": "Custom name for the modifier"},
                "use_preset": {
                    "type": "boolean",
                    "description": "Apply sensible default values (default: true)",
                },
                "properties": {
                    "type": "object",
                    "description": "Custom properties to set on the modifier",
                },
            },
            "required": ["object_name", "modifier_type"],
        },
    ),
    Tool(
        name="blender_modifier_remove",
        description="Remove a modifier from an object",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "modifier_name": {"type": "string", "description": "Name of the modifier"},
            },
            "required": ["object_name", "modifier_name"],
        },
    ),
    Tool(
        name="blender_modifier_apply",
        description="Apply a modifier permanently to the mesh geometry",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "modifier_name": {"type": "string", "description": "Name of the modifier"},
            },
            "required": ["object_name", "modifier_name"],
        },
    ),
    Tool(
        name="blender_modifier_configure",
        description="Configure modifier parameters",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "modifier_name": {"type": "string", "description": "Name of the modifier"},
                "properties": {
                    "type": "object",
                    "description": "Properties to set (e.g., {'levels': 2} for subdivision)",
                },
            },
            "required": ["object_name", "modifier_name", "properties"],
        },
    ),
    Tool(
        name="blender_modifier_list",
        description="List modifiers on an object, or list all available modifier types",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of object to list modifiers for (omit to list available types)",
                },
            },
            "required": [],
        },
    ),
    # Animation Tools
    Tool(
        name="blender_keyframe_insert",
        description="Insert a keyframe for an object property, optionally setting its value",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "data_path": {
                    "type": "string",
                    "description": "Property path (e.g., 'location', 'rotation_euler', 'scale')",
                },
                "frame": {"type": "integer", "description": "Frame number (default: current)"},
                "index": {
                    "type": "integer",
                    "description": "Property index: -1 for all axes, 0/1/2 for X/Y/Z",
                },
                "value": {
                    "description": "Value to set before inserting keyframe",
                },
            },
            "required": ["object_name", "data_path"],
        },
    ),
    Tool(
        name="blender_keyframe_delete",
        description="Delete a keyframe from an object property",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "data_path": {"type": "string", "description": "Property path"},
                "frame": {"type": "integer", "description": "Frame number (default: current)"},
                "index": {"type": "integer", "description": "Property index (-1 for all)"},
            },
            "required": ["object_name", "data_path"],
        },
    ),
    Tool(
        name="blender_keyframe_list",
        description="List all keyframes for an object",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_action_create",
        description="Create a new action (animation data container) and optionally assign to object",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Action name"},
                "object_name": {"type": "string", "description": "Object to assign the action to"},
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_action_list",
        description="List all actions in the Blender file",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="blender_animation_play",
        description="Play or pause the animation playback",
        inputSchema={
            "type": "object",
            "properties": {
                "play": {"type": "boolean", "description": "True to play, false to pause"},
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_animation_goto_frame",
        description="Jump to a specific frame in the timeline",
        inputSchema={
            "type": "object",
            "properties": {
                "frame": {"type": "integer", "description": "Frame number to jump to"},
            },
            "required": ["frame"],
        },
    ),
    # Render Tools
    Tool(
        name="blender_render_image",
        description="Render the current frame to a file",
        inputSchema={
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "Output file path"},
                "file_format": {
                    "type": "string",
                    "enum": ["PNG", "JPEG", "BMP", "TIFF", "OPEN_EXR"],
                    "description": "Output format",
                },
            },
            "required": ["output_path"],
        },
    ),
    Tool(
        name="blender_render_animation",
        description="Render the animation to files",
        inputSchema={
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "Output path (with frame placeholder)"},
                "file_format": {"type": "string", "description": "Output format"},
                "start_frame": {"type": "integer", "description": "Start frame"},
                "end_frame": {"type": "integer", "description": "End frame"},
            },
            "required": ["output_path"],
        },
    ),
    Tool(
        name="blender_render_set_engine",
        description="Set the render engine",
        inputSchema={
            "type": "object",
            "properties": {
                "engine": {
                    "type": "string",
                    "enum": ["CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH", "EEVEE"],
                    "description": "Render engine",
                },
            },
            "required": ["engine"],
        },
    ),
    Tool(
        name="blender_render_set_resolution",
        description="Set the render resolution",
        inputSchema={
            "type": "object",
            "properties": {
                "width": {"type": "integer", "description": "Width in pixels"},
                "height": {"type": "integer", "description": "Height in pixels"},
                "percentage": {"type": "integer", "description": "Resolution percentage (1-100)"},
            },
            "required": ["width", "height"],
        },
    ),
    Tool(
        name="blender_render_screenshot",
        description="Capture the current viewport as an image",
        inputSchema={
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "Output file path"},
            },
            "required": ["output_path"],
        },
    ),
    # Export Tools
    Tool(
        name="blender_export_gltf",
        description="Export scene or selected objects to glTF/GLB format",
        inputSchema={
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Output file path"},
                "export_format": {"type": "string", "enum": ["GLB", "GLTF_SEPARATE", "GLTF_EMBEDDED"], "description": "Export format"},
                "selected_only": {"type": "boolean", "description": "Export selected objects only"},
                "export_animations": {"type": "boolean", "description": "Include animations"},
                "export_materials": {"type": "boolean", "description": "Include materials"},
            },
            "required": ["filepath"],
        },
    ),
    Tool(
        name="blender_export_fbx",
        description="Export scene or selected objects to FBX format",
        inputSchema={
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Output file path"},
                "selected_only": {"type": "boolean", "description": "Export selected objects only"},
                "apply_modifiers": {"type": "boolean", "description": "Apply modifiers"},
            },
            "required": ["filepath"],
        },
    ),
    Tool(
        name="blender_export_obj",
        description="Export scene or selected objects to OBJ format",
        inputSchema={
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Output file path"},
                "selected_only": {"type": "boolean", "description": "Export selected objects only"},
                "apply_modifiers": {"type": "boolean", "description": "Apply modifiers"},
            },
            "required": ["filepath"],
        },
    ),
    Tool(
        name="blender_export_stl",
        description="Export scene or selected objects to STL format (for 3D printing)",
        inputSchema={
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Output file path"},
                "selected_only": {"type": "boolean", "description": "Export selected objects only"},
                "apply_modifiers": {"type": "boolean", "description": "Apply modifiers"},
                "scale": {"type": "number", "description": "Global scale factor"},
                "ascii": {"type": "boolean", "description": "Export as ASCII (larger file, human-readable)"},
            },
            "required": ["filepath"],
        },
    ),
    Tool(
        name="blender_export_usd",
        description="Export to Universal Scene Description (USD) format",
        inputSchema={
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Output file path (.usd, .usda, .usdc)"},
                "selected_only": {"type": "boolean", "description": "Export selected objects only"},
                "export_animation": {"type": "boolean", "description": "Include animations"},
                "export_materials": {"type": "boolean", "description": "Include materials"},
            },
            "required": ["filepath"],
        },
    ),
    Tool(
        name="blender_import_file",
        description="Import a 3D file (auto-detects format: glTF, FBX, OBJ, STL, USD, PLY, DAE, ABC, SVG)",
        inputSchema={
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Path to the file to import"},
            },
            "required": ["filepath"],
        },
    ),
    # External Integration Tools
    Tool(
        name="blender_polyhaven_search",
        description="Search Poly Haven for free HDRIs, textures, or 3D models",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "asset_type": {"type": "string", "enum": ["hdris", "textures", "models"], "description": "Type of asset"},
                "categories": {"type": "array", "items": {"type": "string"}, "description": "Category filters"},
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_polyhaven_download",
        description="Download and apply a Poly Haven asset",
        inputSchema={
            "type": "object",
            "properties": {
                "asset_id": {"type": "string", "description": "Poly Haven asset ID"},
                "resolution": {"type": "string", "enum": ["1k", "2k", "4k", "8k"], "description": "Resolution"},
                "apply_to": {"type": "string", "description": "For textures: material name to apply to"},
            },
            "required": ["asset_id"],
        },
    ),
    Tool(
        name="blender_ai_generate_model",
        description="Generate a 3D model using Hyper3D Rodin AI. Supports text-to-3D and image-to-3D. Requires RODIN_API_KEY environment variable.",
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text description of the model to generate (required for text-to-3D, optional for image-to-3D)",
                },
                "image_path": {
                    "type": "string",
                    "description": "Path to input image for image-to-3D generation (optional, if provided uses image-to-3D)",
                },
                "style": {
                    "type": "string",
                    "enum": ["realistic", "cartoon", "low_poly", "sculpture", "anime"],
                    "description": "Generation style",
                },
                "quality": {
                    "type": "string",
                    "enum": ["draft", "medium", "high"],
                    "default": "medium",
                    "description": "Generation quality level",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["glb", "gltf", "fbx", "obj", "usdz"],
                    "default": "glb",
                    "description": "Output file format",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_ai_model_status",
        description="Check the status of an AI model generation job and optionally import the completed model",
        inputSchema={
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Job ID returned from blender_ai_generate_model",
                },
                "auto_import": {
                    "type": "boolean",
                    "default": True,
                    "description": "Automatically import the model into Blender when generation completes",
                },
            },
            "required": ["job_id"],
        },
    ),
]


def create_server(host: str, port: int) -> Server:
    """Create and configure the MCP server."""
    server = Server("mcp-blender")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Return the list of available tools."""
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle tool calls by forwarding to Blender."""
        logger.info(f"Tool call: {name} with args: {arguments}")

        try:
            client = await get_client(host, port)

            # Map tool name to Blender command (remove 'blender_' prefix)
            command = name.replace("blender_", "")

            result = await client.send_command(command, arguments)

            # Format result as text
            if isinstance(result, dict):
                result_text = json.dumps(result, indent=2)
            else:
                result_text = str(result)

            return [TextContent(type="text", text=result_text)]

        except ConnectionRefusedError:
            return [TextContent(
                type="text",
                text="Error: Could not connect to Blender. Make sure Blender is running and the MCP Server addon is enabled with the server started.",
            )]
        except Exception as e:
            logger.exception(f"Error calling tool {name}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    return server


async def run_server(host: str, port: int):
    """Run the MCP server with stdio transport."""
    server = create_server(host, port)

    async with stdio_server() as (read_stream, write_stream):
        logger.info(f"MCP Blender server starting (Blender connection: {host}:{port})")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="MCP server for Blender")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Blender addon host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9876,
        help="Blender addon port (default: 9876)",
    )
    args = parser.parse_args()

    asyncio.run(run_server(args.host, args.port))


if __name__ == "__main__":
    main()
