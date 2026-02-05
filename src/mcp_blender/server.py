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
    # MSFS Content Creation Tools - LOD
    Tool(
        name="blender_msfs_create_lod_hierarchy",
        description="Create LOD (Level of Detail) hierarchy from a base object for flight simulator content optimization",
        inputSchema={
            "type": "object",
            "properties": {
                "base_object_name": {"type": "string", "description": "Name of the base (LOD0) object"},
                "lod_count": {"type": "integer", "minimum": 1, "maximum": 4, "description": "Number of LOD levels (1-4, default: 4)"},
                "auto_decimate": {"type": "boolean", "description": "Automatically decimate lower LODs (default: true)"},
                "decimate_ratios": {
                    "type": "object",
                    "description": "Custom decimation ratios per LOD level (e.g., {'LOD1': 0.5, 'LOD2': 0.25})",
                },
            },
            "required": ["base_object_name"],
        },
    ),
    Tool(
        name="blender_msfs_decimate_for_lod",
        description="Decimate a mesh to a target ratio for LOD creation",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object to decimate"},
                "ratio": {"type": "number", "minimum": 0.01, "maximum": 1.0, "description": "Target vertex ratio (0.01-1.0)"},
                "preserve_uvs": {"type": "boolean", "description": "Try to preserve UV seams (default: true)"},
                "preserve_vertex_groups": {"type": "boolean", "description": "Preserve vertex group boundaries (default: true)"},
            },
            "required": ["object_name", "ratio"],
        },
    ),
    Tool(
        name="blender_msfs_setup_lod_distances",
        description="Configure LOD switching distances for flight simulator",
        inputSchema={
            "type": "object",
            "properties": {
                "base_name": {"type": "string", "description": "Base name of the LOD hierarchy"},
                "distances": {
                    "type": "object",
                    "description": "LOD switch distances in meters (e.g., {'LOD0': 0, 'LOD1': 50, 'LOD2': 200, 'LOD3': 500})",
                },
            },
            "required": ["base_name"],
        },
    ),
    Tool(
        name="blender_msfs_get_lod_info",
        description="Get information about an LOD hierarchy including vertex counts and distances",
        inputSchema={
            "type": "object",
            "properties": {
                "base_name": {"type": "string", "description": "Base name of the LOD hierarchy"},
            },
            "required": ["base_name"],
        },
    ),
    # MSFS Content Creation Tools - Materials
    Tool(
        name="blender_msfs_setup_material",
        description="Set up a material with flight simulator-specific PBR properties and extensions",
        inputSchema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the material to configure"},
                "msfs_type": {
                    "type": "string",
                    "enum": ["standard", "windshield", "clear_coat", "anisotropic", "hair", "sss", "glass", "geo_decal", "fresnel_fade", "parallax_window", "fake_terrain", "invisible", "environment_occluder"],
                    "description": "Material type for flight simulator rendering",
                },
                "base_color": {"type": "array", "items": {"type": "number"}, "description": "RGBA base color"},
                "metallic": {"type": "number", "minimum": 0, "maximum": 1, "description": "Metallic value (0-1)"},
                "roughness": {"type": "number", "minimum": 0, "maximum": 1, "description": "Roughness value (0-1)"},
                "emissive_color": {"type": "array", "items": {"type": "number"}, "description": "RGB emissive color"},
                "emissive_strength": {"type": "number", "description": "Emissive intensity"},
                "alpha": {"type": "number", "minimum": 0, "maximum": 1, "description": "Alpha/opacity (0-1)"},
                "double_sided": {"type": "boolean", "description": "Whether material is double-sided"},
            },
            "required": ["material_name"],
        },
    ),
    Tool(
        name="blender_msfs_create_glass_material",
        description="Create a glass material optimized for flight simulator (cockpit glass, windows)",
        inputSchema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name for the new material"},
                "tint_color": {"type": "array", "items": {"type": "number"}, "description": "RGB tint color"},
                "opacity": {"type": "number", "minimum": 0, "maximum": 1, "description": "Glass opacity (0 = fully transparent)"},
                "ior": {"type": "number", "description": "Index of refraction (default: 1.45)"},
                "is_windshield": {"type": "boolean", "description": "Enable windshield features (rain effects, wipers)"},
            },
            "required": ["material_name"],
        },
    ),
    Tool(
        name="blender_msfs_create_emissive_material",
        description="Create an emissive/light material for flight simulator (gauges, displays, lights)",
        inputSchema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name for the material"},
                "base_color": {"type": "array", "items": {"type": "number"}, "description": "RGBA base color (daytime appearance)"},
                "emissive_color": {"type": "array", "items": {"type": "number"}, "description": "RGB emissive color"},
                "emissive_strength": {"type": "number", "description": "Emission intensity (default: 1.0)"},
                "is_day_night": {"type": "boolean", "description": "Emission varies with time of day (night-only glow)"},
            },
            "required": ["material_name"],
        },
    ),
    Tool(
        name="blender_msfs_get_material_presets",
        description="Get list of available flight simulator material presets (vehicle_paint, chrome, glass, etc.)",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    # MSFS Content Creation Tools - Collision
    Tool(
        name="blender_msfs_create_collision_mesh",
        description="Create a simplified collision mesh from a source object for physics interactions",
        inputSchema={
            "type": "object",
            "properties": {
                "source_object_name": {"type": "string", "description": "Name of the source object"},
                "collision_type": {
                    "type": "string",
                    "enum": ["none", "collider", "road", "water", "trigger"],
                    "description": "Type of collision behavior",
                },
                "simplify": {"type": "boolean", "description": "Simplify the collision mesh (default: true)"},
                "simplify_ratio": {"type": "number", "minimum": 0.01, "maximum": 1.0, "description": "Simplification ratio (default: 0.3)"},
            },
            "required": ["source_object_name"],
        },
    ),
    Tool(
        name="blender_msfs_create_collision_box",
        description="Create a box collision primitive for an object (most efficient for physics)",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object to create collision for"},
                "collision_type": {"type": "string", "enum": ["none", "collider", "road", "water", "trigger"], "description": "Type of collision"},
                "padding": {"type": "number", "description": "Extra padding around the bounding box"},
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_msfs_create_collision_convex",
        description="Create a convex hull collision mesh (balance between accuracy and performance)",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the source object"},
                "collision_type": {"type": "string", "enum": ["none", "collider", "road", "water", "trigger"], "description": "Type of collision"},
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_msfs_tag_collision_type",
        description="Tag an existing mesh as a collision object",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "collision_type": {"type": "string", "enum": ["none", "collider", "road", "water", "trigger"], "description": "Type of collision"},
            },
            "required": ["object_name", "collision_type"],
        },
    ),
    # MSFS Content Creation Tools - Animation
    Tool(
        name="blender_msfs_add_animation_tag",
        description="Add an animation tag/event marker for flight simulator animation events",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the animated object"},
                "tag_type": {
                    "type": "string",
                    "enum": ["start", "end", "loop_start", "loop_end", "sound", "sound_start", "sound_stop", "effect", "effect_start", "effect_stop", "show", "hide", "event"],
                    "description": "Type of animation tag",
                },
                "frame": {"type": "integer", "description": "Frame number for the tag"},
                "tag_data": {"type": "string", "description": "Optional data string (e.g., sound file name)"},
            },
            "required": ["object_name", "tag_type", "frame"],
        },
    ),
    Tool(
        name="blender_msfs_setup_visibility_animation",
        description="Set up visibility animation for an object (show/hide during frame ranges)",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "visible_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Frame range when object is visible [start, end]",
                },
                "hidden_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Frame range when object is hidden [start, end]",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_msfs_configure_animation_loop",
        description="Configure animation looping behavior for flight simulator",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the animated object"},
                "behavior": {
                    "type": "string",
                    "enum": ["once", "loop", "ping_pong", "hold"],
                    "description": "Animation playback behavior",
                },
                "loop_start": {"type": "integer", "description": "Start frame of loop (defaults to action start)"},
                "loop_end": {"type": "integer", "description": "End frame of loop (defaults to action end)"},
                "loop_count": {"type": "integer", "description": "Number of loops (0 = infinite)"},
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_msfs_list_animation_tags",
        description="List all animation tags in the scene",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Filter by object name (optional)"},
            },
            "required": [],
        },
    ),
    # MSFS Content Creation Tools - Export
    Tool(
        name="blender_msfs_export_model",
        description="Export model(s) in flight simulator-compatible glTF format with LODs, collision, and animations",
        inputSchema={
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Output file path (.glb or .gltf)"},
                "objects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Object names to export (omit for selected/all)",
                },
                "include_lods": {"type": "boolean", "description": "Include LOD variants (default: true)"},
                "include_collision": {"type": "boolean", "description": "Include collision meshes (default: true)"},
                "include_animations": {"type": "boolean", "description": "Include animation data (default: true)"},
                "export_format": {"type": "string", "enum": ["GLB", "GLTF"], "description": "Export format (default: GLB)"},
            },
            "required": ["filepath"],
        },
    ),
    Tool(
        name="blender_msfs_validate_for_export",
        description="Validate model(s) for flight simulator compatibility and report issues",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Specific object to validate (omit for all selected/all)"},
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_msfs_get_export_settings",
        description="Get available flight simulator export settings and recommendations",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="blender_msfs_batch_export_lods",
        description="Export LOD hierarchy with proper structure (single file or separate files per LOD)",
        inputSchema={
            "type": "object",
            "properties": {
                "base_name": {"type": "string", "description": "Base name of the LOD hierarchy"},
                "output_dir": {"type": "string", "description": "Output directory path"},
                "separate_files": {"type": "boolean", "description": "Export each LOD as separate file (default: false)"},
            },
            "required": ["base_name", "output_dir"],
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
