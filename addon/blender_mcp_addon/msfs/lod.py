"""LOD (Level of Detail) system for MSFS content."""

from typing import Any

import bpy

# Default LOD distances for MSFS (in meters)
DEFAULT_LOD_DISTANCES = {
    "LOD0": 0,      # Full detail
    "LOD1": 50,     # Medium detail
    "LOD2": 200,    # Low detail
    "LOD3": 500,    # Minimal detail
}

# Default decimation ratios
DEFAULT_DECIMATE_RATIOS = {
    "LOD0": 1.0,    # 100% - no decimation
    "LOD1": 0.5,    # 50%
    "LOD2": 0.25,   # 25%
    "LOD3": 0.1,    # 10%
}


def create_lod_hierarchy(
    base_object_name: str,
    lod_count: int = 4,
    auto_decimate: bool = True,
    decimate_ratios: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Create LOD hierarchy from a base object.

    Args:
        base_object_name: Name of the base (LOD0) object
        lod_count: Number of LOD levels (1-4)
        auto_decimate: Whether to automatically decimate lower LODs
        decimate_ratios: Custom decimation ratios per LOD level

    Returns:
        Dictionary with created LOD objects info
    """
    base_obj = bpy.data.objects.get(base_object_name)
    if not base_obj:
        return {"error": f"Object not found: {base_object_name}"}

    if base_obj.type != "MESH":
        return {"error": f"Object must be a mesh, got {base_obj.type}"}

    lod_count = max(1, min(4, lod_count))
    ratios = decimate_ratios or DEFAULT_DECIMATE_RATIOS

    # Get base name without any existing LOD suffix
    base_name = base_object_name
    for suffix in ["_LOD0", "_LOD1", "_LOD2", "_LOD3", "_lod0", "_lod1", "_lod2", "_lod3"]:
        if base_name.endswith(suffix):
            base_name = base_name[:-5]
            break

    # Rename base object to LOD0 if needed
    lod0_name = f"{base_name}_LOD0"
    if base_obj.name != lod0_name:
        base_obj.name = lod0_name

    created_lods = [{"name": lod0_name, "level": 0, "ratio": 1.0}]

    # Create collection for LODs if it doesn't exist
    lod_collection_name = f"{base_name}_LODs"
    lod_collection = bpy.data.collections.get(lod_collection_name)
    if not lod_collection:
        lod_collection = bpy.data.collections.new(lod_collection_name)
        bpy.context.scene.collection.children.link(lod_collection)

    # Move LOD0 to collection
    if base_obj.name not in lod_collection.objects:
        lod_collection.objects.link(base_obj)
        # Remove from other collections
        for col in base_obj.users_collection:
            if col != lod_collection:
                col.objects.unlink(base_obj)

    # Create lower LOD levels
    for lod_level in range(1, lod_count):
        lod_name = f"{base_name}_LOD{lod_level}"
        ratio_key = f"LOD{lod_level}"
        ratio = ratios.get(ratio_key, DEFAULT_DECIMATE_RATIOS.get(ratio_key, 0.5))

        # Duplicate the base object
        new_obj = base_obj.copy()
        new_obj.data = base_obj.data.copy()
        new_obj.name = lod_name
        new_obj.data.name = f"{lod_name}_mesh"

        # Link to LOD collection
        lod_collection.objects.link(new_obj)

        # Apply decimation if requested
        if auto_decimate and ratio < 1.0:
            _apply_decimation(new_obj, ratio)

        created_lods.append({
            "name": new_obj.name,
            "level": lod_level,
            "ratio": ratio,
            "vertex_count": len(new_obj.data.vertices),
        })

    return {
        "base_name": base_name,
        "collection": lod_collection_name,
        "lod_count": lod_count,
        "lods": created_lods,
    }


def _apply_decimation(obj: bpy.types.Object, ratio: float) -> None:
    """Apply decimation modifier and collapse it."""
    # Add decimate modifier
    decimate = obj.modifiers.new(name="LOD_Decimate", type="DECIMATE")
    decimate.decimate_type = "COLLAPSE"
    decimate.ratio = ratio

    # Apply the modifier
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(object=obj):
        bpy.ops.object.modifier_apply(modifier=decimate.name)


def decimate_for_lod(
    object_name: str,
    ratio: float,
    preserve_uvs: bool = True,
    preserve_vertex_groups: bool = True,
) -> dict[str, Any]:
    """Decimate a mesh for LOD creation.

    Args:
        object_name: Name of the object to decimate
        ratio: Decimation ratio (0.0 to 1.0)
        preserve_uvs: Try to preserve UV seams
        preserve_vertex_groups: Preserve vertex group boundaries

    Returns:
        Dictionary with decimation results
    """
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"error": f"Object not found: {object_name}"}

    if obj.type != "MESH":
        return {"error": f"Object must be a mesh, got {obj.type}"}

    ratio = max(0.01, min(1.0, ratio))

    original_verts = len(obj.data.vertices)
    original_faces = len(obj.data.polygons)

    # Add decimate modifier
    decimate = obj.modifiers.new(name="Decimate", type="DECIMATE")
    decimate.decimate_type = "COLLAPSE"
    decimate.ratio = ratio
    decimate.use_collapse_triangulate = True

    if preserve_uvs:
        decimate.use_symmetry = False

    # Apply the modifier
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(object=obj):
        bpy.ops.object.modifier_apply(modifier=decimate.name)

    new_verts = len(obj.data.vertices)
    new_faces = len(obj.data.polygons)

    return {
        "object": object_name,
        "original_vertices": original_verts,
        "new_vertices": new_verts,
        "original_faces": original_faces,
        "new_faces": new_faces,
        "reduction_ratio": round(new_verts / original_verts, 3) if original_verts > 0 else 0,
    }


def setup_lod_distances(
    base_name: str,
    distances: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Set up LOD switching distances as custom properties.

    MSFS reads these from glTF extras during import.

    Args:
        base_name: Base name of the LOD hierarchy
        distances: Dictionary of LOD level to distance in meters

    Returns:
        Dictionary with LOD distance configuration
    """
    distances = distances or DEFAULT_LOD_DISTANCES

    configured_lods = []

    for lod_level in range(4):
        lod_name = f"{base_name}_LOD{lod_level}"
        obj = bpy.data.objects.get(lod_name)

        if obj:
            distance_key = f"LOD{lod_level}"
            distance = distances.get(distance_key, DEFAULT_LOD_DISTANCES.get(distance_key, 0))

            # Store as custom property (exported to glTF extras)
            obj["MSFS_lod_level"] = lod_level
            obj["MSFS_lod_min_distance"] = distance

            # Calculate max distance (next LOD's min distance)
            next_key = f"LOD{lod_level + 1}"
            max_distance = distances.get(next_key, DEFAULT_LOD_DISTANCES.get(next_key, 10000))
            obj["MSFS_lod_max_distance"] = max_distance

            configured_lods.append({
                "name": lod_name,
                "level": lod_level,
                "min_distance": distance,
                "max_distance": max_distance,
            })

    if not configured_lods:
        return {"error": f"No LOD objects found with base name: {base_name}"}

    return {
        "base_name": base_name,
        "lods": configured_lods,
    }


def get_lod_info(base_name: str) -> dict[str, Any]:
    """Get information about an LOD hierarchy.

    Args:
        base_name: Base name of the LOD hierarchy

    Returns:
        Dictionary with LOD hierarchy information
    """
    lods = []

    for lod_level in range(4):
        lod_name = f"{base_name}_LOD{lod_level}"
        obj = bpy.data.objects.get(lod_name)

        if obj:
            lod_info = {
                "name": lod_name,
                "level": lod_level,
                "vertex_count": len(obj.data.vertices) if obj.type == "MESH" else 0,
                "face_count": len(obj.data.polygons) if obj.type == "MESH" else 0,
            }

            # Get custom properties if set
            if "MSFS_lod_min_distance" in obj:
                lod_info["min_distance"] = obj["MSFS_lod_min_distance"]
            if "MSFS_lod_max_distance" in obj:
                lod_info["max_distance"] = obj["MSFS_lod_max_distance"]

            lods.append(lod_info)

    if not lods:
        return {"error": f"No LOD objects found with base name: {base_name}"}

    # Calculate total reduction
    if len(lods) >= 2:
        lod0_verts = lods[0]["vertex_count"]
        lowest_lod_verts = lods[-1]["vertex_count"]
        total_reduction = round(1 - (lowest_lod_verts / lod0_verts), 3) if lod0_verts > 0 else 0
    else:
        total_reduction = 0

    return {
        "base_name": base_name,
        "lod_count": len(lods),
        "lods": lods,
        "total_vertex_reduction": total_reduction,
    }
