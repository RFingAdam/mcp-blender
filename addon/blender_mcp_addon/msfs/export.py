"""MSFS model export utilities."""

from pathlib import Path
from typing import Any

import bpy

# Default export settings for MSFS-compatible glTF
DEFAULT_EXPORT_SETTINGS = {
    "export_format": "GLB",
    "export_copyright": "",
    "export_image_format": "AUTO",
    "export_texture_dir": "",
    "export_keep_originals": False,
    "export_texcoords": True,
    "export_normals": True,
    "export_tangents": True,
    "export_materials": "EXPORT",
    "export_colors": True,
    "export_cameras": False,
    "export_lights": False,
    "export_extras": True,  # Required for MSFS custom properties
    "export_yup": True,
    "export_apply": False,
    "export_animations": True,
    "export_frame_range": False,
    "export_anim_single_armature": False,
    "export_skins": True,
    "export_morph": True,
    "export_morph_normal": True,
    "export_morph_tangent": False,
}


def export_msfs_model(
    filepath: str,
    objects: list[str] | None = None,
    include_lods: bool = True,
    include_collision: bool = True,
    include_animations: bool = True,
    export_format: str = "GLB",
) -> dict[str, Any]:
    """Export model(s) in MSFS-compatible glTF format.

    Args:
        filepath: Output file path (.glb or .gltf)
        objects: List of object names to export (None = selected or all)
        include_lods: Include LOD variants in export
        include_collision: Include collision meshes
        include_animations: Include animation data
        export_format: GLB (binary) or GLTF (separate files)

    Returns:
        Dictionary with export results
    """
    path = Path(filepath)

    # Ensure correct extension
    if export_format.upper() == "GLB" and path.suffix.lower() != ".glb":
        path = path.with_suffix(".glb")
    elif export_format.upper() == "GLTF" and path.suffix.lower() != ".gltf":
        path = path.with_suffix(".gltf")

    # Build list of objects to export
    export_objects = []

    if objects:
        for name in objects:
            obj = bpy.data.objects.get(name)
            if obj:
                export_objects.append(obj)

                # Include LODs if requested
                if include_lods:
                    base_name = name
                    for suffix in ["_LOD0", "_LOD1", "_LOD2", "_LOD3"]:
                        if name.endswith(suffix):
                            base_name = name[:-5]
                            break

                    for lod_level in range(4):
                        lod_name = f"{base_name}_LOD{lod_level}"
                        lod_obj = bpy.data.objects.get(lod_name)
                        if lod_obj and lod_obj not in export_objects:
                            export_objects.append(lod_obj)

                # Include collision meshes if requested
                if include_collision:
                    for child in obj.children:
                        if child.get("MSFS_collision") and child not in export_objects:
                            export_objects.append(child)
    else:
        # Use selected objects or all if none selected
        if bpy.context.selected_objects:
            export_objects = list(bpy.context.selected_objects)
        else:
            export_objects = [obj for obj in bpy.data.objects if obj.type == "MESH"]

    if not export_objects:
        return {"error": "No objects to export"}

    # Select objects for export
    bpy.ops.object.select_all(action="DESELECT")
    for obj in export_objects:
        obj.select_set(True)
        # Unhide temporarily for export
        was_hidden = obj.hide_viewport
        obj.hide_viewport = False
        obj["_temp_was_hidden"] = was_hidden

    # Build export settings
    settings = DEFAULT_EXPORT_SETTINGS.copy()
    settings["filepath"] = str(path)
    settings["export_format"] = export_format.upper()
    settings["use_selection"] = True
    settings["export_animations"] = include_animations

    # Export
    try:
        bpy.ops.export_scene.gltf(**settings)
    except Exception as e:
        # Restore hidden state
        for obj in export_objects:
            if "_temp_was_hidden" in obj:
                obj.hide_viewport = obj["_temp_was_hidden"]
                del obj["_temp_was_hidden"]
        return {"error": f"Export failed: {str(e)}"}

    # Restore hidden state
    for obj in export_objects:
        if "_temp_was_hidden" in obj:
            obj.hide_viewport = obj["_temp_was_hidden"]
            del obj["_temp_was_hidden"]

    # Collect export info
    exported_info = {
        "filepath": str(path),
        "format": export_format.upper(),
        "object_count": len(export_objects),
        "objects": [obj.name for obj in export_objects],
    }

    # Count LODs and collision meshes
    lod_count = sum(1 for obj in export_objects if "MSFS_lod_level" in obj)
    collision_count = sum(1 for obj in export_objects if obj.get("MSFS_collision"))

    if lod_count > 0:
        exported_info["lod_count"] = lod_count
    if collision_count > 0:
        exported_info["collision_count"] = collision_count

    return exported_info


def validate_for_msfs(object_name: str | None = None) -> dict[str, Any]:
    """Validate model(s) for MSFS compatibility.

    Checks for common issues that prevent proper MSFS import.

    Args:
        object_name: Specific object to validate (None = all selected or all)

    Returns:
        Dictionary with validation results
    """
    issues = []
    warnings = []
    info = []

    # Get objects to validate
    if object_name:
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"error": f"Object not found: {object_name}"}
        objects = [obj]
    elif bpy.context.selected_objects:
        objects = list(bpy.context.selected_objects)
    else:
        objects = [obj for obj in bpy.data.objects if obj.type == "MESH"]

    if not objects:
        return {"error": "No objects to validate"}

    for obj in objects:
        obj_prefix = f"[{obj.name}]"

        if obj.type != "MESH":
            continue

        mesh = obj.data

        # Check for ngons (faces with > 4 vertices)
        ngon_count = sum(1 for poly in mesh.polygons if len(poly.vertices) > 4)
        if ngon_count > 0:
            warnings.append(f"{obj_prefix} Has {ngon_count} ngons (may cause issues)")

        # Check for non-manifold geometry
        # This requires bmesh for proper check
        try:
            import bmesh
            bm = bmesh.new()
            bm.from_mesh(mesh)
            non_manifold_edges = [e for e in bm.edges if not e.is_manifold]
            if non_manifold_edges:
                warnings.append(
                    f"{obj_prefix} Has {len(non_manifold_edges)} non-manifold edges"
                )
            bm.free()
        except Exception:
            pass

        # Check for missing UVs
        if not mesh.uv_layers:
            issues.append(f"{obj_prefix} Missing UV map (required for textures)")

        # Check for missing materials
        if not mesh.materials or all(m is None for m in mesh.materials):
            warnings.append(f"{obj_prefix} No materials assigned")

        # Check scale
        if obj.scale != (1, 1, 1):
            scale_str = f"({obj.scale.x:.2f}, {obj.scale.y:.2f}, {obj.scale.z:.2f})"
            warnings.append(
                f"{obj_prefix} Non-applied scale {scale_str} - consider applying"
            )

        # Check rotation
        rotation = obj.rotation_euler
        if any(abs(r) > 0.001 for r in rotation):
            warnings.append(
                f"{obj_prefix} Has rotation - consider applying for correct orientation"
            )

        # Check for MSFS properties
        has_msfs_props = any(key.startswith("MSFS_") for key in obj.keys())
        if has_msfs_props:
            info.append(f"{obj_prefix} Has MSFS custom properties")

        # Check vertex count
        vert_count = len(mesh.vertices)
        if vert_count > 65535:
            warnings.append(
                f"{obj_prefix} High vertex count ({vert_count}) - consider LODs"
            )
        elif vert_count > 10000:
            info.append(f"{obj_prefix} Vertex count: {vert_count}")

    # Check materials
    material_issues = _validate_materials()
    issues.extend(material_issues.get("issues", []))
    warnings.extend(material_issues.get("warnings", []))

    # Check for LOD hierarchy
    lod_objects = [obj for obj in objects if "MSFS_lod_level" in obj]
    if lod_objects:
        info.append(f"Found {len(lod_objects)} LOD objects")

    # Check for collision meshes
    collision_objects = [obj for obj in bpy.data.objects if obj.get("MSFS_collision")]
    if collision_objects:
        info.append(f"Found {len(collision_objects)} collision meshes")

    result = {
        "validated_objects": len(objects),
        "valid": len(issues) == 0,
    }

    if issues:
        result["issues"] = issues
    if warnings:
        result["warnings"] = warnings
    if info:
        result["info"] = info

    return result


def _validate_materials() -> dict[str, Any]:
    """Validate materials for MSFS compatibility."""
    issues = []
    warnings = []

    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue

        mat_prefix = f"[Material: {mat.name}]"

        # Check for Principled BSDF
        principled = None
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                principled = node
                break

        if not principled:
            warnings.append(f"{mat_prefix} No Principled BSDF (may not export correctly)")
            continue

        # Check for textures larger than 4096
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                width, height = node.image.size
                if width > 4096 or height > 4096:
                    warnings.append(
                        f"{mat_prefix} Texture {node.image.name} is "
                        f"{width}x{height} (max recommended: 4096x4096)"
                    )

                # Check for non-power-of-2 dimensions
                if (width & (width - 1)) != 0 or (height & (height - 1)) != 0:
                    warnings.append(
                        f"{mat_prefix} Texture {node.image.name} is not power-of-2"
                    )

    return {"issues": issues, "warnings": warnings}


def get_export_settings() -> dict[str, Any]:
    """Get available export settings and their defaults.

    Returns:
        Dictionary with export settings info
    """
    return {
        "formats": ["GLB", "GLTF"],
        "default_format": "GLB",
        "default_settings": DEFAULT_EXPORT_SETTINGS,
        "msfs_recommendations": {
            "format": "GLB",
            "export_extras": True,
            "export_tangents": True,
            "export_yup": True,
            "max_texture_size": 4096,
            "recommended_lod_count": 4,
            "collision_simplify_ratio": 0.3,
        },
    }


def batch_export_lods(
    base_name: str,
    output_dir: str,
    separate_files: bool = False,
) -> dict[str, Any]:
    """Export LOD hierarchy with proper MSFS structure.

    Args:
        base_name: Base name of the LOD hierarchy
        output_dir: Output directory path
        separate_files: Export each LOD as separate file

    Returns:
        Dictionary with export results
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Find all LOD objects
    lod_objects = []
    for lod_level in range(4):
        lod_name = f"{base_name}_LOD{lod_level}"
        obj = bpy.data.objects.get(lod_name)
        if obj:
            lod_objects.append((lod_level, obj))

    if not lod_objects:
        return {"error": f"No LOD objects found for base name: {base_name}"}

    exported = []

    if separate_files:
        # Export each LOD as separate file
        for lod_level, obj in lod_objects:
            filepath = output_path / f"{base_name}_LOD{lod_level}.glb"
            result = export_msfs_model(
                str(filepath),
                objects=[obj.name],
                include_lods=False,
                include_collision=True,
            )
            if "error" not in result:
                exported.append({
                    "lod_level": lod_level,
                    "filepath": str(filepath),
                    "vertex_count": len(obj.data.vertices),
                })
    else:
        # Export all LODs in single file
        filepath = output_path / f"{base_name}.glb"
        object_names = [obj.name for _, obj in lod_objects]

        # Include collision meshes
        for _, obj in lod_objects:
            for child in obj.children:
                if child.get("MSFS_collision"):
                    object_names.append(child.name)

        result = export_msfs_model(
            str(filepath),
            objects=object_names,
            include_lods=False,  # Already included
            include_collision=False,  # Already included
        )

        if "error" not in result:
            exported.append({
                "filepath": str(filepath),
                "lod_count": len(lod_objects),
                "objects": object_names,
            })

    return {
        "base_name": base_name,
        "output_dir": str(output_path),
        "separate_files": separate_files,
        "exported": exported,
    }
