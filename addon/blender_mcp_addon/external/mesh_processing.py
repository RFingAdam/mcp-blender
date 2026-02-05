"""Mesh processing pipeline for AI-generated models.

This module provides tools for cleaning up, optimizing, and preparing
AI-generated meshes for use in Blender.
"""

from typing import Any

import bpy
import bmesh
from mathutils import Vector


def get_mesh_object(name: str) -> bpy.types.Object | None:
    """Get a mesh object by name.

    Args:
        name: Object name.

    Returns:
        Object or None if not found or not a mesh.
    """
    obj = bpy.data.objects.get(name)
    if obj and obj.type == "MESH":
        return obj
    return None


def cleanup_mesh(
    object_name: str,
    remove_doubles: bool = True,
    merge_distance: float = 0.0001,
    fix_normals: bool = True,
    remove_loose: bool = True,
    remove_degenerate: bool = True,
) -> dict[str, Any]:
    """Clean up a mesh by removing doubles, fixing normals, etc.

    Args:
        object_name: Name of the mesh object.
        remove_doubles: Remove duplicate vertices.
        merge_distance: Distance threshold for merging vertices.
        fix_normals: Recalculate normals to face outward.
        remove_loose: Remove loose vertices/edges.
        remove_degenerate: Remove degenerate geometry.

    Returns:
        Dictionary with cleanup results.
    """
    obj = get_mesh_object(object_name)
    if not obj:
        return {"success": False, "error": f"Mesh object not found: {object_name}"}

    # Get initial stats
    initial_verts = len(obj.data.vertices)
    initial_faces = len(obj.data.polygons)

    # Store current mode and active object
    original_mode = bpy.context.mode
    original_active = bpy.context.view_layer.objects.active

    try:
        # Select and activate the object
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # Enter edit mode
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")

        operations = []

        # Remove degenerate geometry first
        if remove_degenerate:
            bpy.ops.mesh.dissolve_degenerate(threshold=merge_distance)
            operations.append("dissolve_degenerate")

        # Remove doubles (merge by distance)
        if remove_doubles:
            bpy.ops.mesh.remove_doubles(threshold=merge_distance)
            operations.append("remove_doubles")

        # Fix normals (make consistent, pointing outward)
        if fix_normals:
            bpy.ops.mesh.normals_make_consistent(inside=False)
            operations.append("fix_normals")

        # Remove loose geometry
        if remove_loose:
            bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=False)
            operations.append("remove_loose")

        # Return to object mode
        bpy.ops.object.mode_set(mode="OBJECT")

        # Get final stats
        final_verts = len(obj.data.vertices)
        final_faces = len(obj.data.polygons)

        return {
            "success": True,
            "object": object_name,
            "operations": operations,
            "initial_vertices": initial_verts,
            "final_vertices": final_verts,
            "vertices_removed": initial_verts - final_verts,
            "initial_faces": initial_faces,
            "final_faces": final_faces,
            "faces_removed": initial_faces - final_faces,
        }

    except Exception as e:
        # Try to return to object mode on error
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        return {"success": False, "error": str(e)}

    finally:
        # Restore original state
        if original_active:
            bpy.context.view_layer.objects.active = original_active


def decimate_mesh(
    object_name: str,
    ratio: float = 0.5,
    method: str = "COLLAPSE",
    triangulate: bool = False,
    preserve_uvs: bool = True,
    vertex_group: str | None = None,
    invert_vertex_group: bool = False,
) -> dict[str, Any]:
    """Reduce polygon count of a mesh.

    Args:
        object_name: Name of the mesh object.
        ratio: Target ratio of faces to keep (0.0-1.0).
        method: Decimation method (COLLAPSE, UNSUBDIV, DISSOLVE).
        triangulate: Triangulate mesh before decimating.
        preserve_uvs: Try to preserve UV seams.
        vertex_group: Optional vertex group to influence decimation.
        invert_vertex_group: Invert vertex group influence.

    Returns:
        Dictionary with decimation results.
    """
    obj = get_mesh_object(object_name)
    if not obj:
        return {"success": False, "error": f"Mesh object not found: {object_name}"}

    if ratio < 0.0 or ratio > 1.0:
        return {"success": False, "error": "Ratio must be between 0.0 and 1.0"}

    valid_methods = ["COLLAPSE", "UNSUBDIV", "DISSOLVE"]
    method = method.upper()
    if method not in valid_methods:
        return {"success": False, "error": f"Invalid method: {method}. Use: {valid_methods}"}

    initial_faces = len(obj.data.polygons)
    initial_verts = len(obj.data.vertices)

    try:
        # Store current active object
        original_active = bpy.context.view_layer.objects.active
        bpy.context.view_layer.objects.active = obj

        # Triangulate if requested (improves results for COLLAPSE)
        if triangulate:
            tri_mod = obj.modifiers.new(name="Triangulate_Temp", type="TRIANGULATE")
            tri_mod.quad_method = "BEAUTY"
            bpy.ops.object.modifier_apply(modifier="Triangulate_Temp")

        # Add decimate modifier
        mod = obj.modifiers.new(name="Decimate_AI", type="DECIMATE")
        mod.decimate_type = method

        if method == "COLLAPSE":
            mod.ratio = ratio
            if preserve_uvs:
                mod.use_collapse_triangulate = False
        elif method == "UNSUBDIV":
            # Calculate iterations from ratio
            iterations = max(1, int(-1.44 * (ratio - 1)))  # Approximate conversion
            mod.iterations = iterations
        elif method == "DISSOLVE":
            mod.angle_limit = (1 - ratio) * 1.5708  # Map ratio to angle (0-90 degrees)

        # Set vertex group if specified
        if vertex_group and vertex_group in obj.vertex_groups:
            mod.vertex_group = vertex_group
            mod.invert_vertex_group = invert_vertex_group

        # Apply the modifier
        bpy.ops.object.modifier_apply(modifier="Decimate_AI")

        final_faces = len(obj.data.polygons)
        final_verts = len(obj.data.vertices)

        # Restore active object
        if original_active:
            bpy.context.view_layer.objects.active = original_active

        actual_ratio = final_faces / initial_faces if initial_faces > 0 else 1.0

        return {
            "success": True,
            "object": object_name,
            "method": method,
            "target_ratio": ratio,
            "actual_ratio": round(actual_ratio, 4),
            "initial_faces": initial_faces,
            "final_faces": final_faces,
            "faces_removed": initial_faces - final_faces,
            "initial_vertices": initial_verts,
            "final_vertices": final_verts,
            "reduction_percent": round((1 - actual_ratio) * 100, 1),
        }

    except Exception as e:
        # Try to remove modifier on error
        try:
            if "Decimate_AI" in obj.modifiers:
                obj.modifiers.remove(obj.modifiers["Decimate_AI"])
        except Exception:
            pass
        return {"success": False, "error": str(e)}


def remesh_object(
    object_name: str,
    method: str = "VOXEL",
    voxel_size: float = 0.05,
    octree_depth: int = 5,
    smooth_normals: bool = True,
    apply_smooth: bool = True,
    smooth_factor: float = 0.5,
    smooth_iterations: int = 2,
) -> dict[str, Any]:
    """Retopologize a mesh for better geometry flow.

    Args:
        object_name: Name of the mesh object.
        method: Remesh method (VOXEL, QUAD, SHARP, SMOOTH, BLOCKS).
        voxel_size: Voxel size for VOXEL method.
        octree_depth: Octree depth for other methods.
        smooth_normals: Smooth normals after remeshing.
        apply_smooth: Apply smoothing after remesh.
        smooth_factor: Smoothing factor.
        smooth_iterations: Number of smoothing iterations.

    Returns:
        Dictionary with remesh results.
    """
    obj = get_mesh_object(object_name)
    if not obj:
        return {"success": False, "error": f"Mesh object not found: {object_name}"}

    valid_methods = ["VOXEL", "QUAD", "SHARP", "SMOOTH", "BLOCKS"]
    method = method.upper()
    if method not in valid_methods:
        return {"success": False, "error": f"Invalid method: {method}. Use: {valid_methods}"}

    initial_faces = len(obj.data.polygons)
    initial_verts = len(obj.data.vertices)

    try:
        original_active = bpy.context.view_layer.objects.active
        bpy.context.view_layer.objects.active = obj

        # Add remesh modifier
        mod = obj.modifiers.new(name="Remesh_AI", type="REMESH")
        mod.mode = method

        if method == "VOXEL":
            mod.voxel_size = voxel_size
        else:
            mod.octree_depth = octree_depth

        if method == "SMOOTH":
            mod.use_smooth_shade = smooth_normals

        # Apply the modifier
        bpy.ops.object.modifier_apply(modifier="Remesh_AI")

        # Optional smoothing pass
        if apply_smooth:
            smooth_mod = obj.modifiers.new(name="Smooth_AI", type="SMOOTH")
            smooth_mod.factor = smooth_factor
            smooth_mod.iterations = smooth_iterations
            bpy.ops.object.modifier_apply(modifier="Smooth_AI")

        # Smooth normals
        if smooth_normals:
            bpy.ops.object.shade_smooth()

        final_faces = len(obj.data.polygons)
        final_verts = len(obj.data.vertices)

        if original_active:
            bpy.context.view_layer.objects.active = original_active

        return {
            "success": True,
            "object": object_name,
            "method": method,
            "voxel_size": voxel_size if method == "VOXEL" else None,
            "octree_depth": octree_depth if method != "VOXEL" else None,
            "initial_faces": initial_faces,
            "final_faces": final_faces,
            "initial_vertices": initial_verts,
            "final_vertices": final_verts,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def auto_uv_unwrap(
    object_name: str,
    method: str = "SMART",
    angle_limit: float = 66.0,
    island_margin: float = 0.02,
    area_weight: float = 0.0,
    correct_aspect: bool = True,
    scale_to_bounds: bool = True,
    uv_layer_name: str | None = None,
) -> dict[str, Any]:
    """Generate UV maps for a mesh.

    Args:
        object_name: Name of the mesh object.
        method: UV projection method (SMART, LIGHTMAP, CUBE, CYLINDER, SPHERE).
        angle_limit: Angle limit for smart project (degrees).
        island_margin: Margin between UV islands.
        area_weight: Area weight for smart project.
        correct_aspect: Correct for non-square textures.
        scale_to_bounds: Scale UVs to fit 0-1 space.
        uv_layer_name: Name for the new UV layer.

    Returns:
        Dictionary with UV results.
    """
    obj = get_mesh_object(object_name)
    if not obj:
        return {"success": False, "error": f"Mesh object not found: {object_name}"}

    valid_methods = ["SMART", "LIGHTMAP", "CUBE", "CYLINDER", "SPHERE", "PROJECT"]
    method = method.upper()
    if method not in valid_methods:
        return {"success": False, "error": f"Invalid method: {method}. Use: {valid_methods}"}

    try:
        original_active = bpy.context.view_layer.objects.active
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # Create or get UV layer
        if uv_layer_name:
            if uv_layer_name in obj.data.uv_layers:
                uv_layer = obj.data.uv_layers[uv_layer_name]
            else:
                uv_layer = obj.data.uv_layers.new(name=uv_layer_name)
        else:
            if not obj.data.uv_layers:
                uv_layer = obj.data.uv_layers.new(name="UVMap")
            else:
                uv_layer = obj.data.uv_layers.active

        # Set as active
        obj.data.uv_layers.active = uv_layer

        # Enter edit mode and select all
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")

        # Apply UV projection method
        import math

        if method == "SMART":
            bpy.ops.uv.smart_project(
                angle_limit=math.radians(angle_limit),
                island_margin=island_margin,
                area_weight=area_weight,
                correct_aspect=correct_aspect,
                scale_to_bounds=scale_to_bounds,
            )
        elif method == "LIGHTMAP":
            bpy.ops.uv.lightmap_pack(
                PREF_CONTEXT="ALL_FACES",
                PREF_PACK_IN_ONE=True,
                PREF_NEW_UVLAYER=False,
                PREF_APPLY_IMAGE=False,
                PREF_IMG_PX_SIZE=1024,
                PREF_BOX_DIV=12,
                PREF_MARGIN_DIV=island_margin,
            )
        elif method == "CUBE":
            bpy.ops.uv.cube_project(
                cube_size=1.0,
                correct_aspect=correct_aspect,
                scale_to_bounds=scale_to_bounds,
            )
        elif method == "CYLINDER":
            bpy.ops.uv.cylinder_project(
                direction="VIEW_ON_EQUATOR",
                align="POLAR_ZX",
                radius=1.0,
                correct_aspect=correct_aspect,
                scale_to_bounds=scale_to_bounds,
            )
        elif method == "SPHERE":
            bpy.ops.uv.sphere_project(
                direction="VIEW_ON_EQUATOR",
                align="POLAR_ZX",
                correct_aspect=correct_aspect,
                scale_to_bounds=scale_to_bounds,
            )
        elif method == "PROJECT":
            bpy.ops.uv.project_from_view(
                scale_to_bounds=scale_to_bounds,
                correct_aspect=correct_aspect,
            )

        # Return to object mode
        bpy.ops.object.mode_set(mode="OBJECT")

        if original_active:
            bpy.context.view_layer.objects.active = original_active

        return {
            "success": True,
            "object": object_name,
            "method": method,
            "uv_layer": uv_layer.name,
            "uv_layers": list(obj.data.uv_layers.keys()),
        }

    except Exception as e:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        return {"success": False, "error": str(e)}


def optimize_mesh(
    object_name: str,
    cleanup: bool = True,
    decimate: bool = True,
    decimate_ratio: float = 0.5,
    auto_uv: bool = True,
    smooth_normals: bool = True,
) -> dict[str, Any]:
    """Run full optimization pipeline on a mesh.

    Args:
        object_name: Name of the mesh object.
        cleanup: Run cleanup pass.
        decimate: Run decimation.
        decimate_ratio: Target face ratio for decimation.
        auto_uv: Generate UVs.
        smooth_normals: Smooth shade the result.

    Returns:
        Dictionary with full optimization results.
    """
    obj = get_mesh_object(object_name)
    if not obj:
        return {"success": False, "error": f"Mesh object not found: {object_name}"}

    results = {
        "success": True,
        "object": object_name,
        "steps": [],
    }

    initial_verts = len(obj.data.vertices)
    initial_faces = len(obj.data.polygons)

    # Step 1: Cleanup
    if cleanup:
        cleanup_result = cleanup_mesh(object_name)
        results["steps"].append({
            "step": "cleanup",
            "success": cleanup_result.get("success", False),
            "details": cleanup_result,
        })
        if not cleanup_result.get("success"):
            results["success"] = False
            results["error"] = f"Cleanup failed: {cleanup_result.get('error')}"
            return results

    # Step 2: Decimate
    if decimate:
        decimate_result = decimate_mesh(
            object_name,
            ratio=decimate_ratio,
            method="COLLAPSE",
            preserve_uvs=True,
        )
        results["steps"].append({
            "step": "decimate",
            "success": decimate_result.get("success", False),
            "details": decimate_result,
        })
        if not decimate_result.get("success"):
            results["success"] = False
            results["error"] = f"Decimation failed: {decimate_result.get('error')}"
            return results

    # Step 3: Auto UV
    if auto_uv:
        uv_result = auto_uv_unwrap(
            object_name,
            method="SMART",
            angle_limit=66.0,
            island_margin=0.02,
        )
        results["steps"].append({
            "step": "auto_uv",
            "success": uv_result.get("success", False),
            "details": uv_result,
        })
        if not uv_result.get("success"):
            # UV failure is non-critical
            pass

    # Step 4: Smooth normals
    if smooth_normals:
        try:
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.shade_smooth()
            results["steps"].append({
                "step": "smooth_normals",
                "success": True,
            })
        except Exception as e:
            results["steps"].append({
                "step": "smooth_normals",
                "success": False,
                "error": str(e),
            })

    # Final stats
    final_verts = len(obj.data.vertices)
    final_faces = len(obj.data.polygons)

    results["initial_vertices"] = initial_verts
    results["final_vertices"] = final_verts
    results["initial_faces"] = initial_faces
    results["final_faces"] = final_faces
    results["reduction_percent"] = round(
        (1 - final_faces / initial_faces) * 100 if initial_faces > 0 else 0, 1
    )

    return results


def fix_mesh_issues(
    object_name: str,
    fix_non_manifold: bool = True,
    fill_holes: bool = True,
    max_hole_edges: int = 12,
    fix_normals: bool = True,
    remove_interior_faces: bool = True,
) -> dict[str, Any]:
    """Fix common mesh issues.

    Args:
        object_name: Name of the mesh object.
        fix_non_manifold: Fix non-manifold geometry.
        fill_holes: Fill small holes.
        max_hole_edges: Maximum edges in holes to fill.
        fix_normals: Recalculate and make normals consistent.
        remove_interior_faces: Remove faces inside the mesh.

    Returns:
        Dictionary with fix results.
    """
    obj = get_mesh_object(object_name)
    if not obj:
        return {"success": False, "error": f"Mesh object not found: {object_name}"}

    fixes_applied = []

    try:
        original_active = bpy.context.view_layer.objects.active
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")

        # Fix non-manifold edges
        if fix_non_manifold:
            bpy.ops.mesh.select_non_manifold()
            # Get count of selected
            bpy.ops.object.mode_set(mode="OBJECT")
            non_manifold_count = len([v for v in obj.data.vertices if v.select])
            bpy.ops.object.mode_set(mode="EDIT")

            if non_manifold_count > 0:
                # Try to fix by merging close vertices
                bpy.ops.mesh.remove_doubles(threshold=0.0001)
                fixes_applied.append(f"non_manifold_vertices: {non_manifold_count}")

            bpy.ops.mesh.select_all(action="DESELECT")

        # Fill holes
        if fill_holes:
            bpy.ops.mesh.select_all(action="DESELECT")
            bpy.ops.mesh.select_non_manifold(
                extend=False,
                use_wire=False,
                use_boundary=True,
                use_multi_face=False,
                use_non_contiguous=False,
                use_verts=False,
            )
            # Check if boundary edges selected
            bpy.ops.object.mode_set(mode="OBJECT")
            boundary_count = len([e for e in obj.data.edges if e.select])
            bpy.ops.object.mode_set(mode="EDIT")

            if boundary_count > 0 and boundary_count <= max_hole_edges * 4:
                bpy.ops.mesh.fill_holes(sides=max_hole_edges)
                fixes_applied.append(f"holes_filled: boundary_edges={boundary_count}")

            bpy.ops.mesh.select_all(action="DESELECT")

        # Fix normals
        if fix_normals:
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.normals_make_consistent(inside=False)
            fixes_applied.append("normals_fixed")
            bpy.ops.mesh.select_all(action="DESELECT")

        # Remove interior faces (faces with no visible exterior)
        if remove_interior_faces:
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.select_interior_faces()
            bpy.ops.object.mode_set(mode="OBJECT")
            interior_count = len([f for f in obj.data.polygons if f.select])
            bpy.ops.object.mode_set(mode="EDIT")

            if interior_count > 0:
                bpy.ops.mesh.delete(type="FACE")
                fixes_applied.append(f"interior_faces_removed: {interior_count}")

        bpy.ops.object.mode_set(mode="OBJECT")

        if original_active:
            bpy.context.view_layer.objects.active = original_active

        return {
            "success": True,
            "object": object_name,
            "fixes_applied": fixes_applied,
            "final_vertices": len(obj.data.vertices),
            "final_faces": len(obj.data.polygons),
        }

    except Exception as e:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        return {"success": False, "error": str(e)}


def get_mesh_stats(object_name: str) -> dict[str, Any]:
    """Get detailed statistics about a mesh.

    Args:
        object_name: Name of the mesh object.

    Returns:
        Dictionary with mesh statistics.
    """
    obj = get_mesh_object(object_name)
    if not obj:
        return {"success": False, "error": f"Mesh object not found: {object_name}"}

    mesh = obj.data

    # Count geometry
    vertex_count = len(mesh.vertices)
    edge_count = len(mesh.edges)
    face_count = len(mesh.polygons)

    # Count triangles (faces may be quads or ngons)
    triangle_count = sum(len(f.vertices) - 2 for f in mesh.polygons)

    # Check for ngons and quads
    tris = sum(1 for f in mesh.polygons if len(f.vertices) == 3)
    quads = sum(1 for f in mesh.polygons if len(f.vertices) == 4)
    ngons = sum(1 for f in mesh.polygons if len(f.vertices) > 4)

    # UV layers
    uv_layers = list(mesh.uv_layers.keys())
    has_uvs = len(uv_layers) > 0

    # Materials
    materials = [slot.material.name if slot.material else None for slot in obj.material_slots]

    # Bounding box
    bbox = obj.bound_box
    dimensions = obj.dimensions[:]

    # Check for issues
    issues = []

    # Check for non-manifold geometry using bmesh
    bm = bmesh.new()
    bm.from_mesh(mesh)
    non_manifold_edges = [e for e in bm.edges if not e.is_manifold]
    if non_manifold_edges:
        issues.append(f"non_manifold_edges: {len(non_manifold_edges)}")

    loose_verts = [v for v in bm.verts if not v.link_edges]
    if loose_verts:
        issues.append(f"loose_vertices: {len(loose_verts)}")

    bm.free()

    return {
        "success": True,
        "object": object_name,
        "vertices": vertex_count,
        "edges": edge_count,
        "faces": face_count,
        "triangles": triangle_count,
        "face_breakdown": {
            "tris": tris,
            "quads": quads,
            "ngons": ngons,
        },
        "has_uvs": has_uvs,
        "uv_layers": uv_layers,
        "materials": materials,
        "dimensions": list(dimensions),
        "issues": issues,
        "is_clean": len(issues) == 0,
    }
