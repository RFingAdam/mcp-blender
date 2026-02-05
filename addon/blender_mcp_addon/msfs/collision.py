"""Collision mesh tools for MSFS content."""

from typing import Any

import bmesh
import bpy
from mathutils import Vector

# MSFS collision types
COLLISION_TYPES = {
    "none": "NONE",
    "collider": "COLLIDER",
    "road": "ROAD",
    "water": "WATER",
    "trigger": "TRIGGER",
}

# Collision mesh naming convention for MSFS
COLLISION_PREFIX = "_COL_"


def create_collision_mesh(
    source_object_name: str,
    collision_type: str = "collider",
    simplify: bool = True,
    simplify_ratio: float = 0.3,
) -> dict[str, Any]:
    """Create a collision mesh from a source object.

    Args:
        source_object_name: Name of the source object
        collision_type: Type of collision (collider, road, water, trigger)
        simplify: Whether to simplify the collision mesh
        simplify_ratio: Simplification ratio if simplifying

    Returns:
        Dictionary with collision mesh info
    """
    source_obj = bpy.data.objects.get(source_object_name)
    if not source_obj:
        return {"error": f"Object not found: {source_object_name}"}

    if source_obj.type != "MESH":
        return {"error": f"Object must be a mesh, got {source_obj.type}"}

    if collision_type not in COLLISION_TYPES:
        return {
            "error": f"Invalid collision type: {collision_type}",
            "valid_types": list(COLLISION_TYPES.keys()),
        }

    # Create collision mesh name
    collision_name = f"{COLLISION_PREFIX}{source_object_name}"

    # Duplicate the source object
    collision_obj = source_obj.copy()
    collision_obj.data = source_obj.data.copy()
    collision_obj.name = collision_name
    collision_obj.data.name = f"{collision_name}_mesh"

    # Link to scene
    bpy.context.scene.collection.objects.link(collision_obj)

    # Simplify if requested
    if simplify and simplify_ratio < 1.0:
        decimate = collision_obj.modifiers.new(name="Simplify", type="DECIMATE")
        decimate.decimate_type = "COLLAPSE"
        decimate.ratio = simplify_ratio

        bpy.context.view_layer.objects.active = collision_obj
        with bpy.context.temp_override(object=collision_obj):
            bpy.ops.object.modifier_apply(modifier=decimate.name)

    # Clear materials from collision mesh
    collision_obj.data.materials.clear()

    # Set collision properties
    _set_collision_properties(collision_obj, collision_type)

    # Hide collision mesh in viewport (but keep for export)
    collision_obj.hide_viewport = True
    collision_obj.hide_render = True

    # Parent to source object
    collision_obj.parent = source_obj
    collision_obj.matrix_parent_inverse = source_obj.matrix_world.inverted()

    return {
        "collision_mesh": collision_name,
        "source_object": source_object_name,
        "collision_type": collision_type,
        "vertex_count": len(collision_obj.data.vertices),
        "face_count": len(collision_obj.data.polygons),
    }


def create_collision_box(
    object_name: str,
    collision_type: str = "collider",
    padding: float = 0.0,
) -> dict[str, Any]:
    """Create a box collision primitive for an object.

    Args:
        object_name: Name of the object to create collision for
        collision_type: Type of collision
        padding: Extra padding around the bounding box

    Returns:
        Dictionary with collision box info
    """
    source_obj = bpy.data.objects.get(object_name)
    if not source_obj:
        return {"error": f"Object not found: {object_name}"}

    if collision_type not in COLLISION_TYPES:
        return {
            "error": f"Invalid collision type: {collision_type}",
            "valid_types": list(COLLISION_TYPES.keys()),
        }

    # Get bounding box in world space
    bbox_corners = [source_obj.matrix_world @ Vector(corner) for corner in source_obj.bound_box]

    # Calculate dimensions
    min_co = Vector((
        min(c.x for c in bbox_corners),
        min(c.y for c in bbox_corners),
        min(c.z for c in bbox_corners),
    ))
    max_co = Vector((
        max(c.x for c in bbox_corners),
        max(c.y for c in bbox_corners),
        max(c.z for c in bbox_corners),
    ))

    # Add padding
    min_co -= Vector((padding, padding, padding))
    max_co += Vector((padding, padding, padding))

    center = (min_co + max_co) / 2
    dimensions = max_co - min_co

    # Create collision box name
    collision_name = f"{COLLISION_PREFIX}{object_name}_box"

    # Create cube
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    collision_obj = bpy.context.active_object
    collision_obj.name = collision_name
    collision_obj.scale = dimensions

    # Apply scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    # Set collision properties
    _set_collision_properties(collision_obj, collision_type)

    # Hide in viewport
    collision_obj.hide_viewport = True
    collision_obj.hide_render = True

    # Parent to source
    collision_obj.parent = source_obj
    collision_obj.matrix_parent_inverse = source_obj.matrix_world.inverted()

    return {
        "collision_mesh": collision_name,
        "source_object": object_name,
        "collision_type": collision_type,
        "dimensions": list(dimensions),
        "center": list(center),
        "is_box": True,
    }


def create_collision_convex(
    object_name: str,
    collision_type: str = "collider",
) -> dict[str, Any]:
    """Create a convex hull collision mesh.

    Args:
        object_name: Name of the source object
        collision_type: Type of collision

    Returns:
        Dictionary with collision mesh info
    """
    source_obj = bpy.data.objects.get(object_name)
    if not source_obj:
        return {"error": f"Object not found: {object_name}"}

    if source_obj.type != "MESH":
        return {"error": f"Object must be a mesh, got {source_obj.type}"}

    if collision_type not in COLLISION_TYPES:
        return {
            "error": f"Invalid collision type: {collision_type}",
            "valid_types": list(COLLISION_TYPES.keys()),
        }

    # Create collision mesh name
    collision_name = f"{COLLISION_PREFIX}{object_name}_convex"

    # Duplicate
    collision_obj = source_obj.copy()
    collision_obj.data = source_obj.data.copy()
    collision_obj.name = collision_name
    collision_obj.data.name = f"{collision_name}_mesh"

    bpy.context.scene.collection.objects.link(collision_obj)

    # Create convex hull
    bm = bmesh.new()
    bm.from_mesh(collision_obj.data)

    # Get all vertex positions
    verts = [v.co.copy() for v in bm.verts]

    # Clear mesh
    bm.clear()

    # Create convex hull
    if verts:
        bmesh.ops.convex_hull(bm, input=[bm.verts.new(v) for v in verts])

    bm.to_mesh(collision_obj.data)
    bm.free()

    # Clear materials
    collision_obj.data.materials.clear()

    # Set collision properties
    _set_collision_properties(collision_obj, collision_type)

    # Hide in viewport
    collision_obj.hide_viewport = True
    collision_obj.hide_render = True

    # Parent to source
    collision_obj.parent = source_obj
    collision_obj.matrix_parent_inverse = source_obj.matrix_world.inverted()

    return {
        "collision_mesh": collision_name,
        "source_object": object_name,
        "collision_type": collision_type,
        "vertex_count": len(collision_obj.data.vertices),
        "face_count": len(collision_obj.data.polygons),
        "is_convex": True,
    }


def tag_collision_type(
    object_name: str,
    collision_type: str,
) -> dict[str, Any]:
    """Tag an existing object as a collision mesh.

    Args:
        object_name: Name of the object
        collision_type: Type of collision

    Returns:
        Dictionary with tag info
    """
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    if collision_type not in COLLISION_TYPES:
        return {
            "error": f"Invalid collision type: {collision_type}",
            "valid_types": list(COLLISION_TYPES.keys()),
        }

    _set_collision_properties(obj, collision_type)

    return {
        "object": object_name,
        "collision_type": collision_type,
        "msfs_tag": COLLISION_TYPES[collision_type],
    }


def _set_collision_properties(obj: bpy.types.Object, collision_type: str) -> None:
    """Set MSFS collision properties on an object."""
    msfs_tag = COLLISION_TYPES.get(collision_type, "COLLIDER")

    # Store as custom properties (exported to glTF extras)
    obj["MSFS_collision"] = True
    obj["MSFS_collision_type"] = msfs_tag

    # Additional type-specific properties
    if collision_type == "road":
        obj["MSFS_road_material"] = "DEFAULT"
    elif collision_type == "trigger":
        obj["MSFS_trigger_type"] = "ENTER"


def list_collision_meshes(parent_name: str | None = None) -> dict[str, Any]:
    """List all collision meshes in the scene.

    Args:
        parent_name: Optional filter by parent object name

    Returns:
        Dictionary with collision mesh list
    """
    collision_meshes = []

    for obj in bpy.data.objects:
        if obj.get("MSFS_collision"):
            if parent_name and obj.parent and obj.parent.name != parent_name:
                continue

            collision_meshes.append({
                "name": obj.name,
                "collision_type": obj.get("MSFS_collision_type", "COLLIDER"),
                "parent": obj.parent.name if obj.parent else None,
                "vertex_count": len(obj.data.vertices) if obj.type == "MESH" else 0,
            })

    return {
        "collision_meshes": collision_meshes,
        "count": len(collision_meshes),
    }
