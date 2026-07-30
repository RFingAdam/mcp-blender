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
    # AI Backend Management Tools
    Tool(
        name="blender_ai_list_backends",
        description="List available AI model generation backends with status (installed, available, capabilities)",
        inputSchema={
            "type": "object",
            "properties": {
                "available_only": {
                    "type": "boolean",
                    "default": True,
                    "description": "Only list backends that are currently available (default: true)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_ai_set_backend",
        description="Set the preferred AI backend for model generation (e.g., 'comfyui', 'rodin', 'triposr')",
        inputSchema={
            "type": "object",
            "properties": {
                "backend": {
                    "type": "string",
                    "description": "Backend name to set as preferred",
                },
                "prefer_local": {
                    "type": "boolean",
                    "description": "Prefer local backends over cloud APIs",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_ai_configure_backend",
        description="Configure settings for a specific AI backend (API keys, URLs, model paths, device, timeout)",
        inputSchema={
            "type": "object",
            "properties": {
                "backend": {
                    "type": "string",
                    "description": "Backend name to configure",
                },
                "config": {
                    "type": "object",
                    "description": "Configuration dictionary (e.g., {'api_base_url': 'http://...', 'api_key': '...', 'timeout': 120})",
                },
            },
            "required": ["backend"],
        },
    ),
    Tool(
        name="blender_ai_generate_model_sync",
        description="Generate a 3D model and wait for completion (synchronous). Combines generate + poll + optional import in one call. Returns the final model when done.",
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text description of the model to generate",
                },
                "image_path": {
                    "type": "string",
                    "description": "Path to input image for image-to-3D generation",
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
                "max_wait": {
                    "type": "integer",
                    "default": 300,
                    "description": "Maximum wait time in seconds (default: 300)",
                },
                "auto_import": {
                    "type": "boolean",
                    "default": True,
                    "description": "Automatically import the completed model into Blender",
                },
            },
            "required": [],
        },
    ),
    # AI Texture Generation Tools
    Tool(
        name="blender_ai_generate_texture",
        description="Generate a PBR texture set (diffuse, roughness, normal, metallic) from a text prompt using SDXL and apply it to a Blender object",
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text description of the desired texture (e.g., 'worn red brick wall', 'brushed steel')",
                },
                "object_name": {
                    "type": "string",
                    "description": "Name of the Blender object to apply the texture to",
                },
                "resolution": {
                    "type": "integer",
                    "enum": [512, 1024, 2048],
                    "default": 1024,
                    "description": "Texture resolution in pixels",
                },
                "auto_apply": {
                    "type": "boolean",
                    "default": True,
                    "description": "Automatically apply generated textures to the object's material",
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "What to avoid in generation (default: 'blurry, low quality, watermark, text, logo')",
                },
                "seed": {
                    "type": "integer",
                    "description": "Random seed for reproducible results",
                },
            },
            "required": ["prompt"],
        },
    ),
    Tool(
        name="blender_ai_generate_texture_sync",
        description="Generate PBR texture and wait for completion (synchronous). Returns texture file paths when done.",
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text description of the desired texture (e.g., 'worn red brick wall', 'brushed steel')",
                },
                "object_name": {
                    "type": "string",
                    "description": "Name of the Blender object to apply the texture to",
                },
                "resolution": {
                    "type": "integer",
                    "enum": [512, 1024, 2048],
                    "default": 1024,
                    "description": "Texture resolution in pixels",
                },
                "auto_apply": {
                    "type": "boolean",
                    "default": True,
                    "description": "Automatically apply generated textures to the object's material",
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "What to avoid in generation (default: 'blurry, low quality, watermark, text, logo')",
                },
                "seed": {
                    "type": "integer",
                    "description": "Random seed for reproducible results",
                },
                "timeout": {
                    "type": "integer",
                    "default": 300,
                    "description": "Maximum wait time in seconds (default: 300)",
                },
            },
            "required": ["prompt"],
        },
    ),
    Tool(
        name="blender_ai_generate_reference_image",
        description="Generate a concept art / reference image from a text prompt using SDXL (useful for image-to-3D workflows)",
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text description of the desired image (e.g., 'isometric medieval castle, concept art')",
                },
                "resolution": {
                    "type": "integer",
                    "enum": [512, 1024, 2048],
                    "default": 1024,
                    "description": "Image resolution in pixels",
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "What to avoid in generation",
                },
                "seed": {
                    "type": "integer",
                    "description": "Random seed for reproducible results",
                },
            },
            "required": ["prompt"],
        },
    ),
    Tool(
        name="blender_ai_inpaint_texture",
        description="Generate inpainted content for a masked region of an existing texture using SDXL",
        inputSchema={
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Path to the texture image to inpaint",
                },
                "mask_path": {
                    "type": "string",
                    "description": "Path to the mask image (white = inpaint region, black = keep)",
                },
                "prompt": {
                    "type": "string",
                    "description": "Text description of what to paint in the masked region",
                },
                "strength": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 0.85,
                    "description": "Inpainting strength (0.0 = no change, 1.0 = full repaint)",
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "What to avoid in generation",
                },
                "seed": {
                    "type": "integer",
                    "description": "Random seed for reproducible results",
                },
            },
            "required": ["image_path", "mask_path", "prompt"],
        },
    ),
    Tool(
        name="blender_ai_texture_from_render",
        description="Generate a texture from a depth or normal render of a Blender object using ControlNet guidance",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the Blender object to render and generate texture for",
                },
                "prompt": {
                    "type": "string",
                    "description": "Text description of the desired texture (e.g., 'weathered stone wall')",
                },
                "control_type": {
                    "type": "string",
                    "enum": ["depth", "normal"],
                    "default": "depth",
                    "description": "Type of control image to render (depth map or normal map)",
                },
                "auto_apply": {
                    "type": "boolean",
                    "default": True,
                    "description": "Automatically apply generated texture to the object",
                },
                "controlnet_strength": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 0.85,
                    "description": "ControlNet conditioning strength",
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "What to avoid in generation",
                },
                "seed": {
                    "type": "integer",
                    "description": "Random seed for reproducible results",
                },
            },
            "required": ["object_name", "prompt"],
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
    # ==================== MSFS Livery Tools ====================
    Tool(
        name="blender_msfs_livery_setup_paint_mode",
        description="Set up an object for texture painting with UV map and paint texture",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object to paint"},
                "texture_resolution": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Texture resolution [width, height] (default: [4096, 4096])",
                },
                "create_uvs": {"type": "boolean", "description": "Create UV map if none exists (default: true)"},
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_msfs_livery_create_paint_layers",
        description="Create paint layer images for livery workflow (primer, base_color, cheatline, belly, details, decals, weathering, clearcoat)",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "layers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Layer names to create (default: all layers)",
                },
                "texture_resolution": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Resolution for each layer [width, height]",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_msfs_livery_load_template_overlay",
        description="Load a reference template image as overlay for painting",
        inputSchema={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Path to template image"},
                "object_name": {"type": "string", "description": "Object to use as reference (optional)"},
                "opacity": {"type": "number", "description": "Overlay opacity 0-1 (default: 0.5)"},
            },
            "required": ["image_path"],
        },
    ),
    Tool(
        name="blender_msfs_livery_export_uv_layout",
        description="Export UV layout as an image for painting reference in external editors",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "output_path": {"type": "string", "description": "Output image path"},
                "resolution": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Output resolution [width, height]",
                },
                "fill_opacity": {"type": "number", "description": "Fill opacity for UV faces (default: 0)"},
                "line_thickness": {"type": "number", "description": "UV edge line thickness (default: 1)"},
            },
            "required": ["object_name", "output_path"],
        },
    ),
    Tool(
        name="blender_msfs_livery_set_paint_brush",
        description="Configure paint brush settings with presets (soft_airbrush, hard_edge, detail_brush, smudge, clone, fill)",
        inputSchema={
            "type": "object",
            "properties": {
                "preset": {"type": "string", "description": "Brush preset name"},
                "color": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "RGBA paint color (0-1 range)",
                },
                "size": {"type": "integer", "description": "Brush size in pixels"},
                "strength": {"type": "number", "description": "Brush strength (0-1)"},
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_msfs_livery_sample_color",
        description="Sample a color from an image at specific coordinates for matching reference livery colors",
        inputSchema={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Path to image file"},
                "x": {"type": "integer", "description": "X coordinate to sample"},
                "y": {"type": "integer", "description": "Y coordinate to sample"},
            },
            "required": ["image_path", "x", "y"],
        },
    ),
    Tool(
        name="blender_msfs_livery_get_paint_presets",
        description="Get available paint presets for livery painting (layers and brushes)",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="blender_msfs_livery_get_aircraft_templates",
        description="Get list of supported aircraft templates (FBW A32NX, Fenix, PMDG, iniBuilds, etc.)",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="blender_msfs_livery_get_template_info",
        description="Get detailed template information for an aircraft including texture sizes and UV regions",
        inputSchema={
            "type": "object",
            "properties": {
                "aircraft_id": {
                    "type": "string",
                    "description": "Aircraft identifier (e.g., 'fbw_a32nx', 'pmdg_737', 'fenix_a320')",
                },
            },
            "required": ["aircraft_id"],
        },
    ),
    Tool(
        name="blender_msfs_livery_download_template",
        description="Download or generate template files for an aircraft at correct resolution",
        inputSchema={
            "type": "object",
            "properties": {
                "aircraft_id": {"type": "string", "description": "Aircraft identifier"},
                "output_dir": {"type": "string", "description": "Directory to save template files"},
            },
            "required": ["aircraft_id", "output_dir"],
        },
    ),
    Tool(
        name="blender_msfs_livery_analyze",
        description="Analyze a livery image for colors, patterns, and design elements",
        inputSchema={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Path to livery image"},
                "aircraft_type": {"type": "string", "description": "Type of aircraft for region analysis (optional)"},
            },
            "required": ["image_path"],
        },
    ),
    Tool(
        name="blender_msfs_livery_transfer",
        description="Transfer livery design between different aircraft types with UV remapping",
        inputSchema={
            "type": "object",
            "properties": {
                "source_image": {"type": "string", "description": "Path to source livery image"},
                "source_aircraft": {"type": "string", "description": "Source aircraft ID"},
                "target_aircraft": {"type": "string", "description": "Target aircraft ID"},
                "output_dir": {"type": "string", "description": "Output directory for transferred livery"},
                "preserve_colors": {"type": "boolean", "description": "Preserve original colors (default: true)"},
                "preserve_text": {"type": "boolean", "description": "Attempt to preserve text elements (default: true)"},
            },
            "required": ["source_image", "source_aircraft", "target_aircraft", "output_dir"],
        },
    ),
    Tool(
        name="blender_msfs_livery_extract_colors",
        description="Extract color palette from livery image for recreating designs",
        inputSchema={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Path to livery image"},
                "num_colors": {"type": "integer", "description": "Number of colors to extract (default: 8)"},
                "exclude_white": {"type": "boolean", "description": "Exclude white/near-white colors (default: true)"},
            },
            "required": ["image_path"],
        },
    ),
    Tool(
        name="blender_msfs_livery_map_elements",
        description="Map design elements (cheatline, logo, registration) between aircraft templates",
        inputSchema={
            "type": "object",
            "properties": {
                "source_aircraft": {"type": "string", "description": "Source aircraft ID"},
                "target_aircraft": {"type": "string", "description": "Target aircraft ID"},
                "elements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Elements to map (default: all)",
                },
            },
            "required": ["source_aircraft", "target_aircraft"],
        },
    ),
    Tool(
        name="blender_msfs_livery_export_textures",
        description="Export livery textures from an object in PNG, TARGA, or for DDS conversion",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object with livery materials"},
                "output_dir": {"type": "string", "description": "Directory to save exported textures"},
                "texture_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Types to export: albedo, normal, composite, emissive (default: albedo)",
                },
                "format": {"type": "string", "description": "Output format: PNG, TARGA (default: PNG)"},
            },
            "required": ["object_name", "output_dir"],
        },
    ),
    Tool(
        name="blender_msfs_livery_create_package",
        description="Create MSFS livery package folder structure with manifest.json and layout.json",
        inputSchema={
            "type": "object",
            "properties": {
                "aircraft_id": {"type": "string", "description": "Aircraft identifier (e.g., 'fbw_a32nx')"},
                "livery_name": {"type": "string", "description": "Name for the livery"},
                "output_dir": {"type": "string", "description": "Base directory for the package"},
                "texture_dir": {"type": "string", "description": "Directory containing texture files to include"},
                "airline": {"type": "string", "description": "Airline name for aircraft.cfg"},
                "description": {"type": "string", "description": "Livery description"},
                "author": {"type": "string", "description": "Author name"},
            },
            "required": ["aircraft_id", "livery_name", "output_dir"],
        },
    ),
    Tool(
        name="blender_msfs_livery_convert_to_dds",
        description="Convert texture to DDS format for MSFS (requires texconv)",
        inputSchema={
            "type": "object",
            "properties": {
                "input_path": {"type": "string", "description": "Path to input image"},
                "output_path": {"type": "string", "description": "Path for output DDS (optional)"},
                "texture_type": {
                    "type": "string",
                    "description": "Type for format selection: albedo, normal, composite, emissive (default: albedo)",
                },
            },
            "required": ["input_path"],
        },
    ),
    Tool(
        name="blender_msfs_livery_validate_package",
        description="Validate a livery package structure for MSFS compatibility",
        inputSchema={
            "type": "object",
            "properties": {
                "package_dir": {"type": "string", "description": "Path to the livery package"},
            },
            "required": ["package_dir"],
        },
    ),
    # ==================== Edit Mode Mesh Operations ====================
    Tool(
        name="blender_mesh_extrude",
        description="Extrude faces, edges, or vertices along an offset vector. The most fundamental mesh modeling operation - creates new geometry by extending existing elements outward.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "mode": {
                    "type": "string",
                    "enum": ["FACES", "EDGES", "VERTICES", "REGION"],
                    "default": "FACES",
                    "description": "What to extrude: FACES (individual or region), EDGES, or VERTICES",
                },
                "indices": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Indices of faces/edges/vertices to extrude",
                },
                "offset": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Extrusion direction and distance [x, y, z]",
                },
                "individual": {
                    "type": "boolean",
                    "default": False,
                    "description": "Extrude each face individually (only for FACES mode)",
                },
            },
            "required": ["object_name", "indices", "offset"],
        },
    ),
    Tool(
        name="blender_mesh_inset",
        description="Inset faces to create border loops. Essential for panel lines, window frames, recessed details on hard surfaces.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "face_indices": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Indices of faces to inset",
                },
                "thickness": {"type": "number", "default": 0.1, "description": "Inset distance from edges"},
                "depth": {"type": "number", "default": 0.0, "description": "Push inset faces in (+) or out (-)"},
                "use_even_offset": {"type": "boolean", "default": True, "description": "Even thickness around corners"},
                "use_relative_offset": {"type": "boolean", "default": False, "description": "Scale offset by face size"},
            },
            "required": ["object_name", "face_indices"],
        },
    ),
    Tool(
        name="blender_mesh_bevel",
        description="Bevel edges for smooth transitions and rounded corners. Can target specific edges or auto-select all sharp edges.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "edge_indices": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Edge indices to bevel (omit to bevel all sharp edges)",
                },
                "width": {"type": "number", "default": 0.1, "description": "Bevel width/offset"},
                "segments": {"type": "integer", "default": 1, "description": "Number of bevel segments (more = smoother)"},
                "profile": {"type": "number", "default": 0.5, "description": "Bevel profile shape (0=concave, 0.5=round, 1=convex)"},
                "clamp_overlap": {"type": "boolean", "default": True, "description": "Prevent overlapping bevels"},
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_mesh_loop_cut",
        description="Add edge loops (loop cuts) to a mesh for topology control. Adds resolution to specific areas without subdividing the whole mesh.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "edge_index": {"type": "integer", "description": "Reference edge index that defines the loop direction"},
                "cuts": {"type": "integer", "default": 1, "description": "Number of cuts to add"},
                "smoothness": {"type": "number", "default": 0.0, "description": "Smoothing factor (0=sharp, 1=smooth)"},
            },
            "required": ["object_name", "edge_index"],
        },
    ),
    # ==================== Curve Creation & Conversion ====================
    Tool(
        name="blender_curve_create",
        description="Create a Bezier, NURBS, or Poly curve from control points. Curves enable smooth profiles, body panels, pipe routing, and organic shapes.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name for the curve object"},
                "type": {
                    "type": "string",
                    "enum": ["BEZIER", "NURBS", "POLY"],
                    "default": "BEZIER",
                    "description": "Curve type",
                },
                "points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Control points [[x,y,z], ...]. For NURBS, optional 4th value is weight.",
                },
                "handles": {
                    "type": "array",
                    "description": "Bezier handle config per point. String ('AUTO','VECTOR','FREE','ALIGNED') or dict with 'type', 'left':[x,y,z], 'right':[x,y,z]",
                },
                "cyclic": {"type": "boolean", "default": False, "description": "Close the curve into a loop"},
                "resolution": {"type": "integer", "default": 12, "description": "Curve smoothness (segments between control points)"},
                "location": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Object location [x, y, z]",
                },
            },
            "required": ["points"],
        },
    ),
    Tool(
        name="blender_curve_to_mesh",
        description="Convert a curve to mesh with optional bevel (tube) or extrude (flat panel). A curve with bevel_depth becomes a tube; with extrude becomes a flat panel.",
        inputSchema={
            "type": "object",
            "properties": {
                "curve_name": {"type": "string", "description": "Name of the curve object"},
                "bevel_depth": {"type": "number", "default": 0, "description": "Tube radius (0 = no tube)"},
                "bevel_resolution": {"type": "integer", "default": 4, "description": "Tube cross-section smoothness"},
                "extrude": {"type": "number", "default": 0, "description": "Flat extrusion depth"},
                "fill_type": {
                    "type": "string",
                    "enum": ["FULL", "BACK", "FRONT", "HALF", "NONE"],
                    "default": "FULL",
                    "description": "Cap fill type",
                },
                "twist_method": {"type": "string", "default": "MINIMUM", "description": "Twist computation method"},
                "apply_as_mesh": {
                    "type": "boolean",
                    "default": True,
                    "description": "Convert to mesh object (default: true)",
                },
            },
            "required": ["curve_name"],
        },
    ),
    Tool(
        name="blender_curve_from_mesh_edge",
        description="Extract a curve from mesh edge indices. Useful for creating curves that follow existing geometry for pipe routing or profile extraction.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "edge_indices": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Edge indices to extract as a curve",
                },
                "curve_type": {
                    "type": "string",
                    "enum": ["BEZIER", "NURBS", "POLY"],
                    "default": "POLY",
                    "description": "Output curve type",
                },
            },
            "required": ["object_name", "edge_indices"],
        },
    ),
    # ==================== Text Objects ====================
    Tool(
        name="blender_text_create",
        description="Create a 3D text object from Blender's native FONT/TextCurve data. Unlike reconstructing glyphs from a raster/height-map, letterforms stay smooth vector curves at any extrude/bevel_depth, so corners round correctly instead of stair-stepping. Use this for engraved or relief text (signage, badges, embossed logos) instead of voxel/pixel-based letter reconstruction.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "default": "Text", "description": "Name for the text object"},
                "content": {"type": "string", "description": "The text to display"},
                "location": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Object location [x, y, z]",
                },
                "rotation": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Object rotation in radians [x, y, z]",
                },
                "size": {"type": "number", "default": 1.0, "description": "Font size"},
                "extrude": {"type": "number", "default": 0.0, "description": "Depth to extrude the flat glyph outline (0 = flat text)"},
                "bevel_depth": {"type": "number", "default": 0.0, "description": "Bevel/round the extruded edges by this radius"},
                "bevel_resolution": {"type": "integer", "default": 4, "description": "Bevel smoothness (segments)"},
                "letter_spacing": {"type": "number", "default": 1.0, "description": "Extra spacing between characters"},
                "word_spacing": {"type": "number", "default": 1.0, "description": "Extra spacing between words"},
                "line_spacing": {"type": "number", "default": 1.0, "description": "Spacing between lines"},
                "align_x": {
                    "type": "string",
                    "enum": ["LEFT", "CENTER", "RIGHT", "JUSTIFY", "FLUSH"],
                    "default": "LEFT",
                    "description": "Horizontal alignment",
                },
                "align_y": {
                    "type": "string",
                    "enum": ["TOP_BASELINE", "TOP", "CENTER", "BOTTOM", "BOTTOM_BASELINE"],
                    "default": "BOTTOM_BASELINE",
                    "description": "Vertical alignment",
                },
                "fill_type": {
                    "type": "string",
                    "enum": ["NONE", "BACK", "FRONT", "BOTH"],
                    "default": "BOTH",
                    "description": "Which caps to fill on the extruded solid (BOTH = solid front+back)",
                },
                "font_path": {"type": "string", "description": "Path to a .ttf/.otf font file (default: Blender's built-in font)"},
            },
            "required": ["content"],
        },
    ),
    Tool(
        name="blender_text_set_properties",
        description="Set a text object's content, font, extrude, bevel, spacing, or alignment. Only the parameters passed are changed, so you can iterate quickly (e.g. dialing in depth and corner roundness to match an existing relief) without recreating the object from scratch.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the text object"},
                "content": {"type": "string", "description": "New text content"},
                "size": {"type": "number", "description": "Font size"},
                "extrude": {"type": "number", "description": "Extrude depth"},
                "bevel_depth": {"type": "number", "description": "Bevel radius"},
                "bevel_resolution": {"type": "integer", "description": "Bevel smoothness (segments)"},
                "letter_spacing": {"type": "number", "description": "Extra spacing between characters"},
                "word_spacing": {"type": "number", "description": "Extra spacing between words"},
                "line_spacing": {"type": "number", "description": "Spacing between lines"},
                "align_x": {"type": "string", "enum": ["LEFT", "CENTER", "RIGHT", "JUSTIFY", "FLUSH"], "description": "Horizontal alignment"},
                "align_y": {"type": "string", "enum": ["TOP_BASELINE", "TOP", "CENTER", "BOTTOM", "BOTTOM_BASELINE"], "description": "Vertical alignment"},
                "fill_type": {"type": "string", "enum": ["NONE", "BACK", "FRONT", "BOTH"], "description": "Which caps to fill on the extruded solid"},
                "font_path": {"type": "string", "description": "Path to a .ttf/.otf font file"},
                "location": {"type": "array", "items": {"type": "number"}, "description": "Object location [x, y, z]"},
                "rotation": {"type": "array", "items": {"type": "number"}, "description": "Object rotation in radians [x, y, z]"},
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_text_to_mesh",
        description="Convert a text object to a real mesh, baking the vector letterforms into geometry usable with boolean_op, export_stl, modifiers, etc. Automatically welds the duplicate coincident vertices Blender's convert operator leaves at each glyph's spline seam, so the result is manifold instead of reading as non-manifold at every letter.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the text object to convert"},
                "keep_original": {"type": "boolean", "default": False, "description": "Keep the original text object and convert a duplicate instead"},
                "new_name": {"type": "string", "description": "Name for the converted duplicate (only used if keep_original is true)"},
            },
            "required": ["object_name"],
        },
    ),
    # ==================== Boolean Operations ====================
    Tool(
        name="blender_boolean_op",
        description="Perform a boolean operation (union, difference, intersect) between two objects in a single call. Optionally apply immediately and hide the tool object.",
        inputSchema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Name of the object to modify"},
                "tool": {"type": "string", "description": "Name of the object to use as boolean cutter/operand"},
                "operation": {
                    "type": "string",
                    "enum": ["UNION", "DIFFERENCE", "INTERSECT"],
                    "description": "Boolean operation type",
                },
                "solver": {
                    "type": "string",
                    "enum": ["FAST", "EXACT"],
                    "default": "EXACT",
                    "description": "Boolean solver (EXACT is more reliable, FAST is quicker)",
                },
                "apply": {
                    "type": "boolean",
                    "default": True,
                    "description": "Apply the modifier immediately (default: true)",
                },
                "hide_tool": {
                    "type": "boolean",
                    "default": True,
                    "description": "Hide the tool object after operation (default: true)",
                },
            },
            "required": ["target", "tool", "operation"],
        },
    ),
    # ==================== Mesh & Transform Utilities ====================
    Tool(
        name="blender_mesh_from_data",
        description="Create a mesh object from raw vertex/face data using mesh.from_pydata(). Useful for procedural geometry.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name for the new mesh object"},
                "vertices": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "List of vertex positions [[x,y,z], ...]",
                },
                "faces": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "description": "List of face vertex-index lists [[0,1,2,3], ...]",
                },
                "edges": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "description": "Optional list of edge vertex-index pairs [[0,1], ...]",
                },
                "location": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Location [x, y, z]",
                },
                "smooth_shade": {"type": "boolean", "description": "Apply smooth shading (default: false)"},
            },
            "required": ["name", "vertices", "faces"],
        },
    ),
    Tool(
        name="blender_object_set_origin",
        description="Set the origin (pivot point) of an object",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "origin_type": {
                    "type": "string",
                    "enum": ["GEOMETRY_CENTER", "ORIGIN_CURSOR", "ORIGIN_CENTER_OF_MASS", "ORIGIN_CENTER_OF_VOLUME"],
                    "description": "How to compute the new origin",
                },
                "cursor_location": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Set 3D cursor here first (used with ORIGIN_CURSOR)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_object_apply_transforms",
        description="Apply (bake) object transforms to mesh data so location/rotation/scale reset to identity",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object"},
                "location": {"type": "boolean", "description": "Apply location (default: true)"},
                "rotation": {"type": "boolean", "description": "Apply rotation (default: true)"},
                "scale": {"type": "boolean", "description": "Apply scale (default: true)"},
            },
            "required": ["object_name"],
        },
    ),
    # ==================== Script Execution ====================
    Tool(
        name="blender_execute_script",
        description="Execute arbitrary Python/bmesh script in Blender's context. Enables real mesh modeling with vertices, edges, faces, extrusion, bevel, and full Blender API access. The script can import bmesh, mathutils, math, etc. Set a 'result' variable in the script to return data.",
        inputSchema={
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "Python script to execute in Blender. Has 'bpy' pre-loaded. Can import bmesh, mathutils, etc.",
                },
                "timeout": {
                    "type": "number",
                    "description": "Execution timeout in seconds (default: 30)",
                },
            },
            "required": ["script"],
        },
    ),
    # ==================== Multi-Angle Rendering ====================
    Tool(
        name="blender_render_multi_angle",
        description="Render an object from multiple angles (front, right, top, perspective) for visual feedback. Uses Workbench engine for speed. Returns file paths to rendered PNG images.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of object to render (omit for all mesh objects)",
                },
                "angles": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["front", "right", "top", "perspective"]},
                    "description": "Angles to render (default: all four)",
                },
                "resolution": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Render resolution [width, height] (default: [512, 512])",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Output directory for renders (default: temp dir)",
                },
            },
            "required": [],
        },
    ),
    # ==================== Vision Analysis ====================
    Tool(
        name="blender_analyze_viewport",
        description="Render multi-angle views and analyze with Ollama vision model. Returns structured feedback with quality score, issues, and fix suggestions for iterative mesh refinement.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of object to analyze (omit for all)",
                },
                "reference_image": {
                    "type": "string",
                    "description": "Path to reference image for comparison",
                },
                "prompt": {
                    "type": "string",
                    "description": "Analysis prompt/instructions for the vision model",
                },
                "resolution": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Render resolution [width, height] (default: [512, 512])",
                },
                "ollama_host": {
                    "type": "string",
                    "description": "Ollama server URL (default: http://127.0.0.1:11434)",
                },
                "ollama_model": {
                    "type": "string",
                    "description": "Vision model name (default: llama3.2-vision:11b)",
                },
            },
            "required": [],
        },
    ),
    # ==================== Refinement Loop ====================
    Tool(
        name="blender_refine_iteration",
        description="Run one iteration of the AI refinement loop: render object from multiple angles, analyze with vision model, check for convergence. Returns score, issues, and whether to continue refining.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of object being refined",
                },
                "reference_image": {
                    "type": "string",
                    "description": "Path to reference image for comparison",
                },
                "prompt": {
                    "type": "string",
                    "description": "Evaluation prompt for the vision model",
                },
                "iteration": {
                    "type": "integer",
                    "description": "Current iteration number (0-based)",
                },
                "previous_score": {
                    "type": "number",
                    "description": "Score from previous iteration (for delta calculation)",
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Maximum iterations before forced convergence (default: 10)",
                },
            },
            "required": [],
        },
    ),
    # ==================== Refinement Session Management ====================
    Tool(
        name="blender_refine_create_session",
        description="Create a new refinement session to track iterative improvement of a 3D model",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the object being refined",
                },
                "reference_image": {
                    "type": "string",
                    "description": "Optional reference image path",
                },
                "prompt": {
                    "type": "string",
                    "description": "Description of what the model should look like",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_refine_get_session",
        description="Get details and iteration history of a refinement session",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Refinement session ID",
                },
            },
            "required": ["session_id"],
        },
    ),
    Tool(
        name="blender_refine_list_sessions",
        description="List all refinement sessions with their status and iteration counts",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    # ==================== AI Evaluation & Self-Refinement ====================
    Tool(
        name="blender_ai_evaluate",
        description="Evaluate any render or output (model, texture, animation) using Ollama vision with category-specific criteria. Returns structured scores and improvement suggestions.",
        inputSchema={
            "type": "object",
            "properties": {
                "render_path": {
                    "type": "string",
                    "description": "Path to the rendered image to evaluate",
                },
                "category": {
                    "type": "string",
                    "enum": ["model", "texture", "animation"],
                    "default": "model",
                    "description": "Evaluation category: model (geometry/proportions), texture (PBR/tiling), or animation (motion/timing)",
                },
                "reference_image": {
                    "type": "string",
                    "description": "Optional reference image path for comparison",
                },
                "prompt": {
                    "type": "string",
                    "description": "Additional evaluation context or instructions",
                },
                "ollama_host": {
                    "type": "string",
                    "description": "Ollama server URL (default: http://127.0.0.1:11434)",
                },
                "ollama_model": {
                    "type": "string",
                    "description": "Vision model name (default: llama3.2-vision:11b)",
                },
            },
            "required": ["render_path"],
        },
    ),
    Tool(
        name="blender_ai_refine",
        description="Run one iteration of AI self-refinement: render object, evaluate with vision model, return scores and suggestions. Call repeatedly in a loop, applying suggestions between calls, until converged.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the Blender object to refine",
                },
                "prompt": {
                    "type": "string",
                    "description": "Description of the desired result for evaluation",
                },
                "category": {
                    "type": "string",
                    "enum": ["model", "texture", "animation"],
                    "default": "model",
                    "description": "Refinement category",
                },
                "max_iterations": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum iterations before forced convergence",
                },
                "quality_threshold": {
                    "type": "number",
                    "default": 0.85,
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Score threshold to consider converged (0.0-1.0)",
                },
                "materials": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Material names for texture refinement (optional)",
                },
                "ollama_host": {
                    "type": "string",
                    "description": "Ollama server URL (default: http://127.0.0.1:11434)",
                },
                "ollama_model": {
                    "type": "string",
                    "description": "Vision model name (default: llama3.2-vision:11b)",
                },
            },
            "required": ["object_name", "prompt"],
        },
    ),
    # AI Mesh Processing Tools
    Tool(
        name="blender_ai_mesh_cleanup",
        description="Clean up a generated mesh: remove doubles, fix normals, remove loose geometry, remove degenerate faces. Essential post-processing step after AI model generation.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to clean up",
                },
                "remove_doubles": {
                    "type": "boolean",
                    "default": True,
                    "description": "Merge overlapping vertices (default: true)",
                },
                "merge_distance": {
                    "type": "number",
                    "default": 0.0001,
                    "description": "Distance threshold for merging vertices (default: 0.0001)",
                },
                "fix_normals": {
                    "type": "boolean",
                    "default": True,
                    "description": "Recalculate face normals to point outward (default: true)",
                },
                "remove_loose": {
                    "type": "boolean",
                    "default": True,
                    "description": "Remove loose vertices and edges (default: true)",
                },
                "remove_degenerate": {
                    "type": "boolean",
                    "default": True,
                    "description": "Remove zero-area faces (default: true)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_ai_mesh_decimate",
        description="Reduce polygon count of a mesh while preserving shape. Supports COLLAPSE, UN_SUBDIVIDE, and PLANAR methods. Can target specific vertex groups and optionally preserve UVs.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to decimate",
                },
                "ratio": {
                    "type": "number",
                    "default": 0.5,
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Target ratio of faces to keep (0.0-1.0, default: 0.5)",
                },
                "method": {
                    "type": "string",
                    "enum": ["COLLAPSE", "UN_SUBDIVIDE", "PLANAR"],
                    "default": "COLLAPSE",
                    "description": "Decimation method (default: COLLAPSE)",
                },
                "triangulate": {
                    "type": "boolean",
                    "default": False,
                    "description": "Triangulate mesh before decimating (default: false)",
                },
                "preserve_uvs": {
                    "type": "boolean",
                    "default": True,
                    "description": "Preserve UV seams during decimation (default: true)",
                },
                "vertex_group": {
                    "type": "string",
                    "description": "Vertex group name to limit decimation to (optional)",
                },
                "invert_vertex_group": {
                    "type": "boolean",
                    "default": False,
                    "description": "Invert vertex group selection (default: false)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_ai_mesh_remesh",
        description="Retopologize a mesh using VOXEL or SMOOTH methods. Controls voxel size, octree depth, and smoothing. Useful for converting AI-generated meshes to clean topology.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to remesh",
                },
                "method": {
                    "type": "string",
                    "enum": ["VOXEL", "SMOOTH"],
                    "default": "VOXEL",
                    "description": "Remesh method (default: VOXEL)",
                },
                "voxel_size": {
                    "type": "number",
                    "default": 0.05,
                    "description": "Voxel size for VOXEL method - smaller = more detail (default: 0.05)",
                },
                "octree_depth": {
                    "type": "number",
                    "default": 5,
                    "description": "Octree depth for SMOOTH method (1-10, default: 5)",
                },
                "smooth_normals": {
                    "type": "boolean",
                    "default": True,
                    "description": "Smooth normals after remeshing (default: true)",
                },
                "apply_smooth": {
                    "type": "boolean",
                    "default": True,
                    "description": "Apply smoothing modifier after remesh (default: true)",
                },
                "smooth_factor": {
                    "type": "number",
                    "default": 0.5,
                    "description": "Smoothing strength (0.0-1.0, default: 0.5)",
                },
                "smooth_iterations": {
                    "type": "number",
                    "default": 2,
                    "description": "Number of smoothing iterations (default: 2)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_ai_mesh_optimize",
        description="Run full optimization pipeline on a mesh: cleanup, decimation, auto-UV, and normal smoothing in one call. Convenience wrapper for post-generation processing.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to optimize",
                },
                "cleanup": {
                    "type": "boolean",
                    "default": True,
                    "description": "Run mesh cleanup step (default: true)",
                },
                "decimate": {
                    "type": "boolean",
                    "default": True,
                    "description": "Run decimation step (default: true)",
                },
                "decimate_ratio": {
                    "type": "number",
                    "default": 0.5,
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Decimation ratio if decimate is enabled (default: 0.5)",
                },
                "auto_uv": {
                    "type": "boolean",
                    "default": True,
                    "description": "Generate UV maps (default: true)",
                },
                "smooth_normals": {
                    "type": "boolean",
                    "default": True,
                    "description": "Smooth normals (default: true)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_ai_auto_uv",
        description="Generate UV maps for a mesh using SMART or LIGHTMAP projection. Controls angle limit, island margin, area weighting, and aspect correction.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to UV unwrap",
                },
                "method": {
                    "type": "string",
                    "enum": ["SMART", "LIGHTMAP"],
                    "default": "SMART",
                    "description": "UV projection method (default: SMART)",
                },
                "angle_limit": {
                    "type": "number",
                    "default": 66.0,
                    "description": "Angle limit for island detection in degrees (default: 66.0)",
                },
                "island_margin": {
                    "type": "number",
                    "default": 0.02,
                    "description": "Margin between UV islands (default: 0.02)",
                },
                "area_weight": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Weight for face area in island placement (default: 0.0)",
                },
                "correct_aspect": {
                    "type": "boolean",
                    "default": True,
                    "description": "Correct for non-square textures (default: true)",
                },
                "scale_to_bounds": {
                    "type": "boolean",
                    "default": True,
                    "description": "Scale UV islands to fill UV space (default: true)",
                },
                "uv_layer_name": {
                    "type": "string",
                    "description": "Name for the UV layer (optional, auto-generated if not specified)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_ai_fix_mesh_issues",
        description="Fix common mesh problems: non-manifold edges, holes, inverted normals, interior faces. Useful for repairing AI-generated meshes before export.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to fix",
                },
                "fix_non_manifold": {
                    "type": "boolean",
                    "default": True,
                    "description": "Fix non-manifold edges (default: true)",
                },
                "fill_holes": {
                    "type": "boolean",
                    "default": True,
                    "description": "Fill holes in the mesh (default: true)",
                },
                "max_hole_edges": {
                    "type": "number",
                    "default": 12,
                    "description": "Maximum edges in a hole to fill (default: 12)",
                },
                "fix_normals": {
                    "type": "boolean",
                    "default": True,
                    "description": "Recalculate and fix normals (default: true)",
                },
                "remove_interior_faces": {
                    "type": "boolean",
                    "default": True,
                    "description": "Remove faces inside the mesh volume (default: true)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_ai_mesh_stats",
        description="Get detailed statistics about a mesh: vertex/edge/face counts, bounding box dimensions, non-manifold edges, UV layers, material slots, and more.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to analyze",
                },
            },
            "required": ["object_name"],
        },
    ),
    # AI Backend Probing Tool
    Tool(
        name="blender_ai_probe_backends",
        description="Probe all AI backends and report capabilities: which ComfyUI 3D generation nodes are available (SF3D, TripoSR, TripoSG, InstantMesh, Hunyuan3D, CRM, Zero123Plus), GPU VRAM, queue status.",
        inputSchema={
            "type": "object",
            "properties": {
                "check_nodes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific ComfyUI node class names to check (default: checks all known 3D nodes)",
                },
            },
            "required": [],
        },
    ),
    # AI Pipeline Tools
    Tool(
        name="blender_ai_pipeline_generate",
        description="Full AI pipeline: reference photo/prompt -> 3D model generation -> import to Blender -> mesh cleanup -> UV unwrap -> texture -> optional MSFS prep. Quality tiers: quick (SF3D, 15s blob), standard (TripoSG, good single-image), multiview_quality (Zero123Plus+InstantMesh, best structure), vehicle_components (multi-view + part separation). Returns pipeline status with results from each stage.",
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text description of the object to generate",
                },
                "image_path": {
                    "type": "string",
                    "description": "Path to reference photo (recommended for mechanical objects)",
                },
                "backend": {
                    "type": "string",
                    "enum": ["auto", "multiview", "triposg", "stable_fast_3d", "triposr", "rodin"],
                    "description": "3D generation backend. Preset sets default; override here. multiview=best quality, triposg=good single-image, stable_fast_3d=fast preview.",
                },
                "pipeline_preset": {
                    "type": "string",
                    "enum": ["quick", "standard", "multiview_quality", "vehicle_components", "msfs_vehicle", "msfs_building", "generic"],
                    "description": "Pipeline preset: quick (SF3D fast preview), standard (TripoSG), multiview_quality (best, Zero123+InstantMesh), vehicle_components (multi-view + part separation), msfs_vehicle/msfs_building (with LOD/collision), generic (auto backend).",
                },
                "target_polycount": {
                    "type": "number",
                    "description": "Target polygon count after decimation (default: 10000)",
                },
                "texture_prompt": {
                    "type": "string",
                    "description": "Override prompt for texture generation",
                },
                "texture_resolution": {
                    "type": "number",
                    "description": "Texture resolution: 512, 1024, or 2048 (default: 1024)",
                },
                "skip_stages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Stages to skip: generate, import, cleanup, component_separation, uv, texture, msfs_prep",
                },
                "existing_object": {
                    "type": "string",
                    "description": "Run pipeline on existing Blender object (skips generate+import)",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Export output directory",
                },
                "max_wait": {
                    "type": "number",
                    "description": "Maximum wait for generation in seconds (default: 600)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_ai_pipeline_status",
        description="Get status of a pipeline run or resume from last successful stage.",
        inputSchema={
            "type": "object",
            "properties": {
                "pipeline_id": {
                    "type": "string",
                    "description": "Pipeline run ID from blender_ai_pipeline_generate",
                },
                "resume": {
                    "type": "boolean",
                    "description": "Resume from last successful stage",
                },
            },
            "required": ["pipeline_id"],
        },
    ),
    # ==================== Selection & Query Tools ====================
    Tool(
        name="blender_mesh_select",
        description="Multi-criteria mesh selection engine. Select vertices, edges, or faces by index, position range, normal direction, material, edge angle, or face area. Supports grow/shrink and linked selection. Returns selected indices for piping to subsequent edit operations.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "mode": {
                    "type": "string",
                    "enum": ["VERT", "EDGE", "FACE"],
                    "default": "FACE",
                    "description": "Selection mode: VERT, EDGE, or FACE",
                },
                "action": {
                    "type": "string",
                    "enum": ["SET", "ADD", "SUBTRACT", "INVERT", "SELECT_ALL", "DESELECT_ALL"],
                    "default": "SET",
                    "description": "Selection action",
                },
                "indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Specific element indices to select",
                },
                "position_min": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Minimum position [x, y, z] — select elements above this",
                },
                "position_max": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Maximum position [x, y, z] — select elements below this",
                },
                "normal_direction": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Select faces whose normal aligns with this direction [x, y, z]",
                },
                "normal_threshold": {
                    "type": "number",
                    "default": 0.5,
                    "description": "Dot product threshold for normal direction (0-1, higher = stricter)",
                },
                "material_index": {
                    "type": "number",
                    "description": "Select faces with this material slot index",
                },
                "edge_angle_min": {
                    "type": "number",
                    "description": "Minimum edge angle in degrees (for EDGE mode)",
                },
                "edge_angle_max": {
                    "type": "number",
                    "description": "Maximum edge angle in degrees (for EDGE mode)",
                },
                "face_area_min": {
                    "type": "number",
                    "description": "Minimum face area (for FACE mode)",
                },
                "face_area_max": {
                    "type": "number",
                    "description": "Maximum face area (for FACE mode)",
                },
                "linked": {
                    "type": "boolean",
                    "default": False,
                    "description": "Extend selection to all linked/connected elements",
                },
                "grow": {
                    "type": "number",
                    "default": 0,
                    "description": "Number of grow iterations to expand selection",
                },
                "shrink": {
                    "type": "number",
                    "default": 0,
                    "description": "Number of shrink iterations to contract selection",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_mesh_select_trait",
        description="Select mesh elements by geometric trait: non-manifold edges, boundary edges, loose vertices, interior faces, faces by side count, ungrouped vertices, or non-planar faces. Essential for finding problem areas.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "trait": {
                    "type": "string",
                    "enum": ["NON_MANIFOLD", "BOUNDARY", "LOOSE", "INTERIOR_FACES", "FACE_SIDES", "UNGROUPED", "NON_PLANAR"],
                    "description": "Geometric trait to select by",
                },
                "extend": {
                    "type": "boolean",
                    "default": False,
                    "description": "Add to current selection instead of replacing",
                },
                "face_sides": {
                    "type": "number",
                    "description": "For FACE_SIDES trait: number of sides to match (3=tris, 4=quads, 5+=ngons)",
                },
                "non_planar_threshold": {
                    "type": "number",
                    "default": 0.01,
                    "description": "For NON_PLANAR trait: deviation threshold",
                },
            },
            "required": ["object_name", "trait"],
        },
    ),
    Tool(
        name="blender_mesh_select_linked_flat",
        description="Flood-select connected coplanar faces from a seed face. Selects entire flat panels by expanding to neighboring faces within an angle threshold. Ideal for selecting body panels.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "face_index": {
                    "type": "number",
                    "description": "Seed face index to start selection from",
                },
                "angle_threshold": {
                    "type": "number",
                    "default": 15.0,
                    "description": "Maximum angle in degrees between adjacent faces to include (default: 15)",
                },
            },
            "required": ["object_name", "face_index"],
        },
    ),
    Tool(
        name="blender_mesh_select_shortest_path",
        description="Select shortest path between two mesh elements. Useful for selecting edge loops or vertex paths along the mesh surface.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "mode": {
                    "type": "string",
                    "enum": ["VERT", "EDGE"],
                    "default": "EDGE",
                    "description": "Element type for path: VERT or EDGE",
                },
                "index_a": {
                    "type": "number",
                    "description": "Start element index",
                },
                "index_b": {
                    "type": "number",
                    "description": "End element index",
                },
            },
            "required": ["object_name", "index_a", "index_b"],
        },
    ),
    Tool(
        name="blender_mesh_get_selection",
        description="Query current mesh selection state without modifying it. Returns indices of selected vertices, edges, or faces.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "mode": {
                    "type": "string",
                    "enum": ["VERT", "EDGE", "FACE"],
                    "default": "FACE",
                    "description": "Which element type to query",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_mesh_select_edge_loops",
        description="Select complete edge loops or edge rings through a given edge. Fundamental for hard surface modeling — loops define the flow of geometry.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "edge_index": {
                    "type": "number",
                    "description": "Edge index to find the loop through",
                },
                "ring": {
                    "type": "boolean",
                    "default": False,
                    "description": "Select edge ring instead of edge loop",
                },
            },
            "required": ["object_name", "edge_index"],
        },
    ),
    # ==================== Shading & Normal Control ====================
    Tool(
        name="blender_shade_smooth",
        description="Set smooth, flat, or auto-smooth shading on an object. Auto-smooth applies smooth shading while keeping edges sharper than the angle threshold as flat — essential for mechanical surfaces.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "shade_type": {
                    "type": "string",
                    "enum": ["SMOOTH", "FLAT", "AUTO"],
                    "default": "AUTO",
                    "description": "Shading type: SMOOTH (all smooth), FLAT (all flat), AUTO (angle-based)",
                },
                "auto_smooth_angle": {
                    "type": "number",
                    "default": 30.0,
                    "description": "Angle threshold in degrees for auto-smooth (default: 30)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_mesh_crease",
        description="Set edge crease values for subdivision surface control. THE hard surface modeling tool — crease=1.0 keeps edges sharp through subdivision, crease=0.5 creates softer feature lines.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "edge_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Edge indices to set crease on (omit to use selected_only)",
                },
                "crease_value": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Crease value (0.0 = smooth, 1.0 = fully sharp)",
                },
                "selected_only": {
                    "type": "boolean",
                    "default": False,
                    "description": "Apply to currently selected edges (if edge_indices not provided)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_mesh_mark_sharp",
        description="Mark or clear sharp edges. Sharp edges override auto-smooth angle for precise normal control on specific edges.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "edge_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Edge indices to mark (omit to use selected_only)",
                },
                "clear": {
                    "type": "boolean",
                    "default": False,
                    "description": "Clear sharp marking instead of setting it",
                },
                "selected_only": {
                    "type": "boolean",
                    "default": False,
                    "description": "Apply to currently selected edges (if edge_indices not provided)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_mesh_mark_seam",
        description="Mark or clear UV seams on edges. UV seams define where the UV map is cut for unwrapping. Essential for texture mapping preparation.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "edge_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Edge indices to mark (omit to use selected_only)",
                },
                "clear": {
                    "type": "boolean",
                    "default": False,
                    "description": "Clear seam marking instead of setting it",
                },
                "selected_only": {
                    "type": "boolean",
                    "default": False,
                    "description": "Apply to currently selected edges (if edge_indices not provided)",
                },
            },
            "required": ["object_name"],
        },
    ),
    # ==================== Topology Editing Tools ====================
    Tool(
        name="blender_mesh_dissolve",
        description="Remove vertices, edges, or faces while preserving surrounding geometry. Unlike delete, dissolve merges the surrounding geometry to fill the gap.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "mode": {
                    "type": "string",
                    "enum": ["VERTS", "EDGES", "FACES"],
                    "description": "What to dissolve",
                },
                "indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Indices of elements to dissolve",
                },
                "use_face_split": {
                    "type": "boolean",
                    "default": False,
                    "description": "Split off face corners to maintain face integrity",
                },
            },
            "required": ["object_name", "mode", "indices"],
        },
    ),
    Tool(
        name="blender_mesh_merge",
        description="Merge vertices together — close gaps, join geometry, remove doubles. Supports merge to center, first, last, or by distance threshold.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "vertex_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Vertex indices to merge",
                },
                "merge_type": {
                    "type": "string",
                    "enum": ["CENTER", "FIRST", "LAST", "BY_DISTANCE"],
                    "default": "CENTER",
                    "description": "How to merge: CENTER (average position), FIRST, LAST, or BY_DISTANCE",
                },
                "distance": {
                    "type": "number",
                    "default": 0.0001,
                    "description": "Merge distance threshold (for BY_DISTANCE mode)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_mesh_bridge",
        description="Bridge two edge loops to create connecting faces — connect body panels, create tubes between openings, join separate mesh islands.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "loop1_edges": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Edge indices of first loop",
                },
                "loop2_edges": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Edge indices of second loop",
                },
                "segments": {
                    "type": "number",
                    "default": 1,
                    "description": "Number of intermediate segments",
                },
                "twist": {
                    "type": "number",
                    "default": 0,
                    "description": "Twist offset between loops",
                },
                "profile_factor": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Profile curvature (-1 to 1, 0=straight)",
                },
            },
            "required": ["object_name", "loop1_edges", "loop2_edges"],
        },
    ),
    Tool(
        name="blender_mesh_fill",
        description="Fill boundary edges with faces — cap holes, close open geometry. Supports n-gon fill, triangle fan, and grid fill.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "edge_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Edge indices forming the boundary to fill",
                },
                "fill_type": {
                    "type": "string",
                    "enum": ["NGON", "TRIANGLE_FAN", "GRID"],
                    "default": "NGON",
                    "description": "Fill method: NGON (single face), TRIANGLE_FAN, or GRID (requires even loop)",
                },
                "use_beauty": {
                    "type": "boolean",
                    "default": True,
                    "description": "Use beauty fill for better triangulation",
                },
            },
            "required": ["object_name", "edge_indices"],
        },
    ),
    Tool(
        name="blender_mesh_subdivide",
        description="Subdivide selected edges/faces to add resolution. Add geometry where needed without subdividing the entire mesh.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "edge_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Edge indices to subdivide (omit to subdivide all)",
                },
                "cuts": {
                    "type": "number",
                    "default": 1,
                    "description": "Number of cuts per edge",
                },
                "smoothness": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Smoothing factor (0=sharp, 1=smooth)",
                },
                "quad_corner_type": {
                    "type": "string",
                    "enum": ["STRAIGHT_CUT", "INNERVERT", "PATH", "FAN"],
                    "default": "STRAIGHT_CUT",
                    "description": "How to handle quad corners during subdivision",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_mesh_edge_slide",
        description="Slide edges along their connected faces to fine-tune edge loop position. Non-destructive repositioning of topology.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "edge_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Edge indices to slide",
                },
                "factor": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Slide factor (-1.0 to 1.0, 0=no change)",
                },
                "even": {
                    "type": "boolean",
                    "default": False,
                    "description": "Use even slide mode for uniform spacing",
                },
            },
            "required": ["object_name", "edge_indices"],
        },
    ),
    Tool(
        name="blender_mesh_tris_to_quads",
        description="Convert triangles to quads — clean up triangulated meshes to get cleaner quad topology. Pairs adjacent triangles based on angle and UV matching.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "face_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Face indices to process (omit for all triangles)",
                },
                "angle_limit": {
                    "type": "number",
                    "default": 40.0,
                    "description": "Maximum angle between triangle normals to join (degrees)",
                },
                "compare_uvs": {
                    "type": "boolean",
                    "default": False,
                    "description": "Only join triangles with matching UV edges",
                },
            },
            "required": ["object_name"],
        },
    ),
    # ==================== Cutting & Separation Tools ====================
    Tool(
        name="blender_mesh_knife_project",
        description="Project a curve or mesh outline onto a target surface to cut panel lines. The cutter object is projected along the view/normal onto the target.",
        inputSchema={
            "type": "object",
            "properties": {
                "target_object": {"type": "string", "description": "Name of the object to cut into"},
                "cutter_object": {"type": "string", "description": "Name of the curve/mesh to project as cutter"},
                "cut_through": {
                    "type": "boolean",
                    "default": False,
                    "description": "Cut through entire mesh (not just front faces)",
                },
            },
            "required": ["target_object", "cutter_object"],
        },
    ),
    Tool(
        name="blender_mesh_bisect",
        description="Cut mesh with an infinite plane defined by a point and normal. Can optionally clear geometry on either side and fill the cut. Perfect for splitting vehicles into sections.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "plane_point": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Point on the cutting plane [x, y, z]",
                },
                "plane_normal": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Normal direction of the cutting plane [x, y, z]",
                },
                "clear_inner": {
                    "type": "boolean",
                    "default": False,
                    "description": "Remove geometry on the negative side of the plane",
                },
                "clear_outer": {
                    "type": "boolean",
                    "default": False,
                    "description": "Remove geometry on the positive side of the plane",
                },
                "fill": {
                    "type": "boolean",
                    "default": False,
                    "description": "Fill the cut plane with a face",
                },
            },
            "required": ["object_name", "plane_point", "plane_normal"],
        },
    ),
    Tool(
        name="blender_mesh_separate_selected",
        description="Separate selected faces into a new object — extract body panels, components, or regions into independent objects.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "face_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Face indices to separate into a new object",
                },
                "new_name": {
                    "type": "string",
                    "description": "Name for the new separated object (optional)",
                },
            },
            "required": ["object_name", "face_indices"],
        },
    ),
    Tool(
        name="blender_mesh_split",
        description="Split edges or faces without separating into a new object — creates hard boundaries within the mesh by duplicating shared vertices.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "mode": {
                    "type": "string",
                    "enum": ["EDGES", "FACES"],
                    "default": "EDGES",
                    "description": "Split edges or faces",
                },
                "indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Indices of edges or faces to split",
                },
            },
            "required": ["object_name", "indices"],
        },
    ),
    # ==================== Reference & Measurement ====================
    Tool(
        name="blender_silhouette_compare",
        description="Render object silhouette and compare against a reference image. Returns a difference score and overlay image for proportion verification.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object to render"},
                "reference_image": {"type": "string", "description": "Path to reference silhouette/image"},
                "camera_angle": {
                    "type": "string",
                    "enum": ["FRONT", "RIGHT", "TOP", "PERSPECTIVE"],
                    "default": "FRONT",
                    "description": "Camera angle for rendering",
                },
                "resolution": {
                    "type": "number",
                    "default": 512,
                    "description": "Render resolution (square)",
                },
            },
            "required": ["object_name", "reference_image"],
        },
    ),
    Tool(
        name="blender_measure",
        description="Measure distances, bounding box dimensions, edge lengths, and vertex-to-vertex distances in world units.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "mode": {
                    "type": "string",
                    "enum": ["BBOX", "DISTANCE", "EDGE_LENGTH", "VERTEX_DISTANCE"],
                    "default": "BBOX",
                    "description": "Measurement mode",
                },
                "point_a": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "First point [x, y, z] for DISTANCE mode",
                },
                "point_b": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Second point [x, y, z] for DISTANCE mode",
                },
                "edge_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Edge indices for EDGE_LENGTH mode",
                },
                "vertex_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Two vertex indices for VERTEX_DISTANCE mode",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_reference_image_setup",
        description="Load a reference image as a background empty for modeling viewport overlay. Position it on a specific axis plane for tracing geometry.",
        inputSchema={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Path to the reference image file"},
                "axis": {
                    "type": "string",
                    "enum": ["FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"],
                    "default": "FRONT",
                    "description": "Axis plane to position the image on",
                },
                "offset": {
                    "type": "number",
                    "default": -5.0,
                    "description": "Distance offset along the axis normal",
                },
                "opacity": {
                    "type": "number",
                    "default": 0.5,
                    "description": "Image opacity (0-1)",
                },
                "size": {
                    "type": "number",
                    "default": 5.0,
                    "description": "Display size of the reference image",
                },
            },
            "required": ["image_path"],
        },
    ),
    # ==================== Detail Placement & Instancing ====================
    Tool(
        name="blender_array_along_curve",
        description="Instance objects along a curve path — rivet lines, bolt patterns, cable runs. Uses Array + Curve modifiers for parametric control.",
        inputSchema={
            "type": "object",
            "properties": {
                "source_object": {"type": "string", "description": "Name of the object to array"},
                "curve_name": {"type": "string", "description": "Name of the curve to follow"},
                "count": {
                    "type": "number",
                    "default": 10,
                    "description": "Number of instances along the curve",
                },
                "fit_type": {
                    "type": "string",
                    "enum": ["FIXED_COUNT", "FIT_LENGTH", "FIT_CURVE"],
                    "default": "FIT_CURVE",
                    "description": "How to distribute instances: FIXED_COUNT, FIT_LENGTH, or FIT_CURVE",
                },
                "apply": {
                    "type": "boolean",
                    "default": False,
                    "description": "Apply modifiers immediately (makes instances real geometry)",
                },
            },
            "required": ["source_object", "curve_name"],
        },
    ),
    Tool(
        name="blender_scatter_on_surface",
        description="Scatter objects on a mesh surface using a particle system — bolts, rivets, damage marks, vegetation. Control count, randomization, and area restriction.",
        inputSchema={
            "type": "object",
            "properties": {
                "target_object": {"type": "string", "description": "Name of the surface object to scatter on"},
                "source_object": {"type": "string", "description": "Name of the object to scatter"},
                "count": {
                    "type": "number",
                    "default": 100,
                    "description": "Number of scattered instances",
                },
                "seed": {
                    "type": "number",
                    "default": 0,
                    "description": "Random seed for reproducible scattering",
                },
                "scale_min": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Minimum random scale factor",
                },
                "scale_max": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Maximum random scale factor",
                },
                "rotation_random": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Random rotation factor (0-1)",
                },
                "vertex_group": {
                    "type": "string",
                    "description": "Vertex group to restrict scattering area (optional)",
                },
            },
            "required": ["target_object", "source_object"],
        },
    ),
    Tool(
        name="blender_collection_instance",
        description="Place collection instances at specific locations — efficient placement of repeated complex objects like wheel assemblies, control panels, or structural details.",
        inputSchema={
            "type": "object",
            "properties": {
                "collection_name": {"type": "string", "description": "Name of the collection to instance"},
                "locations": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Array of [x, y, z] positions for instances",
                },
                "rotations": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Optional array of [x, y, z] rotations in degrees per instance",
                },
                "scales": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Optional array of [x, y, z] scales per instance",
                },
            },
            "required": ["collection_name", "locations"],
        },
    ),
    # ==================== Transform & Deform ====================
    Tool(
        name="blender_mesh_proportional_transform",
        description="Move, rotate, or scale vertices with proportional falloff affecting neighbors — organic shape refinement, smooth deformations, sculpt-like adjustments via MCP.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "vertex_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Center vertex indices for the transform",
                },
                "transform_type": {
                    "type": "string",
                    "enum": ["TRANSLATE", "ROTATE", "SCALE"],
                    "default": "TRANSLATE",
                    "description": "Transform type",
                },
                "value": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Transform value: [x,y,z] for translate/scale, [angle_degrees, axis_x, axis_y, axis_z] for rotate",
                },
                "falloff": {
                    "type": "string",
                    "enum": ["SMOOTH", "SPHERE", "ROOT", "LINEAR", "SHARP", "CONSTANT"],
                    "default": "SMOOTH",
                    "description": "Falloff curve type",
                },
                "radius": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Proportional influence radius",
                },
            },
            "required": ["object_name", "vertex_indices", "value"],
        },
    ),
    Tool(
        name="blender_mesh_shrinkwrap",
        description="Snap vertices to another object's surface — conform details to body panels, project geometry onto curved surfaces.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the object whose vertices to snap"},
                "target_object": {"type": "string", "description": "Name of the target surface object"},
                "vertex_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Specific vertex indices to snap (omit for all)",
                },
                "mode": {
                    "type": "string",
                    "enum": ["NEAREST_SURFACE", "PROJECT", "NEAREST_VERTEX"],
                    "default": "NEAREST_SURFACE",
                    "description": "Shrinkwrap projection mode",
                },
                "offset": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Offset from target surface",
                },
            },
            "required": ["object_name", "target_object"],
        },
    ),
    Tool(
        name="blender_mesh_flatten",
        description="Flatten selected vertices to a plane — clean up bumpy surfaces, create perfectly flat areas on body panels.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the mesh object"},
                "vertex_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Vertex indices to flatten",
                },
                "plane": {
                    "type": "string",
                    "enum": ["XY", "XZ", "YZ", "NORMAL", "BEST_FIT"],
                    "default": "BEST_FIT",
                    "description": "Plane to flatten to: axis plane or BEST_FIT (PCA-derived)",
                },
            },
            "required": ["object_name", "vertex_indices"],
        },
    ),
    # ========== Sculpting Tools ==========
    Tool(
        name="blender_sculpt_setup",
        description=(
            "Enter sculpt mode with configuration. Supports MULTIRES (subdivision levels), "
            "DYNTOPO (dynamic topology for adaptive detail), and SIMPLE mode. "
            "Can configure symmetry axes for mirrored sculpting."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to sculpt",
                },
                "mode": {
                    "type": "string",
                    "enum": ["MULTIRES", "DYNTOPO", "SIMPLE"],
                    "description": "Sculpting mode: MULTIRES adds subdivision levels, DYNTOPO enables dynamic topology, SIMPLE enters sculpt mode as-is",
                },
                "multires_levels": {
                    "type": "number",
                    "description": "Number of multires subdivision levels to add (default: 3, only used with MULTIRES mode)",
                },
                "dyntopo_detail": {
                    "type": "number",
                    "description": "Dynamic topology detail size (default: 12.0, only used with DYNTOPO mode)",
                },
                "dyntopo_method": {
                    "type": "string",
                    "enum": ["RELATIVE", "CONSTANT", "BRUSH", "MANUAL"],
                    "description": "Dynamic topology detail method (default: RELATIVE)",
                },
                "symmetry_axes": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["X", "Y", "Z"],
                    },
                    "description": "Axes to enable sculpt symmetry on, e.g. ['X'] for bilateral symmetry",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_sculpt_mesh_filter",
        description=(
            "Apply global mesh filters to a sculpt-mode object. Unlike brush strokes, "
            "mesh filters affect the entire mesh uniformly and work reliably over MCP. "
            "Useful for smoothing, sharpening detail, adding surface noise, inflating, "
            "or relaxing topology."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object (must be in sculpt mode or will be switched)",
                },
                "filter_type": {
                    "type": "string",
                    "enum": [
                        "SMOOTH",
                        "SHARPEN",
                        "ENHANCE_DETAIL",
                        "SURFACE_NOISE",
                        "INFLATE",
                        "SPHERE",
                        "RELAX",
                        "RELAX_FACE_SETS",
                        "ERASE_DISPLACEMENT",
                    ],
                    "description": "Type of mesh filter to apply",
                },
                "strength": {
                    "type": "number",
                    "description": "Filter strength (default: 1.0)",
                },
                "iterations": {
                    "type": "number",
                    "description": "Number of times to apply the filter (default: 1)",
                },
            },
            "required": ["object_name", "filter_type"],
        },
    ),
    Tool(
        name="blender_sculpt_mask_by_topology",
        description=(
            "Create sculpt masks based on topology features. Masks control which "
            "parts of the mesh are affected by sculpting operations. CAVITY masks "
            "concave areas, ALL fills the entire mask, NONE clears it, RANDOM creates "
            "a random mask pattern. Optional blur smooths mask edges."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object",
                },
                "mask_type": {
                    "type": "string",
                    "enum": ["CAVITY", "ALL", "NONE", "RANDOM"],
                    "description": "Type of mask to create",
                },
                "invert": {
                    "type": "boolean",
                    "description": "Invert the mask after creation (default: false)",
                },
                "blur_iterations": {
                    "type": "number",
                    "description": "Number of blur/smooth passes on the mask (default: 0)",
                },
            },
            "required": ["object_name", "mask_type"],
        },
    ),
    Tool(
        name="blender_sculpt_face_set_create",
        description=(
            "Create face sets by grouping faces based on criteria. Face sets partition "
            "the mesh into regions for isolated sculpting. LINKED groups connected geometry, "
            "MATERIAL groups by material assignment, NORMAL groups by face orientation, "
            "SHARP_EDGES splits at sharp edges, UV_ISLAND groups by UV islands."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object",
                },
                "criteria": {
                    "type": "string",
                    "enum": ["LINKED", "MATERIAL", "NORMAL", "SHARP_EDGES", "UV_ISLAND"],
                    "description": "Criteria for creating face sets",
                },
            },
            "required": ["object_name", "criteria"],
        },
    ),
    Tool(
        name="blender_sculpt_multires_reshape",
        description=(
            "Manage multiresolution modifier levels for sculpting. SUBDIVIDE adds a level, "
            "UNSUBDIVIDE removes the highest level, REBUILD reconstructs subdivisions, "
            "APPLY_BASE applies sculpted changes to the base mesh, DELETE_HIGHER removes "
            "levels above current, DELETE_LOWER removes levels below current."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object with a Multires modifier",
                },
                "action": {
                    "type": "string",
                    "enum": [
                        "SUBDIVIDE",
                        "UNSUBDIVIDE",
                        "REBUILD",
                        "APPLY_BASE",
                        "DELETE_HIGHER",
                        "DELETE_LOWER",
                    ],
                    "description": "Action to perform on the multires modifier",
                },
            },
            "required": ["object_name", "action"],
        },
    ),
    Tool(
        name="blender_sculpt_to_retopo",
        description=(
            "Pipeline tool: convert a high-poly sculpt to a retopologized low-poly mesh "
            "with optional displacement map baking. Creates a duplicate, applies remesh "
            "(voxel or quadriflow), auto-UV unwraps, and optionally bakes displacement "
            "from the original. Essential for game-ready asset production."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the high-poly sculpted mesh object",
                },
                "method": {
                    "type": "string",
                    "enum": ["VOXEL_REMESH", "QUADRIFLOW"],
                    "description": "Retopology method (default: VOXEL_REMESH)",
                },
                "target_polycount": {
                    "type": "number",
                    "description": "Target polygon count for the retopo mesh (default: 5000)",
                },
                "bake_displacement": {
                    "type": "boolean",
                    "description": "Bake displacement map from original to retopo mesh (default: true)",
                },
                "displacement_resolution": {
                    "type": "number",
                    "description": "Resolution of the displacement map in pixels (default: 2048)",
                },
                "output_displacement_path": {
                    "type": "string",
                    "description": "File path to save the baked displacement map (optional, defaults to temp file)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_sculpt_extract_mask",
        description=(
            "Extract the masked region of a sculpt as a separate mesh object. "
            "Creates a new mesh from faces above the mask threshold, optionally adding "
            "thickness via solidify. Useful for creating armor plates, panel lines, "
            "or detail pieces from sculpted forms."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object with an active sculpt mask",
                },
                "thickness": {
                    "type": "number",
                    "description": "Thickness of the extracted shell (default: 0.05)",
                },
                "smooth_iterations": {
                    "type": "number",
                    "description": "Number of smooth iterations on the extracted boundary (default: 2)",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_sculpt_remesh_voxel",
        description=(
            "Apply voxel remesh to create a uniform topology. Converts the mesh to a "
            "voxel representation and back, producing evenly-spaced quads. Useful for "
            "cleaning up boolean results, imported meshes, or preparing for sculpting. "
            "Smaller voxel_size = higher detail but more polygons."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to remesh",
                },
                "voxel_size": {
                    "type": "number",
                    "description": "Size of voxels in world units - smaller = more detail (default: 0.05)",
                },
                "smooth": {
                    "type": "boolean",
                    "description": "Apply smoothing after remesh (default: false)",
                },
                "fix_poles": {
                    "type": "boolean",
                    "description": "Attempt to fix topology poles after remesh (default: false)",
                },
            },
            "required": ["object_name"],
        },
    ),
    # ========== Rigging & Armature Tools ==========
    Tool(
        name="blender_armature_create",
        description=(
            "Create an armature from a list of bone definitions. Each bone specifies "
            "head/tail positions, optional parent, connection state, and roll angle. "
            "Use this for precise skeleton construction from known bone positions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the armature object (default: 'Armature')",
                },
                "bones": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Bone name",
                            },
                            "head": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "Head position [x, y, z]",
                            },
                            "tail": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "Tail position [x, y, z]",
                            },
                            "parent": {
                                "type": "string",
                                "description": "Name of parent bone (optional)",
                            },
                            "connected": {
                                "type": "boolean",
                                "description": "Whether bone is connected to parent (head snaps to parent tail)",
                            },
                            "roll": {
                                "type": "number",
                                "description": "Bone roll angle in degrees (default: 0)",
                            },
                        },
                        "required": ["name", "head", "tail"],
                    },
                    "description": "Array of bone definitions",
                },
                "display_type": {
                    "type": "string",
                    "enum": ["OCTAHEDRAL", "STICK", "BBONE", "WIRE", "ENVELOPE"],
                    "description": "Armature display style (default: OCTAHEDRAL)",
                },
            },
            "required": ["bones"],
        },
    ),
    Tool(
        name="blender_autorig_preset",
        description=(
            "One-call auto-rig generator. Creates a complete bone hierarchy for common "
            "use cases: BIPED (humanoid), QUADRUPED (four-legged), VEHICLE (wheels + steering), "
            "MECHANICAL_ARM (IK chain), TURRET (rotate + elevate), WHEEL_ASSEMBLY (axle + spin), "
            "DOOR_HINGE (limited rotation), PISTON (stretch-to pair), LANDING_GEAR (retract chain). "
            "Optionally auto-weights the mesh and configures for MSFS export."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to rig (required for auto-weighting)",
                },
                "preset": {
                    "type": "string",
                    "enum": [
                        "BIPED",
                        "QUADRUPED",
                        "VEHICLE",
                        "MECHANICAL_ARM",
                        "TURRET",
                        "WHEEL_ASSEMBLY",
                        "DOOR_HINGE",
                        "PISTON",
                        "LANDING_GEAR",
                    ],
                    "description": "Preset rig type to generate",
                },
                "auto_weight": {
                    "type": "boolean",
                    "description": "Automatically parent mesh with armature deform + automatic weights (default: true)",
                },
                "msfs_compatible": {
                    "type": "boolean",
                    "description": "Use MSFS-compatible bone naming conventions (default: false)",
                },
            },
            "required": ["object_name", "preset"],
        },
    ),
    Tool(
        name="blender_constraint_add",
        description=(
            "Add a constraint to a bone or object. Supports IK, copy transforms, "
            "tracking, stretch-to, limits, floor, and child-of constraints. "
            "Specify either bone_name (for pose bone constraint) or object_name "
            "(for object constraint), plus target and type-specific settings."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "armature_name": {
                    "type": "string",
                    "description": "Name of the armature object (required for bone constraints)",
                },
                "bone_name": {
                    "type": "string",
                    "description": "Name of the bone to add constraint to (for bone constraints)",
                },
                "object_name": {
                    "type": "string",
                    "description": "Name of the object to add constraint to (for object constraints)",
                },
                "constraint_type": {
                    "type": "string",
                    "enum": [
                        "IK",
                        "COPY_ROTATION",
                        "COPY_LOCATION",
                        "COPY_SCALE",
                        "TRACK_TO",
                        "DAMPED_TRACK",
                        "STRETCH_TO",
                        "LIMIT_ROTATION",
                        "LIMIT_LOCATION",
                        "FLOOR",
                        "CHILD_OF",
                    ],
                    "description": "Type of constraint to add",
                },
                "target_object": {
                    "type": "string",
                    "description": "Name of the target object for the constraint",
                },
                "target_bone": {
                    "type": "string",
                    "description": "Name of the target bone (if target is an armature)",
                },
                "influence": {
                    "type": "number",
                    "description": "Constraint influence 0-1 (default: 1.0)",
                },
                "settings": {
                    "type": "object",
                    "description": "Constraint-specific settings as key-value pairs (e.g. chain_count for IK, axis for track_to)",
                },
            },
            "required": ["constraint_type"],
        },
    ),
    Tool(
        name="blender_constraint_preset",
        description=(
            "Apply preset constraint setups that require multiple coordinated constraints. "
            "IK_ARM: IK chain with pole target. IK_LEG: IK with foot roll. "
            "PISTON_PAIR: two bones with mutual stretch-to. WHEEL_SPIN: rotation driver. "
            "DOOR_SWING: limit rotation constraint. TURRET_TRACK: two-axis tracking."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "armature_name": {
                    "type": "string",
                    "description": "Name of the armature object",
                },
                "preset": {
                    "type": "string",
                    "enum": [
                        "IK_ARM",
                        "IK_LEG",
                        "PISTON_PAIR",
                        "WHEEL_SPIN",
                        "DOOR_SWING",
                        "TURRET_TRACK",
                    ],
                    "description": "Constraint preset to apply",
                },
                "bones": {
                    "type": "object",
                    "description": (
                        "Bone name mapping for the preset. Keys depend on preset type:\n"
                        "IK_ARM: {ik_bone, pole_target, chain_count}\n"
                        "IK_LEG: {ik_bone, pole_target, foot_bone, chain_count}\n"
                        "PISTON_PAIR: {bone_a, bone_b}\n"
                        "WHEEL_SPIN: {wheel_bone, axis}\n"
                        "DOOR_SWING: {hinge_bone, min_angle, max_angle, axis}\n"
                        "TURRET_TRACK: {base_bone, elevation_bone, target_bone}"
                    ),
                },
            },
            "required": ["armature_name", "preset", "bones"],
        },
    ),
    Tool(
        name="blender_bone_shape_assign",
        description=(
            "Assign a custom wireframe control shape to a bone for rig visualization. "
            "Creates (or reuses) a wire mesh shape and assigns it as the bone's custom_shape. "
            "Shapes: CIRCLE, SQUARE, CUBE, SPHERE, ARROW, DIAMOND, CROSS."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "armature_name": {
                    "type": "string",
                    "description": "Name of the armature object",
                },
                "bone_name": {
                    "type": "string",
                    "description": "Name of the bone to assign the shape to",
                },
                "shape": {
                    "type": "string",
                    "enum": ["CIRCLE", "SQUARE", "CUBE", "SPHERE", "ARROW", "DIAMOND", "CROSS"],
                    "description": "Shape type for the bone control widget",
                },
                "scale": {
                    "type": "number",
                    "description": "Scale factor for the shape (default: 1.0)",
                },
            },
            "required": ["armature_name", "bone_name", "shape"],
        },
    ),
    Tool(
        name="blender_pose_library_save",
        description=(
            "Save the current pose of an armature as a named pose. Stores bone transforms "
            "(location, rotation, scale) as custom properties on the armature. "
            "Optionally filter to save only specific bones."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "armature_name": {
                    "type": "string",
                    "description": "Name of the armature object",
                },
                "pose_name": {
                    "type": "string",
                    "description": "Name to save the pose under",
                },
                "bone_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of bone names to include (all bones if omitted)",
                },
            },
            "required": ["armature_name", "pose_name"],
        },
    ),
    Tool(
        name="blender_pose_library_apply",
        description=(
            "Apply a previously saved pose to an armature. Supports blending with the "
            "current pose via blend_factor (0=keep current, 1=full saved pose). "
            "Useful for creating animation keyframes from preset poses."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "armature_name": {
                    "type": "string",
                    "description": "Name of the armature object",
                },
                "pose_name": {
                    "type": "string",
                    "description": "Name of the saved pose to apply",
                },
                "blend_factor": {
                    "type": "number",
                    "description": "Blend factor between current pose (0) and saved pose (1). Default: 1.0",
                },
            },
            "required": ["armature_name", "pose_name"],
        },
    ),
    Tool(
        name="blender_rig_validate",
        description=(
            "Validate an armature rig for export compatibility. Checks bone naming conventions, "
            "hierarchy structure, constraint setup, deform bone flags, and scale/orientation. "
            "Returns a list of issues and a compatibility score for the target format."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "armature_name": {
                    "type": "string",
                    "description": "Name of the armature object to validate",
                },
                "target_format": {
                    "type": "string",
                    "enum": ["MIXAMO", "UE5", "MSFS", "GENERIC"],
                    "description": "Target export format to validate against (default: GENERIC)",
                },
            },
            "required": ["armature_name"],
        },
    ),
    # ========== Physics Simulation Tools ==========
    Tool(
        name="blender_physics_rigid_body_add",
        description="Add a rigid body physics simulation to an object. Makes it participate in physics as either an active (affected by forces) or passive (static collider) body.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the object to add rigid body to",
                },
                "body_type": {
                    "type": "string",
                    "enum": ["ACTIVE", "PASSIVE"],
                    "description": "Type of rigid body: ACTIVE (dynamic, affected by forces) or PASSIVE (static collider). Default: ACTIVE",
                },
                "mass": {
                    "type": "number",
                    "description": "Mass of the object in kilograms. Default: 1.0",
                },
                "friction": {
                    "type": "number",
                    "description": "Surface friction coefficient (0=frictionless, 1=maximum). Default: 0.5",
                },
                "bounciness": {
                    "type": "number",
                    "description": "Restitution/bounciness (0=no bounce, 1=fully elastic). Default: 0.0",
                },
                "collision_shape": {
                    "type": "string",
                    "enum": [
                        "BOX",
                        "SPHERE",
                        "CAPSULE",
                        "CYLINDER",
                        "CONE",
                        "CONVEX_HULL",
                        "MESH",
                    ],
                    "description": "Collision shape type. CONVEX_HULL is a good default for most objects. MESH is most accurate but slowest. Default: CONVEX_HULL",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_physics_rigid_body_batch",
        description="Add rigid body physics to multiple objects at once. Optionally designate a ground/floor object as a PASSIVE collider.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of object names to add rigid bodies to",
                },
                "body_type": {
                    "type": "string",
                    "enum": ["ACTIVE", "PASSIVE"],
                    "description": "Type of rigid body for all listed objects. Default: ACTIVE",
                },
                "mass": {
                    "type": "number",
                    "description": "Mass for all objects in kilograms. Default: 1.0",
                },
                "ground_object": {
                    "type": "string",
                    "description": "Optional name of an object to set as PASSIVE (ground/floor collider). This object does not need to be in object_names.",
                },
            },
            "required": ["object_names"],
        },
    ),
    Tool(
        name="blender_physics_simulate",
        description="Run the physics simulation for a frame range. Optionally apply results to make the final positions permanent (freezes simulation).",
        inputSchema={
            "type": "object",
            "properties": {
                "frame_start": {
                    "type": "number",
                    "description": "First frame of simulation. Default: 1",
                },
                "frame_end": {
                    "type": "number",
                    "description": "Last frame of simulation. Default: 250",
                },
                "apply_results": {
                    "type": "boolean",
                    "description": "If true, apply the visual transform at frame_end and remove rigid bodies, making positions permanent. Default: false",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_physics_cloth_add",
        description="Add cloth simulation to a mesh object. Supports material presets (silk, cotton, denim, etc.), vertex group pinning, collision objects, and wind.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to add cloth simulation to",
                },
                "preset": {
                    "type": "string",
                    "enum": [
                        "SILK",
                        "COTTON",
                        "DENIM",
                        "LEATHER",
                        "RUBBER",
                        "CANVAS",
                        "TARP",
                    ],
                    "description": "Material preset controlling stiffness, mass, and damping. Default: COTTON",
                },
                "pin_vertex_group": {
                    "type": "string",
                    "description": "Name of a vertex group to pin (vertices in this group stay fixed in place)",
                },
                "collision_objects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of objects that the cloth should collide with",
                },
                "wind_strength": {
                    "type": "number",
                    "description": "Strength of wind force. 0 = no wind. Default: 0.0",
                },
                "wind_direction": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Wind direction as [x, y, z] vector. Default: [1, 0, 0]",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_physics_soft_body_add",
        description="Add soft body simulation to a mesh object. Soft bodies deform under forces while trying to maintain their shape.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to add soft body to",
                },
                "goal_strength": {
                    "type": "number",
                    "description": "How strongly the object tries to return to its original shape (0=fully soft, 1=rigid). Default: 0.7",
                },
                "mass": {
                    "type": "number",
                    "description": "Mass of the soft body in kilograms. Default: 1.0",
                },
                "friction": {
                    "type": "number",
                    "description": "Friction coefficient for the soft body surface. Default: 0.5",
                },
            },
            "required": ["object_name"],
        },
    ),
    Tool(
        name="blender_physics_fluid_quick",
        description="Quick fluid simulation setup with a domain and flow object. Creates a Mantaflow-based liquid or gas simulation.",
        inputSchema={
            "type": "object",
            "properties": {
                "domain_object": {
                    "type": "string",
                    "description": "Name of the object to use as the fluid domain (bounding box for the simulation)",
                },
                "flow_object": {
                    "type": "string",
                    "description": "Name of the object to use as the fluid inflow source",
                },
                "fluid_type": {
                    "type": "string",
                    "enum": ["LIQUID", "GAS"],
                    "description": "Type of fluid simulation. Default: LIQUID",
                },
                "resolution": {
                    "type": "number",
                    "description": "Simulation grid resolution (higher = more detailed but slower). Default: 64",
                },
                "viscosity": {
                    "type": "number",
                    "description": "Fluid viscosity (0=water-like, higher=thicker). Default: 0.0",
                },
            },
            "required": ["domain_object", "flow_object"],
        },
    ),
    # ========== Annotation & Grease Pencil Tools ==========
    Tool(
        name="blender_annotation_add",
        description="Add 3D annotation strokes to the scene as a grease pencil annotation layer. Useful for marking up geometry, drawing guides, or highlighting areas of interest.",
        inputSchema={
            "type": "object",
            "properties": {
                "points": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                    },
                    "description": "Array of [x, y, z] points defining the stroke path",
                },
                "color": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Stroke color as [R, G, B, A] with values 0-1. Default: [1, 0, 0, 1] (red)",
                },
                "thickness": {
                    "type": "number",
                    "description": "Stroke thickness in pixels. Default: 3",
                },
                "layer_name": {
                    "type": "string",
                    "description": "Name of the annotation layer to add strokes to. Created if it doesn't exist. Default: 'Annotations'",
                },
            },
            "required": ["points"],
        },
    ),
    Tool(
        name="blender_annotation_text",
        description="Add a 3D text annotation at a specific location. Creates a font/text object that can be used as a label or callout.",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text content to display",
                },
                "location": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Position as [x, y, z] where the text should be placed",
                },
                "size": {
                    "type": "number",
                    "description": "Text size. Default: 1.0",
                },
                "color": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Text color as [R, G, B, A] with values 0-1. Default: [1, 1, 1, 1] (white)",
                },
            },
            "required": ["text", "location"],
        },
    ),
    Tool(
        name="blender_annotation_dimension",
        description="Add a dimension line between two 3D points showing the distance measurement. Creates endpoint markers, a connecting line, and a text label with the calculated distance.",
        inputSchema={
            "type": "object",
            "properties": {
                "point_a": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "First point as [x, y, z]",
                },
                "point_b": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Second point as [x, y, z]",
                },
                "offset": {
                    "type": "number",
                    "description": "Perpendicular offset distance for the dimension line from the measured points. Default: 0.5",
                },
                "units": {
                    "type": "string",
                    "enum": ["METERS", "CM", "MM", "INCHES", "FEET"],
                    "description": "Display units for the measurement. Default: METERS",
                },
                "label": {
                    "type": "string",
                    "description": "Override label text. If omitted, the calculated distance with units is used.",
                },
            },
            "required": ["point_a", "point_b"],
        },
    ),
    Tool(
        name="blender_annotation_clear",
        description="Clear annotation layers. Can clear a specific layer by name or all annotation layers at once.",
        inputSchema={
            "type": "object",
            "properties": {
                "layer_name": {
                    "type": "string",
                    "description": "Name of the annotation layer to clear. If omitted, clears ALL annotation layers.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_grease_pencil_create",
        description="Create a grease pencil object with one or more strokes. Grease pencil objects are persistent 2D/3D drawing objects in the scene.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the grease pencil object. Default: 'GPencil'",
                },
                "strokes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "points": {
                                "type": "array",
                                "items": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                },
                                "description": "Array of [x, y, z] points for this stroke",
                            },
                            "thickness": {
                                "type": "number",
                                "description": "Line thickness for this stroke. Default: 10",
                            },
                        },
                        "required": ["points"],
                    },
                    "description": "Array of stroke definitions, each with points and optional thickness",
                },
                "color": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Stroke color as [R, G, B, A] with values 0-1. Default: [0, 0, 0, 1] (black)",
                },
            },
            "required": ["strokes"],
        },
    ),
    Tool(
        name="blender_grease_pencil_markup",
        description="Overlay markup annotations (arrows, circles, rectangles, text) on a rendered image. Uses Pillow if available, otherwise falls back to Blender compositor.",
        inputSchema={
            "type": "object",
            "properties": {
                "render_path": {
                    "type": "string",
                    "description": "Path to the input rendered image file (PNG, JPG, etc.)",
                },
                "annotations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["arrow", "circle", "rectangle", "text"],
                                "description": "Type of annotation to draw",
                            },
                            "start": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "Start point [x, y] in pixel coordinates. Used by arrow and rectangle.",
                            },
                            "end": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "End point [x, y] in pixel coordinates. Used by arrow and rectangle.",
                            },
                            "center": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "Center point [x, y] in pixel coordinates. Used by circle.",
                            },
                            "radius": {
                                "type": "number",
                                "description": "Radius in pixels. Used by circle.",
                            },
                            "position": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "Position [x, y] in pixel coordinates. Used by text.",
                            },
                            "text": {
                                "type": "string",
                                "description": "Text content. Used by text annotation type.",
                            },
                            "color": {
                                "type": "string",
                                "description": "Color as a CSS-style string (e.g., 'red', '#FF0000'). Default: 'red'",
                            },
                            "thickness": {
                                "type": "number",
                                "description": "Line thickness in pixels. Default: 3",
                            },
                            "font_size": {
                                "type": "number",
                                "description": "Font size for text annotations. Default: 24",
                            },
                        },
                        "required": ["type"],
                    },
                    "description": "Array of annotation objects to draw on the image",
                },
                "output_path": {
                    "type": "string",
                    "description": "Path to save the annotated output image",
                },
            },
            "required": ["render_path", "annotations", "output_path"],
        },
    ),


    # ── Material Inspection & Manipulation (7 tools) ──

    # ── Material Inspection & Manipulation ──
    Tool(
        name="blender_material_inspect_graph",
        description=(
            "Return the full shader node graph of a material as structured JSON. "
            "Lists every node (name, type, location, input values/connections, output connections) "
            "and every link (from_node, from_output, to_node, to_input)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "material_name": {
                    "type": "string",
                    "description": "Name of the material to inspect",
                },
            },
            "required": ["material_name"],
        },
    ),
    Tool(
        name="blender_material_node_add",
        description=(
            "Add a shader node to a material's node tree. "
            "Supports any Blender node type (e.g. ShaderNodeTexNoise, ShaderNodeMixRGB, "
            "ShaderNodeBump, ShaderNodeMapping, ShaderNodeNormalMap, ShaderNodeValToRGB, etc.). "
            "Optionally set location and input default values."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "material_name": {
                    "type": "string",
                    "description": "Name of the material",
                },
                "node_type": {
                    "type": "string",
                    "description": "Blender node type identifier (e.g. 'ShaderNodeTexNoise', 'ShaderNodeBump')",
                },
                "name": {
                    "type": "string",
                    "description": "Optional display name for the node",
                },
                "location": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Node location [x, y] in the node editor",
                },
                "inputs": {
                    "type": "object",
                    "description": (
                        "Object mapping input socket names to default values. "
                        "Scalar inputs use a number, vector/color inputs use an array."
                    ),
                },
            },
            "required": ["material_name", "node_type"],
        },
    ),
    Tool(
        name="blender_material_node_connect",
        description=(
            "Connect two nodes in a material's shader graph via their socket names. "
            "Creates a link from an output socket on one node to an input socket on another."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "material_name": {
                    "type": "string",
                    "description": "Name of the material",
                },
                "from_node": {
                    "type": "string",
                    "description": "Name of the source node",
                },
                "from_output": {
                    "type": "string",
                    "description": "Name of the output socket on the source node",
                },
                "to_node": {
                    "type": "string",
                    "description": "Name of the destination node",
                },
                "to_input": {
                    "type": "string",
                    "description": "Name of the input socket on the destination node",
                },
            },
            "required": ["material_name", "from_node", "from_output", "to_node", "to_input"],
        },
    ),
    Tool(
        name="blender_material_node_group_create",
        description=(
            "Create a reusable shader node group with defined inputs and outputs. "
            "The group can later be instanced inside any material via a ShaderNodeGroup node."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the node group",
                },
                "inputs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Input socket name"},
                            "type": {
                                "type": "string",
                                "enum": ["FLOAT", "RGBA", "VECTOR", "VALUE", "SHADER"],
                                "description": "Socket type",
                            },
                            "default": {
                                "description": "Default value (number for FLOAT/VALUE, [r,g,b,a] for RGBA, [x,y,z] for VECTOR)",
                            },
                        },
                        "required": ["name", "type"],
                    },
                    "description": "Input socket definitions",
                },
                "outputs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Output socket name"},
                            "type": {
                                "type": "string",
                                "enum": ["FLOAT", "RGBA", "VECTOR", "VALUE", "SHADER"],
                                "description": "Socket type",
                            },
                        },
                        "required": ["name", "type"],
                    },
                    "description": "Output socket definitions",
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="blender_material_procedural_preset",
        description=(
            "Create a complex procedural material from a named preset with one call. "
            "Builds a full shader node tree. Presets: VEHICLE_PAINT, BRUSHED_METAL, CHROME, "
            "RUBBER, CARBON_FIBER, ASPHALT, TARMAC, WORN_METAL, GLASS, PLASTIC_GLOSSY, "
            "PLASTIC_MATTE, CONCRETE, FABRIC, REFLECTIVE_TAPE, LED_DISPLAY, RUST, GOLD, "
            "COPPER, SCRATCHED_PAINT, SNOW, WATER, WOOD, BRICK."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the new material",
                },
                "preset": {
                    "type": "string",
                    "enum": [
                        "VEHICLE_PAINT", "BRUSHED_METAL", "CHROME", "RUBBER",
                        "CARBON_FIBER", "ASPHALT", "TARMAC", "WORN_METAL",
                        "GLASS", "PLASTIC_GLOSSY", "PLASTIC_MATTE", "CONCRETE",
                        "FABRIC", "REFLECTIVE_TAPE", "LED_DISPLAY", "RUST",
                        "GOLD", "COPPER", "SCRATCHED_PAINT", "SNOW", "WATER",
                        "WOOD", "BRICK",
                    ],
                    "description": "Preset type to create",
                },
                "color": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Override base color as RGBA (0-1). Optional; each preset has a sensible default.",
                },
                "wear_amount": {
                    "type": "number",
                    "description": "Wear/aging intensity 0-1 (used by presets that support it, e.g. WORN_METAL, SCRATCHED_PAINT)",
                },
                "scale": {
                    "type": "number",
                    "description": "Texture scale multiplier (default 1.0). Affects procedural pattern size.",
                },
            },
            "required": ["name", "preset"],
        },
    ),
    Tool(
        name="blender_material_convert_to_pbr",
        description=(
            "Convert a material's existing node tree to a clean Principled BSDF setup. "
            "Analyzes current nodes to extract color, roughness, metallic, etc., then rebuilds "
            "as a standard PBR graph compatible with the target format."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "material_name": {
                    "type": "string",
                    "description": "Name of the material to convert",
                },
                "target_format": {
                    "type": "string",
                    "enum": ["GLTF", "MSFS", "UE5", "GENERIC"],
                    "description": "Target format to optimize the PBR setup for",
                },
            },
            "required": ["material_name", "target_format"],
        },
    ),
    Tool(
        name="blender_material_preview_render",
        description=(
            "Render a material preview on a standard shape. Creates a temporary scene "
            "with the chosen shape, assigns the material, renders it, and returns the output path."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "material_name": {
                    "type": "string",
                    "description": "Name of the material to preview",
                },
                "preview_shape": {
                    "type": "string",
                    "enum": ["SPHERE", "CUBE", "PLANE", "CYLINDER"],
                    "description": "Shape to render the material on (default: SPHERE)",
                },
                "output_path": {
                    "type": "string",
                    "description": "Output file path (default: /tmp/material_preview_<name>.png)",
                },
                "resolution": {
                    "type": "number",
                    "description": "Render resolution in pixels, used for both width and height (default: 512)",
                },
                "engine": {
                    "type": "string",
                    "enum": ["EEVEE", "CYCLES"],
                    "description": "Render engine (default: EEVEE)",
                },
            },
            "required": ["material_name"],
        },
    ),

    # ── Measurement & Validation (7 tools) ──

    # ── 1. Surface Area ──────────────────────────────────────────────
    Tool(
        name="blender_measure_surface_area",
        description=(
            "Calculate total surface area of a mesh object, with optional "
            "per-material breakdown.  Reports area in scene units squared "
            "(typically m^2).  Supports local or world-space calculation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to measure",
                },
                "per_material": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "If true, return area breakdown grouped by material slot"
                    ),
                },
                "world_space": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "If true, apply the object's world matrix so the area "
                        "reflects actual scene-space size"
                    ),
                },
            },
            "required": ["object_name"],
        },
    ),

    # ── 2. Volume ────────────────────────────────────────────────────
    Tool(
        name="blender_measure_volume",
        description=(
            "Calculate the enclosed volume of a mesh object.  Returns "
            "volume in scene units cubed (typically m^3).  Also reports "
            "whether the mesh is manifold (watertight)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to measure",
                },
            },
            "required": ["object_name"],
        },
    ),

    # ── 3. Clearance ─────────────────────────────────────────────────
    Tool(
        name="blender_measure_clearance",
        description=(
            "Measure the minimum, average, and maximum distance between "
            "two mesh objects.  Detects intersection (overlap) and returns "
            "the closest point pair.  Useful for collision/clearance checks."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_a": {
                    "type": "string",
                    "description": "Name of the first mesh object",
                },
                "object_b": {
                    "type": "string",
                    "description": "Name of the second mesh object",
                },
                "sample_count": {
                    "type": "number",
                    "default": 1000,
                    "description": (
                        "Maximum number of vertices to sample from object_a "
                        "when computing distances (higher = more accurate, slower)"
                    ),
                },
            },
            "required": ["object_a", "object_b"],
        },
    ),

    # ── 4. Validate Dimensions ───────────────────────────────────────
    Tool(
        name="blender_validate_dimensions",
        description=(
            "Check an object's bounding-box dimensions against expected "
            "values with a configurable tolerance.  Reports per-axis "
            "pass/fail with deviations."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the object to validate",
                },
                "expected": {
                    "type": "object",
                    "properties": {
                        "length": {
                            "type": "number",
                            "description": "Expected length (mapped via axis_mapping)",
                        },
                        "width": {
                            "type": "number",
                            "description": "Expected width (mapped via axis_mapping)",
                        },
                        "height": {
                            "type": "number",
                            "description": "Expected height (mapped via axis_mapping)",
                        },
                    },
                    "description": (
                        "Expected dimensions. Provide any subset of "
                        "length/width/height."
                    ),
                },
                "tolerance": {
                    "type": "number",
                    "default": 0.01,
                    "description": (
                        "Allowed absolute deviation per axis (scene units)"
                    ),
                },
                "axis_mapping": {
                    "type": "object",
                    "properties": {
                        "length": {
                            "type": "string",
                            "enum": ["x", "y", "z"],
                            "description": "Which axis corresponds to length",
                        },
                        "width": {
                            "type": "string",
                            "enum": ["x", "y", "z"],
                            "description": "Which axis corresponds to width",
                        },
                        "height": {
                            "type": "string",
                            "enum": ["x", "y", "z"],
                            "description": "Which axis corresponds to height",
                        },
                    },
                    "description": (
                        "Map length/width/height to scene axes.  "
                        "Defaults to length=x, width=y, height=z."
                    ),
                },
            },
            "required": ["object_name", "expected"],
        },
    ),

    # ── 5. Calibrate from Reference ──────────────────────────────────
    Tool(
        name="blender_calibrate_from_reference",
        description=(
            "Scale an object uniformly so that a known real-world "
            "dimension matches along a chosen axis.  Applies transforms "
            "afterwards so scale returns to (1,1,1)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the object to calibrate",
                },
                "known_dimension": {
                    "type": "number",
                    "description": (
                        "Real-world size the object should be along the "
                        "chosen axis, in target_units"
                    ),
                },
                "dimension_axis": {
                    "type": "string",
                    "enum": ["X", "Y", "Z"],
                    "description": "Axis to match the known dimension on",
                },
                "target_units": {
                    "type": "string",
                    "enum": ["METERS", "CM", "MM", "INCHES", "FEET"],
                    "default": "METERS",
                    "description": (
                        "Unit system for known_dimension.  The value is "
                        "converted to scene units (meters) before scaling."
                    ),
                },
            },
            "required": ["object_name", "known_dimension", "dimension_axis"],
        },
    ),

    # ── 6. Edge Angle ────────────────────────────────────────────────
    Tool(
        name="blender_measure_edge_angle",
        description=(
            "Measure dihedral angles (face-to-face) at mesh edges.  "
            "Optionally filter to specific edge indices and flag edges "
            "outside a threshold range.  Angles are in degrees."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object",
                },
                "edge_indices": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "Specific edge indices to measure.  "
                        "If omitted, all edges with 2+ linked faces are measured."
                    ),
                },
                "threshold_min": {
                    "type": "number",
                    "description": (
                        "Minimum acceptable angle in degrees.  "
                        "Edges below this are flagged."
                    ),
                },
                "threshold_max": {
                    "type": "number",
                    "description": (
                        "Maximum acceptable angle in degrees.  "
                        "Edges above this are flagged."
                    ),
                },
            },
            "required": ["object_name"],
        },
    ),

    # ── 7. Validate Mesh Quality ─────────────────────────────────────
    Tool(
        name="blender_validate_mesh_quality",
        description=(
            "Run a comprehensive mesh quality audit.  Returns an overall "
            "score (0-1), per-check pass/fail results, and a list of "
            "blocking issues that would prevent clean export."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to validate",
                },
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "NON_MANIFOLD",
                            "DEGENERATE",
                            "FLIPPED_NORMALS",
                            "ZERO_AREA",
                            "NGONS",
                            "TRIS",
                            "UV_COVERAGE",
                            "UV_OVERLAP",
                            "MATERIAL_ASSIGNMENT",
                            "SCALE_APPLIED",
                            "ORIGIN_CENTERED",
                        ],
                    },
                    "description": (
                        "List of checks to run.  If omitted, all checks "
                        "are executed."
                    ),
                },
            },
            "required": ["object_name"],
        },
    ),

    # ── Collections & System (8 tools) ──

    # ========== Collection Tools ==========
    Tool(
        name="blender_collection_create",
        description="Create a new collection. Collections organize objects into logical groups in the scene hierarchy.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the new collection",
                },
                "parent": {
                    "type": "string",
                    "description": "Name of parent collection to nest under (defaults to Scene Collection)",
                },
                "color_tag": {
                    "type": "string",
                    "enum": [
                        "NONE",
                        "COLOR_01",
                        "COLOR_02",
                        "COLOR_03",
                        "COLOR_04",
                        "COLOR_05",
                        "COLOR_06",
                        "COLOR_07",
                        "COLOR_08",
                    ],
                    "description": "Color tag for the collection in the outliner",
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="blender_collection_list",
        description="List all collections in the scene with their full hierarchy, objects, visibility, and render state. Returns a nested tree structure.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="blender_collection_move",
        description="Move one or more objects to a target collection. Can optionally remove them from their current collections.",
        inputSchema={
            "type": "object",
            "properties": {
                "object_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of objects to move",
                },
                "target_collection": {
                    "type": "string",
                    "description": "Name of the target collection to move objects into",
                },
                "remove_from_current": {
                    "type": "boolean",
                    "description": "Remove objects from their current collections (default: true). Set false to link into multiple collections.",
                },
            },
            "required": ["object_names", "target_collection"],
        },
    ),
    Tool(
        name="blender_collection_visibility",
        description="Toggle collection visibility, renderability, and selectability in the current view layer.",
        inputSchema={
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Name of the collection",
                },
                "visible": {
                    "type": "boolean",
                    "description": "Set viewport visibility (hide_viewport on the layer collection)",
                },
                "renderable": {
                    "type": "boolean",
                    "description": "Set whether the collection renders",
                },
                "selectable": {
                    "type": "boolean",
                    "description": "Set whether objects in the collection are selectable",
                },
            },
            "required": ["collection_name"],
        },
    ),
    # ========== System Tools ==========
    Tool(
        name="blender_undo",
        description="Undo the last operation in Blender. Equivalent to Ctrl+Z.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="blender_redo",
        description="Redo the last undone operation in Blender. Equivalent to Ctrl+Shift+Z.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="blender_save",
        description="Save the current Blender file. The file must have been saved at least once before (has a filepath).",
        inputSchema={
            "type": "object",
            "properties": {
                "compress": {
                    "type": "boolean",
                    "description": "Use file compression (default: false)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="blender_save_as",
        description="Save the current Blender file to a new path. Creates parent directories if needed.",
        inputSchema={
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Full file path to save to (should end in .blend)",
                },
                "compress": {
                    "type": "boolean",
                    "description": "Use file compression (default: false)",
                },
                "copy": {
                    "type": "boolean",
                    "description": "Save a copy without changing the current file path (default: false)",
                },
            },
            "required": ["filepath"],
        },
    ),

    # ── Baking (6 tools) ──

    # ── 1. Batch PBR Baking ──
    Tool(
        name="blender_bake_pbr_batch",
        description=(
            "Bake ALL PBR texture channels in one call. Switches to Cycles, iterates "
            "over requested channels (DIFFUSE, ROUGHNESS, METALLIC, NORMAL, AO, EMISSION, "
            "DISPLACEMENT, COMBINED), creates temp images, configures bake settings, and "
            "saves each map to disk. Returns a dict mapping channel name to output file path."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the object to bake from",
                },
                "channels": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "DIFFUSE", "ROUGHNESS", "METALLIC", "NORMAL",
                            "AO", "EMISSION", "DISPLACEMENT", "COMBINED",
                        ],
                    },
                    "description": (
                        "Which PBR channels to bake. Default: all channels. "
                        "Each channel produces a separate texture file."
                    ),
                },
                "resolution": {
                    "type": "number",
                    "description": "Texture resolution in pixels (default 2048)",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Directory to save baked textures",
                },
                "output_prefix": {
                    "type": "string",
                    "description": "Filename prefix (defaults to object name)",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["PNG", "TARGA", "OPEN_EXR"],
                    "description": "Image output format (default PNG)",
                },
                "margin": {
                    "type": "number",
                    "description": "Bake margin in pixels (default 16)",
                },
                "samples": {
                    "type": "number",
                    "description": "Cycles render samples for baking (default 128)",
                },
                "use_cage": {
                    "type": "boolean",
                    "description": "Use cage for ray casting (default false)",
                },
                "cage_extrusion": {
                    "type": "number",
                    "description": "Cage extrusion distance (default 0.1)",
                },
                "normal_space": {
                    "type": "string",
                    "enum": ["TANGENT", "OBJECT"],
                    "description": "Normal map space (default TANGENT)",
                },
            },
            "required": ["object_name", "output_dir"],
        },
    ),

    # ── 2. High-poly to Low-poly Baking ──
    Tool(
        name="blender_bake_highpoly_to_lowpoly",
        description=(
            "Bake detail from a high-poly mesh onto a low-poly mesh using 'selected to active'. "
            "Ideal for transferring normals, AO, and other maps from a sculpt or subdivision "
            "model to a game-ready low-poly mesh."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "lowpoly_name": {
                    "type": "string",
                    "description": "Name of the low-poly target object (active)",
                },
                "highpoly_name": {
                    "type": "string",
                    "description": "Name of the high-poly source object (selected)",
                },
                "channels": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "DIFFUSE", "ROUGHNESS", "METALLIC", "NORMAL",
                            "AO", "EMISSION", "DISPLACEMENT", "COMBINED",
                        ],
                    },
                    "description": "Channels to bake (default: [NORMAL, AO])",
                },
                "resolution": {
                    "type": "number",
                    "description": "Texture resolution in pixels (default 2048)",
                },
                "cage_extrusion": {
                    "type": "number",
                    "description": "Cage extrusion distance (default 0.1)",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Directory to save baked textures",
                },
                "output_prefix": {
                    "type": "string",
                    "description": "Filename prefix (defaults to lowpoly object name)",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["PNG", "TARGA", "OPEN_EXR"],
                    "description": "Image output format (default PNG)",
                },
                "margin": {
                    "type": "number",
                    "description": "Bake margin in pixels (default 16)",
                },
                "samples": {
                    "type": "number",
                    "description": "Cycles render samples (default 128)",
                },
            },
            "required": ["lowpoly_name", "highpoly_name", "output_dir"],
        },
    ),

    # ── 3. Multires Baking ──
    Tool(
        name="blender_bake_from_multires",
        description=(
            "Bake maps from a Multiresolution modifier (normals or displacement). "
            "Uses Blender's multires bake mode to transfer detail from higher "
            "subdivision levels to a texture."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the object with a Multiresolution modifier",
                },
                "map_type": {
                    "type": "string",
                    "enum": ["NORMALS", "DISPLACEMENT"],
                    "description": "Type of map to bake (default NORMALS)",
                },
                "resolution": {
                    "type": "number",
                    "description": "Texture resolution in pixels (default 2048)",
                },
                "output_path": {
                    "type": "string",
                    "description": "Full file path for the output image",
                },
                "margin": {
                    "type": "number",
                    "description": "Bake margin in pixels (default 16)",
                },
            },
            "required": ["object_name", "output_path"],
        },
    ),

    # ── 4. Bake to Vertex Colors ──
    Tool(
        name="blender_bake_to_vertex_colors",
        description=(
            "Bake lighting or material information directly to vertex colors. "
            "Creates a vertex color layer, bakes to a temporary image, then transfers "
            "pixel data to per-vertex colors via UV lookup. Useful for mobile/performance "
            "rendering where texture lookups are expensive."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the object to bake",
                },
                "bake_type": {
                    "type": "string",
                    "enum": ["AO", "DIFFUSE", "COMBINED"],
                    "description": "Type of bake (default AO)",
                },
                "vertex_color_name": {
                    "type": "string",
                    "description": "Name for the vertex color layer (default 'BakedColor')",
                },
                "samples": {
                    "type": "number",
                    "description": "Cycles render samples (default 64)",
                },
            },
            "required": ["object_name"],
        },
    ),

    # ── 5. Curvature Map Baking ──
    Tool(
        name="blender_bake_curvature",
        description=(
            "Bake a curvature map from mesh geometry. Calculates per-vertex curvature "
            "using the dot product of vertex normals vs averaged neighbor normals. "
            "Maps concave areas to dark, convex to bright (or both). Useful for "
            "edge wear, dirt accumulation, and procedural texturing masks."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the object to calculate curvature for",
                },
                "resolution": {
                    "type": "number",
                    "description": "Output texture resolution in pixels (default 2048)",
                },
                "output_path": {
                    "type": "string",
                    "description": "Full file path for the output curvature map",
                },
                "cavity_type": {
                    "type": "string",
                    "enum": ["CONCAVE", "CONVEX", "BOTH"],
                    "description": (
                        "Which curvature to capture: CONCAVE (cavities dark), "
                        "CONVEX (edges bright), or BOTH (default BOTH)"
                    ),
                },
            },
            "required": ["object_name", "output_path"],
        },
    ),

    # ── 6. ID Map Baking ──
    Tool(
        name="blender_bake_id_map",
        description=(
            "Bake a color ID map where each material, object, or face set is assigned "
            "a distinct flat color. Temporarily overrides materials with emission shaders, "
            "bakes EMIT, then restores originals. Essential for texture painting workflows "
            "and Substance Painter masks."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the object to bake ID map for",
                },
                "resolution": {
                    "type": "number",
                    "description": "Output texture resolution in pixels (default 2048)",
                },
                "output_path": {
                    "type": "string",
                    "description": "Full file path for the output ID map",
                },
                "color_mode": {
                    "type": "string",
                    "enum": ["PER_MATERIAL", "PER_OBJECT", "PER_FACE_SET"],
                    "description": (
                        "How to assign ID colors: PER_MATERIAL (one color per material slot), "
                        "PER_OBJECT (one color per joined sub-object), or PER_FACE_SET "
                        "(one color per face set). Default PER_MATERIAL."
                    ),
                },
            },
            "required": ["object_name", "output_path"],
        },
    ),

    # ── Geometry Nodes (7 tools) ──

    # ── 1. Create Group ──────────────────────────────────────────────
    Tool(
        name="blender_geonode_create_group",
        description=(
            "Create a new Geometry Nodes node group with typed inputs "
            "and outputs.  A Geometry input and Geometry output are always "
            "added automatically.  Returns the group name and socket layout."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the new geometry node group",
                },
                "inputs": {
                    "type": "array",
                    "description": (
                        "Extra input sockets to add (beyond the default "
                        "Geometry input)"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Socket display name",
                            },
                            "type": {
                                "type": "string",
                                "enum": ["FLOAT", "INT", "VECTOR", "BOOLEAN", "OBJECT", "COLLECTION", "MATERIAL", "IMAGE", "STRING"],
                                "description": "Socket data type",
                            },
                            "default": {
                                "description": (
                                    "Default value for the socket (number, "
                                    "bool, [x,y,z], or string)"
                                ),
                            },
                        },
                        "required": ["name", "type"],
                    },
                },
                "outputs": {
                    "type": "array",
                    "description": (
                        "Extra output sockets to add (beyond the default "
                        "Geometry output)"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Socket display name",
                            },
                            "type": {
                                "type": "string",
                                "enum": ["FLOAT", "INT", "VECTOR", "BOOLEAN", "OBJECT", "COLLECTION", "MATERIAL", "IMAGE", "STRING"],
                                "description": "Socket data type",
                            },
                        },
                        "required": ["name", "type"],
                    },
                },
            },
            "required": ["name"],
        },
    ),

    # ── 2. Apply to Object ───────────────────────────────────────────
    Tool(
        name="blender_geonode_apply",
        description=(
            "Apply an existing Geometry Nodes group to an object as a "
            "modifier and optionally set input values.  Returns the "
            "modifier name and current input state."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the object to add the modifier to",
                },
                "node_group": {
                    "type": "string",
                    "description": (
                        "Name of an existing GeometryNodeTree in bpy.data.node_groups"
                    ),
                },
                "inputs": {
                    "type": "object",
                    "description": (
                        "Mapping of input socket names to values.  "
                        "Numbers, booleans, [x,y,z] vectors, and object/"
                        "material names (as strings) are accepted."
                    ),
                },
            },
            "required": ["object_name", "node_group"],
        },
    ),

    # ── 3. Scatter Instances ─────────────────────────────────────────
    Tool(
        name="blender_geonode_scatter_instances",
        description=(
            "One-call scatter: build a complete Geometry Nodes setup that "
            "distributes instances of one object across the surface of "
            "another.  Supports density, Poisson-disk spacing, random "
            "scale range, random rotation, and normal alignment."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target_object": {
                    "type": "string",
                    "description": "Name of the surface object to scatter onto",
                },
                "instance_object": {
                    "type": "string",
                    "description": "Name of the object to instance",
                },
                "density": {
                    "type": "number",
                    "default": 10.0,
                    "description": "Points per unit area (higher = more instances)",
                },
                "seed": {
                    "type": "number",
                    "default": 0,
                    "description": "Random seed for distribution",
                },
                "min_distance": {
                    "type": "number",
                    "default": 0.0,
                    "description": (
                        "Minimum distance between points.  If > 0, Poisson "
                        "Disk distribution is used instead of random."
                    ),
                },
                "scale_min": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Minimum random scale factor",
                },
                "scale_max": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Maximum random scale factor",
                },
                "rotation_random": {
                    "type": "array",
                    "items": {"type": "number"},
                    "default": [0, 0, 0],
                    "description": (
                        "Random rotation range in degrees [X, Y, Z].  "
                        "Each axis gets uniform random rotation from "
                        "-value to +value."
                    ),
                },
                "align_to_normal": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Rotate instances to align with the surface normal"
                    ),
                },
            },
            "required": ["target_object", "instance_object"],
        },
    ),

    # ── 4. Array / Grid ──────────────────────────────────────────────
    Tool(
        name="blender_geonode_array_grid",
        description=(
            "Parametric array patterns via Geometry Nodes.  Instances an "
            "object in LINEAR, GRID_2D, RADIAL, or HEXAGONAL arrangements.  "
            "The modifier is applied to object_name."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": (
                        "Object that receives the GN modifier (typically "
                        "an empty or the instance_object itself)"
                    ),
                },
                "instance_object": {
                    "type": "string",
                    "description": "Object to be instanced in the pattern",
                },
                "grid_type": {
                    "type": "string",
                    "enum": ["LINEAR", "GRID_2D", "RADIAL", "HEXAGONAL"],
                    "description": "Type of array pattern",
                },
                "count_x": {
                    "type": "number",
                    "default": 5,
                    "description": "Count along primary axis (or total for LINEAR)",
                },
                "count_y": {
                    "type": "number",
                    "default": 5,
                    "description": "Count along secondary axis (GRID_2D / HEXAGONAL)",
                },
                "spacing_x": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Spacing along primary axis (scene units)",
                },
                "spacing_y": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Spacing along secondary axis (scene units)",
                },
                "radial_count": {
                    "type": "number",
                    "default": 8,
                    "description": "Number of instances around the circle (RADIAL)",
                },
                "radial_radius": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Radius of the circle (RADIAL)",
                },
            },
            "required": ["object_name", "instance_object", "grid_type"],
        },
    ),

    # ── 5. Deform Along Curve ────────────────────────────────────────
    Tool(
        name="blender_geonode_deform_curve",
        description=(
            "Deform a mesh along a curve using Geometry Nodes.  "
            "The mesh is stretched or fitted along the curve length.  "
            "Useful for roads, rails, cables, and profile sweeps."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the mesh object to deform",
                },
                "curve_name": {
                    "type": "string",
                    "description": "Name of the curve object to deform along",
                },
                "stretch": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "If true, stretch the mesh to fill the curve length; "
                        "otherwise clamp to original mesh length"
                    ),
                },
            },
            "required": ["object_name", "curve_name"],
        },
    ),

    # ── 6. Extrude Profile Along Curve ───────────────────────────────
    Tool(
        name="blender_geonode_extrude_profile",
        description=(
            "Extrude a 2D profile mesh along a curve path using the "
            "Curve to Mesh node.  Creates a new object with the extruded "
            "geometry.  Great for pipes, railings, moulding, and trim."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "profile_object": {
                    "type": "string",
                    "description": (
                        "Name of the profile object (mesh or curve) to "
                        "sweep along the path"
                    ),
                },
                "curve_name": {
                    "type": "string",
                    "description": "Name of the curve to extrude along",
                },
                "name": {
                    "type": "string",
                    "default": "ExtrudedProfile",
                    "description": "Name for the resulting object",
                },
                "fill_caps": {
                    "type": "boolean",
                    "default": True,
                    "description": "Fill the start and end caps of the extrusion",
                },
                "resolution": {
                    "type": "number",
                    "default": 12,
                    "description": (
                        "Curve resolution (segments per spline point).  "
                        "Higher values produce smoother bends."
                    ),
                },
            },
            "required": ["profile_object", "curve_name"],
        },
    ),

    # ── 7. Inspect GN Setup ──────────────────────────────────────────
    Tool(
        name="blender_geonode_inspect",
        description=(
            "Read the current Geometry Nodes setup on an object.  "
            "Returns the node group name, all input names/types/current "
            "values, and output names.  Useful for introspection before "
            "tweaking values with geonode_apply."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "Name of the object to inspect",
                },
                "modifier_name": {
                    "type": "string",
                    "description": (
                        "Name of a specific GN modifier.  If omitted, the "
                        "first Geometry Nodes modifier found is used."
                    ),
                },
            },
            "required": ["object_name"],
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

            # Extract timeout from arguments, or use longer defaults
            # for known long-running commands
            timeout = arguments.pop("timeout", None)
            if timeout is None:
                _long_running = {
                    "ai_pipeline_generate", "ai_generate_model_sync",
                    "ai_generate_texture_sync", "ai_auto_uv",
                    "render_animation", "render_multi_angle",
                    "ai_generate_model",
                }
                timeout = 600.0 if command in _long_running else 30.0

            result = await client.send_command(command, arguments, timeout=timeout)

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
