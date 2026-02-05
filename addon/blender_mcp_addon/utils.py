"""Utility functions for the Blender MCP addon."""

import bpy
import json
import fnmatch
from typing import Any


def serialize_vector(vec) -> list[float]:
    """Convert a Blender vector to a list of floats."""
    return [float(v) for v in vec]


def serialize_color(color) -> list[float]:
    """Convert a Blender color to a list of floats."""
    return [float(c) for c in color]


def serialize_object(obj) -> dict[str, Any]:
    """Serialize a Blender object to a dictionary."""
    data = {
        "name": obj.name,
        "type": obj.type,
        "location": serialize_vector(obj.location),
        "rotation_euler": serialize_vector(obj.rotation_euler),
        "scale": serialize_vector(obj.scale),
        "visible": obj.visible_get(),
        "parent": obj.parent.name if obj.parent else None,
    }

    # Add mesh-specific data
    if obj.type == "MESH" and obj.data:
        data["mesh"] = {
            "name": obj.data.name,
            "vertices": len(obj.data.vertices),
            "edges": len(obj.data.edges),
            "polygons": len(obj.data.polygons),
        }
        # Add material slots
        data["materials"] = [
            slot.material.name if slot.material else None for slot in obj.material_slots
        ]
        # Add modifiers
        data["modifiers"] = [
            {"name": mod.name, "type": mod.type} for mod in obj.modifiers
        ]

    return data


def serialize_material(mat) -> dict[str, Any]:
    """Serialize a Blender material to a dictionary."""
    data = {
        "name": mat.name,
        "use_nodes": mat.use_nodes,
    }

    if mat.use_nodes and mat.node_tree:
        # Find Principled BSDF node
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                inputs = {}
                for inp in node.inputs:
                    if hasattr(inp, "default_value"):
                        try:
                            if hasattr(inp.default_value, "__iter__"):
                                inputs[inp.name] = serialize_vector(inp.default_value)
                            else:
                                inputs[inp.name] = float(inp.default_value)
                        except (TypeError, ValueError):
                            pass
                data["principled_bsdf"] = inputs
                break

    return data


def serialize_scene(scene) -> dict[str, Any]:
    """Serialize scene information to a dictionary."""
    return {
        "name": scene.name,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_current": scene.frame_current,
        "fps": scene.render.fps,
        "object_count": len(scene.objects),
        "render_engine": scene.render.engine,
        "resolution_x": scene.render.resolution_x,
        "resolution_y": scene.render.resolution_y,
    }


def find_objects_by_pattern(pattern: str) -> list:
    """Find objects matching a glob pattern."""
    return [obj for obj in bpy.data.objects if fnmatch.fnmatch(obj.name, pattern)]


def ensure_object_selected(obj, context=None):
    """Ensure an object is selected and active."""
    if context is None:
        context = bpy.context

    # Deselect all
    bpy.ops.object.select_all(action="DESELECT")

    # Select and make active
    obj.select_set(True)
    context.view_layer.objects.active = obj


def safe_mode_set(mode: str, obj=None):
    """Safely set the object mode, handling edge cases."""
    if obj is None:
        obj = bpy.context.active_object

    if obj is None:
        return False

    if obj.mode != mode:
        try:
            bpy.ops.object.mode_set(mode=mode)
            return True
        except RuntimeError:
            return False
    return True


def create_response(result: Any = None, error: str | None = None) -> dict:
    """Create a standardized response dictionary."""
    if error:
        return {"success": False, "error": error}
    return {"success": True, "result": result}


def json_serialize(obj: Any) -> str:
    """Serialize an object to JSON, handling Blender types."""

    def default_handler(o):
        if hasattr(o, "__iter__") and not isinstance(o, (str, bytes, dict)):
            return list(o)
        raise TypeError(f"Object of type {type(o)} is not JSON serializable")

    return json.dumps(obj, default=default_handler)


def parse_color(color_input) -> tuple[float, float, float, float]:
    """Parse color input to RGBA tuple."""
    if isinstance(color_input, (list, tuple)):
        if len(color_input) == 3:
            return (float(color_input[0]), float(color_input[1]), float(color_input[2]), 1.0)
        elif len(color_input) >= 4:
            return (
                float(color_input[0]),
                float(color_input[1]),
                float(color_input[2]),
                float(color_input[3]),
            )
    raise ValueError(f"Invalid color format: {color_input}")


def get_object_or_error(name: str):
    """Get an object by name or raise an error."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")
    return obj


def get_material_or_error(name: str):
    """Get a material by name or raise an error."""
    mat = bpy.data.materials.get(name)
    if mat is None:
        raise ValueError(f"Material not found: {name}")
    return mat
