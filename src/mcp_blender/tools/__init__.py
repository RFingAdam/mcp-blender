"""Tool modules for MCP Blender server."""

from .animation import register_animation_tools
from .export import register_export_tools
from .external import register_external_tools
from .materials import register_material_tools
from .modifiers import register_modifier_tools
from .objects import register_object_tools
from .render import register_render_tools
from .scene import register_scene_tools

__all__ = [
    "register_scene_tools",
    "register_object_tools",
    "register_material_tools",
    "register_modifier_tools",
    "register_animation_tools",
    "register_render_tools",
    "register_export_tools",
    "register_external_tools",
]
