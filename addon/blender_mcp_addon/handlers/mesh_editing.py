"""Mesh editing command handlers."""

import math
import os
import tempfile

import bpy

from .. import compat
from ..utils import (
    ensure_object_selected,
    get_object_or_error,
)
from ..validation import (
    ValidationError,
    require_param,
    validate_enum,
    validate_filepath,
    validate_vector3,
)


class MeshEditingHandlersMixin:
    """Mixin for mesh editing handlers."""

    def _handle_boolean_op(self, params: dict) -> dict:
        """Perform a boolean operation between two objects."""
        target_name = require_param(params, "target", str)
        tool_name = require_param(params, "tool", str)
        operation = validate_enum(
            require_param(params, "operation", str),
            "operation",
            ["UNION", "DIFFERENCE", "INTERSECT"],
        )
        solver = validate_enum(
            params.get("solver", "EXACT"),
            "solver",
            ["FAST", "EXACT"],
        )
        apply_mod = params.get("apply", True)
        hide_tool = params.get("hide_tool", True)

        target_obj = get_object_or_error(target_name)
        tool_obj = get_object_or_error(tool_name)

        # Add boolean modifier
        mod_name = f"Boolean_{operation}"
        mod = target_obj.modifiers.new(name=mod_name, type="BOOLEAN")
        mod.operation = operation
        mod.solver = solver
        mod.object = tool_obj

        result_info = {
            "success": True,
            "target": target_name,
            "tool": tool_name,
            "operation": operation,
            "solver": solver,
            "modifier_name": mod_name,
            "applied": False,
            "tool_hidden": False,
        }

        # Apply modifier if requested
        if apply_mod:
            ctx = bpy.context.copy()
            ctx["object"] = target_obj
            with bpy.context.temp_override(**ctx):
                bpy.ops.object.modifier_apply(modifier=mod_name)
            result_info["applied"] = True

        # Hide tool object if requested
        if hide_tool:
            tool_obj.hide_set(True)
            tool_obj.hide_render = True
            result_info["tool_hidden"] = True

        return result_info

    # ========== Curve Tools Handlers ==========


    def _handle_curve_create(self, params: dict) -> dict:
        """Create a Bezier, NURBS, or Poly curve from control points."""
        name = params.get("name", "Curve")
        curve_type = validate_enum(
            params.get("type", "BEZIER"),
            "type",
            ["BEZIER", "NURBS", "POLY"],
        )
        points = require_param(params, "points", list)
        cyclic = params.get("cyclic", False)
        resolution = params.get("resolution", 12)
        location = params.get("location", [0, 0, 0])
        handles = params.get("handles")

        if len(points) < 2:
            raise ValidationError("At least 2 control points are required")

        # Create the curve data
        curve_data = bpy.data.curves.new(name=name, type="CURVE")
        curve_data.dimensions = "3D"
        curve_data.resolution_u = resolution

        # Add a spline
        if curve_type == "BEZIER":
            spline = curve_data.splines.new("BEZIER")
            spline.bezier_points.add(len(points) - 1)  # first point already exists
            for i, pt in enumerate(points):
                bp = spline.bezier_points[i]
                bp.co = (pt[0], pt[1], pt[2] if len(pt) > 2 else 0)
                # Set handle types
                if handles and i < len(handles):
                    h = handles[i]
                    if isinstance(h, str):
                        bp.handle_left_type = h
                        bp.handle_right_type = h
                    elif isinstance(h, dict):
                        bp.handle_left_type = h.get("type", "AUTO")
                        bp.handle_right_type = h.get("type", "AUTO")
                        if "left" in h:
                            bp.handle_left = tuple(h["left"])
                        if "right" in h:
                            bp.handle_right = tuple(h["right"])
                else:
                    bp.handle_left_type = "AUTO"
                    bp.handle_right_type = "AUTO"
        elif curve_type == "NURBS":
            spline = curve_data.splines.new("NURBS")
            spline.points.add(len(points) - 1)
            for i, pt in enumerate(points):
                z = pt[2] if len(pt) > 2 else 0
                w = pt[3] if len(pt) > 3 else 1.0
                spline.points[i].co = (pt[0], pt[1], z, w)
            spline.use_endpoint_u = True
        else:  # POLY
            spline = curve_data.splines.new("POLY")
            spline.points.add(len(points) - 1)
            for i, pt in enumerate(points):
                z = pt[2] if len(pt) > 2 else 0
                spline.points[i].co = (pt[0], pt[1], z, 1.0)

        spline.use_cyclic_u = cyclic

        # Create the object and link to scene
        curve_obj = bpy.data.objects.new(name, curve_data)
        curve_obj.location = tuple(location)
        bpy.context.collection.objects.link(curve_obj)

        return {
            "success": True,
            "name": curve_obj.name,
            "type": curve_type,
            "point_count": len(points),
            "cyclic": cyclic,
            "resolution": resolution,
        }


    def _handle_curve_to_mesh(self, params: dict) -> dict:
        """Convert a curve to mesh, optionally with bevel/extrusion."""
        curve_name = require_param(params, "curve_name", str)
        bevel_depth = params.get("bevel_depth", 0)
        bevel_resolution = params.get("bevel_resolution", 4)
        extrude = params.get("extrude", 0)
        fill_type = validate_enum(
            params.get("fill_type", "FULL"),
            "fill_type",
            ["FULL", "BACK", "FRONT", "HALF", "NONE"],
        )
        twist_method = params.get("twist_method", "MINIMUM")
        apply_as_mesh = params.get("apply_as_mesh", True)

        curve_obj = get_object_or_error(curve_name)
        if curve_obj.type != "CURVE":
            raise ValidationError(f"Object '{curve_name}' is not a curve (type: {curve_obj.type})")

        curve_data = curve_obj.data
        curve_data.bevel_depth = bevel_depth
        curve_data.bevel_resolution = bevel_resolution
        curve_data.extrude = extrude
        curve_data.fill_mode = fill_type
        curve_data.twist_mode = twist_method

        result_info = {
            "success": True,
            "name": curve_name,
            "bevel_depth": bevel_depth,
            "extrude": extrude,
            "converted_to_mesh": False,
        }

        if apply_as_mesh:
            ensure_object_selected(curve_obj)
            bpy.ops.object.convert(target="MESH")
            result_info["converted_to_mesh"] = True
            result_info["vertex_count"] = len(curve_obj.data.vertices)
            result_info["face_count"] = len(curve_obj.data.polygons)

        return result_info


    def _handle_curve_from_mesh_edge(self, params: dict) -> dict:
        """Create a curve from mesh edge indices."""

        object_name = require_param(params, "object_name", str)
        edge_indices = require_param(params, "edge_indices", list)
        curve_type = validate_enum(
            params.get("curve_type", "POLY"),
            "curve_type",
            ["BEZIER", "NURBS", "POLY"],
        )

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        # Get edge vertex positions from the mesh
        mesh = obj.data
        # Build ordered vertex chain from edges
        edge_verts = {}
        for idx in edge_indices:
            if idx >= len(mesh.edges):
                raise ValidationError(f"Edge index {idx} out of range (mesh has {len(mesh.edges)} edges)")
            e = mesh.edges[idx]
            v1, v2 = e.vertices[0], e.vertices[1]
            edge_verts.setdefault(v1, []).append(v2)
            edge_verts.setdefault(v2, []).append(v1)

        # Walk the edge chain to get ordered vertices
        # Find a start vertex (one with only one connection = endpoint, or any if cyclic)
        start = None
        for v, neighbors in edge_verts.items():
            if len(neighbors) == 1:
                start = v
                break
        if start is None:
            start = next(iter(edge_verts))  # cyclic - pick any

        ordered = [start]
        visited = {start}
        current = start
        while True:
            neighbors = edge_verts.get(current, [])
            next_v = None
            for n in neighbors:
                if n not in visited:
                    next_v = n
                    break
            if next_v is None:
                break
            ordered.append(next_v)
            visited.add(next_v)
            current = next_v

        # Get world-space positions
        world_matrix = obj.matrix_world
        points = []
        for vi in ordered:
            co = world_matrix @ mesh.vertices[vi].co
            points.append((co.x, co.y, co.z))

        # Create the curve
        curve_data = bpy.data.curves.new(name=f"{object_name}_curve", type="CURVE")
        curve_data.dimensions = "3D"

        if curve_type == "BEZIER":
            spline = curve_data.splines.new("BEZIER")
            spline.bezier_points.add(len(points) - 1)
            for i, pt in enumerate(points):
                spline.bezier_points[i].co = pt
                spline.bezier_points[i].handle_left_type = "AUTO"
                spline.bezier_points[i].handle_right_type = "AUTO"
        elif curve_type == "NURBS":
            spline = curve_data.splines.new("NURBS")
            spline.points.add(len(points) - 1)
            for i, pt in enumerate(points):
                spline.points[i].co = (pt[0], pt[1], pt[2], 1.0)
            spline.use_endpoint_u = True
        else:  # POLY
            spline = curve_data.splines.new("POLY")
            spline.points.add(len(points) - 1)
            for i, pt in enumerate(points):
                spline.points[i].co = (pt[0], pt[1], pt[2], 1.0)

        # Check if cyclic (start connects to end)
        if len(ordered) > 2:
            end_neighbors = edge_verts.get(ordered[-1], [])
            if ordered[0] in end_neighbors:
                spline.use_cyclic_u = True

        curve_obj = bpy.data.objects.new(f"{object_name}_curve", curve_data)
        bpy.context.collection.objects.link(curve_obj)

        return {
            "success": True,
            "name": curve_obj.name,
            "type": curve_type,
            "point_count": len(points),
            "source_edges": len(edge_indices),
            "cyclic": spline.use_cyclic_u,
        }

    # ========== Edit Mode Mesh Operations Handlers ==========


    def _handle_mesh_extrude(self, params: dict) -> dict:
        """Extrude faces, edges, or vertices along an offset vector."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        mode = validate_enum(
            params.get("mode", "FACES"),
            "mode",
            ["FACES", "EDGES", "VERTICES", "REGION"],
        )
        indices = require_param(params, "indices", list)
        offset = validate_vector3(require_param(params, "offset", list), "offset")
        individual = params.get("individual", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        from mathutils import Vector

        offset_vec = Vector(offset)
        new_geom_count = 0

        if mode in ("FACES", "REGION"):
            faces = []
            for i in indices:
                if i >= len(bm.faces):
                    bm.free()
                    raise ValidationError(f"Face index {i} out of range (mesh has {len(bm.faces)} faces)")
                faces.append(bm.faces[i])

            if individual and mode == "FACES":
                result = bmesh.ops.extrude_discrete_faces(bm, faces=faces)
                new_faces = [f for f in result["faces"]]
                for f in new_faces:
                    bmesh.ops.translate(bm, verts=f.verts, vec=offset_vec)
                new_geom_count = len(new_faces)
            else:
                result = bmesh.ops.extrude_face_region(bm, geom=faces)
                new_verts = [v for v in result["geom"] if isinstance(v, bmesh.types.BMVert)]
                bmesh.ops.translate(bm, verts=new_verts, vec=offset_vec)
                new_geom_count = len(new_verts)

        elif mode == "EDGES":
            edges = []
            for i in indices:
                if i >= len(bm.edges):
                    bm.free()
                    raise ValidationError(f"Edge index {i} out of range (mesh has {len(bm.edges)} edges)")
                edges.append(bm.edges[i])

            result = bmesh.ops.extrude_edge_only(bm, edges=edges)
            new_verts = [v for v in result["geom"] if isinstance(v, bmesh.types.BMVert)]
            bmesh.ops.translate(bm, verts=new_verts, vec=offset_vec)
            new_geom_count = len(new_verts)

        elif mode == "VERTICES":
            verts = []
            for i in indices:
                if i >= len(bm.verts):
                    bm.free()
                    raise ValidationError(f"Vertex index {i} out of range (mesh has {len(bm.verts)} verts)")
                verts.append(bm.verts[i])

            result = bmesh.ops.extrude_vert_indiv(bm, verts=verts)
            new_verts = [v for v in result["verts"]]
            bmesh.ops.translate(bm, verts=new_verts, vec=offset_vec)
            new_geom_count = len(new_verts)

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "mode": mode,
            "extruded_count": len(indices),
            "new_geometry_count": new_geom_count,
            "offset": list(offset),
        }


    def _handle_mesh_inset(self, params: dict) -> dict:
        """Inset faces to create border loops."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        face_indices = require_param(params, "face_indices", list)
        thickness = params.get("thickness", 0.1)
        depth = params.get("depth", 0.0)
        use_even_offset = params.get("use_even_offset", True)
        use_relative_offset = params.get("use_relative_offset", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()

        faces = []
        for i in face_indices:
            if i >= len(bm.faces):
                bm.free()
                raise ValidationError(f"Face index {i} out of range (mesh has {len(bm.faces)} faces)")
            faces.append(bm.faces[i])

        bmesh.ops.inset_region(
            bm,
            faces=faces,
            thickness=thickness,
            depth=depth,
            use_even_offset=use_even_offset,
            use_relative_offset=use_relative_offset,
        )

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "inset_face_count": len(face_indices),
            "thickness": thickness,
            "depth": depth,
        }


    def _handle_mesh_bevel(self, params: dict) -> dict:
        """Bevel edges or vertices for smooth transitions."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        edge_indices = params.get("edge_indices")
        width = params.get("width", 0.1)
        segments = params.get("segments", 1)
        profile = params.get("profile", 0.5)
        clamp_overlap = params.get("clamp_overlap", True)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        if edge_indices is not None:
            edges = []
            for i in edge_indices:
                if i >= len(bm.edges):
                    bm.free()
                    raise ValidationError(f"Edge index {i} out of range (mesh has {len(bm.edges)} edges)")
                edges.append(bm.edges[i])
        else:
            # Bevel all sharp edges (non-smooth)
            edges = [e for e in bm.edges if not e.smooth]
            if not edges:
                # If no sharp edges, bevel all edges
                edges = list(bm.edges)

        verts = set()
        for e in edges:
            verts.update(e.verts)

        bmesh.ops.bevel(
            bm,
            geom=edges,
            offset=width,
            segments=segments,
            profile=profile,
            affect="EDGES",
            clamp_overlap=clamp_overlap,
        )

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "beveled_edge_count": len(edges),
            "width": width,
            "segments": segments,
            "profile": profile,
        }


    def _handle_mesh_loop_cut(self, params: dict) -> dict:
        """Add edge loops to a mesh via loop cut."""
        object_name = require_param(params, "object_name", str)
        edge_index = require_param(params, "edge_index", int)
        cuts = params.get("cuts", 1)
        smoothness = params.get("smoothness", 0.0)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        mesh = obj.data
        if edge_index >= len(mesh.edges):
            raise ValidationError(f"Edge index {edge_index} out of range (mesh has {len(mesh.edges)} edges)")

        # Use operator for loop cut - requires specific context
        ensure_object_selected(obj)
        bpy.context.view_layer.objects.active = obj

        # Enter edit mode
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")

        # Use loopcut operator
        bpy.ops.mesh.loopcut_slide(
            MESH_OT_loopcut={
                "number_cuts": cuts,
                "smoothness": smoothness,
                "falloff": "INVERSE_SQUARE",
                "object_index": 0,
                "edge_index": edge_index,
            },
            TRANSFORM_OT_edge_slide={
                "value": 0.0,  # centered
                "single_side": False,
                "correct_uv": True,
            },
        )

        bpy.ops.object.mode_set(mode="OBJECT")

        new_edge_count = len(mesh.edges)

        return {
            "success": True,
            "object": object_name,
            "reference_edge": edge_index,
            "cuts": cuts,
            "total_edges": new_edge_count,
        }

    # ========== Selection & Query Tools ==========


    def _handle_mesh_select(self, params: dict) -> dict:
        """Multi-criteria mesh selection engine."""
        import bmesh
        from mathutils import Vector

        object_name = require_param(params, "object_name", str)
        mode = validate_enum(params.get("mode", "FACE"), "mode", ["VERT", "EDGE", "FACE"])
        action = validate_enum(
            params.get("action", "SET"),
            "action",
            ["SET", "ADD", "SUBTRACT", "INVERT", "SELECT_ALL", "DESELECT_ALL"],
        )

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        # Determine element collection based on mode
        if mode == "VERT":
            elements = bm.verts
        elif mode == "EDGE":
            elements = bm.edges
        else:
            elements = bm.faces

        # Start with action
        if action == "DESELECT_ALL":
            for e in elements:
                e.select = False
            bm.to_mesh(obj.data)
            bm.free()
            obj.data.update()
            return {"success": True, "object": object_name, "selected_indices": [], "count": 0, "total": len(elements)}

        if action == "SELECT_ALL":
            for e in elements:
                e.select = True
            selected = list(range(len(elements)))
            bm.to_mesh(obj.data)
            bm.free()
            obj.data.update()
            return {"success": True, "object": object_name, "selected_indices": selected, "count": len(selected), "total": len(elements)}

        if action == "INVERT":
            for e in elements:
                e.select = not e.select
            selected = [i for i, e in enumerate(elements) if e.select]
            bm.to_mesh(obj.data)
            bm.free()
            obj.data.update()
            return {"success": True, "object": object_name, "selected_indices": selected, "count": len(selected), "total": len(elements)}

        # Build candidate set from criteria
        indices = params.get("indices")
        position_min = params.get("position_min")
        position_max = params.get("position_max")
        normal_direction = params.get("normal_direction")
        normal_threshold = params.get("normal_threshold", 0.5)
        material_index = params.get("material_index")
        edge_angle_min = params.get("edge_angle_min")
        edge_angle_max = params.get("edge_angle_max")
        face_area_min = params.get("face_area_min")
        face_area_max = params.get("face_area_max")
        linked = params.get("linked", False)
        grow = int(params.get("grow", 0))
        shrink = int(params.get("shrink", 0))

        candidates = set()

        if indices is not None:
            for i in indices:
                i = int(i)
                if 0 <= i < len(elements):
                    candidates.add(i)

        # Position filter
        if position_min is not None or position_max is not None:
            p_min = Vector(position_min) if position_min else Vector((-1e10, -1e10, -1e10))
            p_max = Vector(position_max) if position_max else Vector((1e10, 1e10, 1e10))
            world_matrix = obj.matrix_world
            for i, elem in enumerate(elements):
                if mode == "VERT":
                    co = world_matrix @ elem.co
                elif mode == "EDGE":
                    co = world_matrix @ ((elem.verts[0].co + elem.verts[1].co) / 2)
                else:
                    co = world_matrix @ elem.calc_center_median()
                if p_min.x <= co.x <= p_max.x and p_min.y <= co.y <= p_max.y and p_min.z <= co.z <= p_max.z:
                    candidates.add(i)

        # Normal direction filter (FACE mode)
        if normal_direction is not None and mode == "FACE":
            nd = Vector(normal_direction).normalized()
            for i, face in enumerate(bm.faces):
                if face.normal.dot(nd) >= normal_threshold:
                    candidates.add(i)

        # Material index filter (FACE mode)
        if material_index is not None and mode == "FACE":
            mat_idx = int(material_index)
            for i, face in enumerate(bm.faces):
                if face.material_index == mat_idx:
                    candidates.add(i)

        # Edge angle filter (EDGE mode)
        if (edge_angle_min is not None or edge_angle_max is not None) and mode == "EDGE":
            a_min = math.radians(edge_angle_min) if edge_angle_min is not None else 0
            a_max = math.radians(edge_angle_max) if edge_angle_max is not None else math.pi
            for i, edge in enumerate(bm.edges):
                if len(edge.link_faces) == 2:
                    angle = edge.calc_face_angle()
                    if a_min <= angle <= a_max:
                        candidates.add(i)

        # Face area filter (FACE mode)
        if (face_area_min is not None or face_area_max is not None) and mode == "FACE":
            fa_min = face_area_min if face_area_min is not None else 0
            fa_max = face_area_max if face_area_max is not None else 1e10
            for i, face in enumerate(bm.faces):
                area = face.calc_area()
                if fa_min <= area <= fa_max:
                    candidates.add(i)

        # If no criteria specified at all, select nothing
        if (indices is None and position_min is None and position_max is None
                and normal_direction is None and material_index is None
                and edge_angle_min is None and edge_angle_max is None
                and face_area_min is None and face_area_max is None):
            candidates = set()

        # Apply action
        if action == "SET":
            for e in elements:
                e.select = False
            for i in candidates:
                elements[i].select = True
        elif action == "ADD":
            for i in candidates:
                elements[i].select = True
        elif action == "SUBTRACT":
            for i in candidates:
                elements[i].select = False

        # Linked expansion
        if linked and mode == "FACE":
            visited = set()
            queue = [i for i in range(len(bm.faces)) if bm.faces[i].select]
            visited.update(queue)
            while queue:
                fi = queue.pop()
                face = bm.faces[fi]
                for edge in face.edges:
                    for lf in edge.link_faces:
                        idx = lf.index
                        if idx not in visited:
                            visited.add(idx)
                            lf.select = True
                            queue.append(idx)

        # Grow/shrink
        for _ in range(grow):
            if mode == "FACE":
                to_select = set()
                for f in bm.faces:
                    if f.select:
                        for e in f.edges:
                            for lf in e.link_faces:
                                to_select.add(lf.index)
                for i in to_select:
                    bm.faces[i].select = True
            elif mode == "VERT":
                to_select = set()
                for v in bm.verts:
                    if v.select:
                        for e in v.link_edges:
                            to_select.add(e.other_vert(v).index)
                for i in to_select:
                    bm.verts[i].select = True

        for _ in range(shrink):
            if mode == "FACE":
                to_deselect = set()
                for f in bm.faces:
                    if f.select:
                        for e in f.edges:
                            if any(not lf.select for lf in e.link_faces if lf != f):
                                to_deselect.add(f.index)
                                break
                            if len(e.link_faces) == 1:
                                to_deselect.add(f.index)
                                break
                for i in to_deselect:
                    bm.faces[i].select = False

        selected = [i for i, e in enumerate(elements) if e.select]

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "mode": mode,
            "action": action,
            "selected_indices": selected,
            "count": len(selected),
            "total": len(elements),
        }


    def _handle_mesh_select_trait(self, params: dict) -> dict:
        """Select mesh elements by geometric trait."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        trait = require_param(params, "trait", str)
        validate_enum(trait, "trait", ["NON_MANIFOLD", "BOUNDARY", "LOOSE", "INTERIOR_FACES", "FACE_SIDES", "UNGROUPED", "NON_PLANAR"])
        extend = params.get("extend", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        if not extend:
            for v in bm.verts:
                v.select = False
            for e in bm.edges:
                e.select = False
            for f in bm.faces:
                f.select = False

        selected_indices = []
        element_type = "edges"

        if trait == "NON_MANIFOLD":
            for e in bm.edges:
                if not e.is_manifold:
                    e.select = True
                    selected_indices.append(e.index)

        elif trait == "BOUNDARY":
            for e in bm.edges:
                if e.is_boundary:
                    e.select = True
                    selected_indices.append(e.index)

        elif trait == "LOOSE":
            element_type = "verts"
            for v in bm.verts:
                if not v.link_edges:
                    v.select = True
                    selected_indices.append(v.index)
            for e in bm.edges:
                if not e.link_faces:
                    e.select = True

        elif trait == "INTERIOR_FACES":
            element_type = "faces"
            for f in bm.faces:
                # Interior face = all edges are shared with at least one other face
                # (no boundary edges)
                if all(len(e.link_faces) >= 2 for e in f.edges):
                    f.select = True
                    selected_indices.append(f.index)

        elif trait == "FACE_SIDES":
            element_type = "faces"
            face_sides = int(params.get("face_sides", 3))
            for f in bm.faces:
                if len(f.verts) == face_sides:
                    f.select = True
                    selected_indices.append(f.index)

        elif trait == "UNGROUPED":
            element_type = "verts"
            deform_layer = bm.verts.layers.deform.active
            for v in bm.verts:
                if deform_layer is None or not v[deform_layer]:
                    v.select = True
                    selected_indices.append(v.index)

        elif trait == "NON_PLANAR":
            element_type = "faces"
            threshold = params.get("non_planar_threshold", 0.01)
            for f in bm.faces:
                if len(f.verts) > 3:
                    normal = f.normal
                    center = f.calc_center_median()
                    max_dev = 0
                    for v in f.verts:
                        dev = abs((v.co - center).dot(normal))
                        max_dev = max(max_dev, dev)
                    if max_dev > threshold:
                        f.select = True
                        selected_indices.append(f.index)

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "trait": trait,
            "element_type": element_type,
            "selected_indices": selected_indices,
            "count": len(selected_indices),
        }


    def _handle_mesh_select_linked_flat(self, params: dict) -> dict:
        """Flood-select connected coplanar faces from a seed face."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        face_index = int(require_param(params, "face_index", (int, float)))
        angle_threshold = math.radians(params.get("angle_threshold", 15.0))

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()

        if face_index >= len(bm.faces):
            bm.free()
            raise ValidationError(f"Face index {face_index} out of range (mesh has {len(bm.faces)} faces)")

        # BFS from seed face
        for f in bm.faces:
            f.select = False

        seed = bm.faces[face_index]
        seed.select = True
        queue = [seed]
        visited = {face_index}

        while queue:
            current = queue.pop(0)
            for edge in current.edges:
                for neighbor in edge.link_faces:
                    if neighbor.index not in visited:
                        angle = current.normal.angle(neighbor.normal)
                        if angle <= angle_threshold:
                            visited.add(neighbor.index)
                            neighbor.select = True
                            queue.append(neighbor)

        selected = sorted(visited)

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "seed_face": face_index,
            "angle_threshold_degrees": math.degrees(angle_threshold),
            "selected_indices": selected,
            "count": len(selected),
        }


    def _handle_mesh_select_shortest_path(self, params: dict) -> dict:
        """Select shortest path between two mesh elements."""
        object_name = require_param(params, "object_name", str)
        mode = validate_enum(params.get("mode", "EDGE"), "mode", ["VERT", "EDGE"])
        index_a = int(require_param(params, "index_a", (int, float)))
        index_b = int(require_param(params, "index_b", (int, float)))

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        ensure_object_selected(obj)
        bpy.context.view_layer.objects.active = obj

        mesh = obj.data
        if mode == "EDGE":
            if index_a >= len(mesh.edges) or index_b >= len(mesh.edges):
                raise ValidationError("Edge index out of range")
        else:
            if index_a >= len(mesh.vertices) or index_b >= len(mesh.vertices):
                raise ValidationError("Vertex index out of range")

        bpy.ops.object.mode_set(mode="EDIT")

        if mode == "EDGE":
            bpy.context.tool_settings.mesh_select_mode = (False, True, False)
        else:
            bpy.context.tool_settings.mesh_select_mode = (True, False, False)

        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")

        if mode == "EDGE":
            mesh.edges[index_a].select = True
            mesh.edges[index_b].select = True
        else:
            mesh.vertices[index_a].select = True
            mesh.vertices[index_b].select = True

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.shortest_path_select()
        bpy.ops.object.mode_set(mode="OBJECT")

        if mode == "EDGE":
            selected = [e.index for e in mesh.edges if e.select]
        else:
            selected = [v.index for v in mesh.vertices if v.select]

        return {
            "success": True,
            "object": object_name,
            "mode": mode,
            "from": index_a,
            "to": index_b,
            "selected_indices": selected,
            "count": len(selected),
        }


    def _handle_mesh_get_selection(self, params: dict) -> dict:
        """Query current mesh selection state."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        mode = validate_enum(params.get("mode", "FACE"), "mode", ["VERT", "EDGE", "FACE"])

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        if mode == "VERT":
            selected = [v.index for v in bm.verts if v.select]
            total = len(bm.verts)
        elif mode == "EDGE":
            selected = [e.index for e in bm.edges if e.select]
            total = len(bm.edges)
        else:
            selected = [f.index for f in bm.faces if f.select]
            total = len(bm.faces)

        bm.free()

        return {
            "success": True,
            "object": object_name,
            "mode": mode,
            "selected_indices": selected,
            "count": len(selected),
            "total": total,
        }


    def _handle_mesh_select_edge_loops(self, params: dict) -> dict:
        """Select complete edge loops or rings through a given edge."""
        object_name = require_param(params, "object_name", str)
        edge_index = int(require_param(params, "edge_index", (int, float)))
        ring = params.get("ring", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        mesh = obj.data
        if edge_index >= len(mesh.edges):
            raise ValidationError(f"Edge index {edge_index} out of range (mesh has {len(mesh.edges)} edges)")

        ensure_object_selected(obj)
        bpy.context.view_layer.objects.active = obj

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, True, False)
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")

        mesh.edges[edge_index].select = True

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.loop_multi_select(ring=ring)
        bpy.ops.object.mode_set(mode="OBJECT")

        selected = [e.index for e in mesh.edges if e.select]

        return {
            "success": True,
            "object": object_name,
            "seed_edge": edge_index,
            "ring": ring,
            "selected_indices": selected,
            "count": len(selected),
        }

    # ========== Shading & Normal Control ==========


    def _handle_shade_smooth(self, params: dict) -> dict:
        """Set smooth, flat, or auto-smooth shading."""
        object_name = require_param(params, "object_name", str)
        shade_type = validate_enum(params.get("shade_type", "AUTO"), "shade_type", ["SMOOTH", "FLAT", "AUTO"])
        auto_smooth_angle = math.radians(params.get("auto_smooth_angle", 30.0))

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        ensure_object_selected(obj)
        bpy.context.view_layer.objects.active = obj

        if shade_type == "FLAT":
            bpy.ops.object.shade_flat()
        elif shade_type == "SMOOTH":
            bpy.ops.object.shade_smooth()
        elif shade_type == "AUTO":
            bpy.ops.object.shade_smooth()
            # Blender 4.2+ removed use_auto_smooth — use Smooth by Angle modifier
            if compat.IS_4_2_OR_LATER:
                # Check if modifier already exists
                existing = None
                for mod in obj.modifiers:
                    if mod.type == "NODES" and mod.name == "Smooth by Angle":
                        existing = mod
                        break
                if not existing:
                    bpy.ops.object.modifier_add(type="NODES")
                    mod = obj.modifiers[-1]
                    # Use the built-in Smooth by Angle geometry node group
                    try:
                        # The modifier is added via operator in 4.2+
                        # Remove the generic one and use shade_smooth_by_angle
                        obj.modifiers.remove(mod)
                        bpy.ops.object.shade_smooth()
                        obj.data.auto_smooth_angle = auto_smooth_angle
                    except (AttributeError, RuntimeError):
                        pass
                # Fallback: set per-edge sharp based on angle via bmesh
                import bmesh
                bm = bmesh.new()
                bm.from_mesh(obj.data)
                for edge in bm.edges:
                    if len(edge.link_faces) == 2:
                        angle = edge.calc_face_angle()
                        edge.smooth = angle <= auto_smooth_angle
                    else:
                        edge.smooth = True
                bm.to_mesh(obj.data)
                bm.free()
                obj.data.update()
            else:
                obj.data.use_auto_smooth = True
                obj.data.auto_smooth_angle = auto_smooth_angle

        return {
            "success": True,
            "object": object_name,
            "shade_type": shade_type,
            "auto_smooth_angle_degrees": math.degrees(auto_smooth_angle) if shade_type == "AUTO" else None,
        }


    def _handle_mesh_crease(self, params: dict) -> dict:
        """Set edge crease values for subdivision surface control."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        edge_indices = params.get("edge_indices")
        crease_value = params.get("crease_value", 1.0)
        selected_only = params.get("selected_only", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.edges.ensure_lookup_table()

        crease_layer = bm.edges.layers.crease.verify()

        affected = 0
        if edge_indices is not None:
            for i in edge_indices:
                i = int(i)
                if 0 <= i < len(bm.edges):
                    bm.edges[i][crease_layer] = crease_value
                    affected += 1
        elif selected_only:
            for e in bm.edges:
                if e.select:
                    e[crease_layer] = crease_value
                    affected += 1
        else:
            for e in bm.edges:
                e[crease_layer] = crease_value
                affected += 1

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "crease_value": crease_value,
            "affected_edges": affected,
        }


    def _handle_mesh_mark_sharp(self, params: dict) -> dict:
        """Mark or clear sharp edges."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        edge_indices = params.get("edge_indices")
        clear = params.get("clear", False)
        selected_only = params.get("selected_only", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.edges.ensure_lookup_table()

        affected = 0
        smooth_val = True if clear else False  # edge.smooth=False means sharp

        if edge_indices is not None:
            for i in edge_indices:
                i = int(i)
                if 0 <= i < len(bm.edges):
                    bm.edges[i].smooth = smooth_val
                    affected += 1
        elif selected_only:
            for e in bm.edges:
                if e.select:
                    e.smooth = smooth_val
                    affected += 1
        else:
            for e in bm.edges:
                e.smooth = smooth_val
                affected += 1

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "action": "clear_sharp" if clear else "mark_sharp",
            "affected_edges": affected,
        }


    def _handle_mesh_mark_seam(self, params: dict) -> dict:
        """Mark or clear UV seams on edges."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        edge_indices = params.get("edge_indices")
        clear = params.get("clear", False)
        selected_only = params.get("selected_only", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.edges.ensure_lookup_table()

        affected = 0
        seam_val = False if clear else True

        if edge_indices is not None:
            for i in edge_indices:
                i = int(i)
                if 0 <= i < len(bm.edges):
                    bm.edges[i].seam = seam_val
                    affected += 1
        elif selected_only:
            for e in bm.edges:
                if e.select:
                    e.seam = seam_val
                    affected += 1
        else:
            for e in bm.edges:
                e.seam = seam_val
                affected += 1

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "action": "clear_seam" if clear else "mark_seam",
            "affected_edges": affected,
        }

    # ========== Topology Editing Tools ==========


    def _handle_mesh_dissolve(self, params: dict) -> dict:
        """Remove elements preserving surrounding geometry."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        mode = validate_enum(require_param(params, "mode", str), "mode", ["VERTS", "EDGES", "FACES"])
        indices = require_param(params, "indices", list)
        use_face_split = params.get("use_face_split", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        if mode == "VERTS":
            elems = []
            for i in indices:
                i = int(i)
                if 0 <= i < len(bm.verts):
                    elems.append(bm.verts[i])
            bmesh.ops.dissolve_verts(bm, verts=elems, use_face_split=use_face_split)
        elif mode == "EDGES":
            elems = []
            for i in indices:
                i = int(i)
                if 0 <= i < len(bm.edges):
                    elems.append(bm.edges[i])
            bmesh.ops.dissolve_edges(bm, edges=elems, use_face_split=use_face_split)
        elif mode == "FACES":
            elems = []
            for i in indices:
                i = int(i)
                if 0 <= i < len(bm.faces):
                    elems.append(bm.faces[i])
            bmesh.ops.dissolve_faces(bm, faces=elems)

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "mode": mode,
            "dissolved_count": len(indices),
        }


    def _handle_mesh_merge(self, params: dict) -> dict:
        """Merge vertices together."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        vertex_indices = params.get("vertex_indices")
        merge_type = validate_enum(params.get("merge_type", "CENTER"), "merge_type", ["CENTER", "FIRST", "LAST", "BY_DISTANCE"])
        distance = params.get("distance", 0.0001)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        before_count = len(bm.verts)

        if merge_type == "BY_DISTANCE":
            if vertex_indices:
                verts = [bm.verts[int(i)] for i in vertex_indices if 0 <= int(i) < len(bm.verts)]
            else:
                verts = list(bm.verts)
            bmesh.ops.remove_doubles(bm, verts=verts, dist=distance)
        else:
            if not vertex_indices or len(vertex_indices) < 2:
                bm.free()
                raise ValidationError("Need at least 2 vertex indices for CENTER/FIRST/LAST merge")
            verts = [bm.verts[int(i)] for i in vertex_indices if 0 <= int(i) < len(bm.verts)]
            if merge_type == "CENTER":
                from mathutils import Vector
                center = Vector((0, 0, 0))
                for v in verts:
                    center += v.co
                center /= len(verts)
                bmesh.ops.pointmerge(bm, verts=verts, merge_co=center)
            elif merge_type == "FIRST":
                bmesh.ops.pointmerge(bm, verts=verts, merge_co=verts[0].co.copy())
            elif merge_type == "LAST":
                bmesh.ops.pointmerge(bm, verts=verts, merge_co=verts[-1].co.copy())

        bm.to_mesh(obj.data)
        after_count = len(bm.verts)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "merge_type": merge_type,
            "verts_before": before_count,
            "verts_after": after_count,
            "merged": before_count - after_count,
        }


    def _handle_mesh_bridge(self, params: dict) -> dict:
        """Bridge two edge loops to create connecting faces."""
        object_name = require_param(params, "object_name", str)
        loop1_edges = require_param(params, "loop1_edges", list)
        loop2_edges = require_param(params, "loop2_edges", list)
        segments = int(params.get("segments", 1))
        twist = int(params.get("twist", 0))
        profile_factor = params.get("profile_factor", 0.0)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        ensure_object_selected(obj)
        bpy.context.view_layer.objects.active = obj

        mesh = obj.data

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, True, False)
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")

        all_edges = [int(i) for i in loop1_edges + loop2_edges]
        for i in all_edges:
            if 0 <= i < len(mesh.edges):
                mesh.edges[i].select = True

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.bridge_edge_loops(
            number_cuts=segments - 1 if segments > 1 else 0,
            twist_offset=twist,
            profile_shape_factor=profile_factor,
        )
        bpy.ops.object.mode_set(mode="OBJECT")

        return {
            "success": True,
            "object": object_name,
            "loop1_count": len(loop1_edges),
            "loop2_count": len(loop2_edges),
            "segments": segments,
        }


    def _handle_mesh_fill(self, params: dict) -> dict:
        """Fill boundary edges with faces."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        edge_indices = require_param(params, "edge_indices", list)
        fill_type = validate_enum(params.get("fill_type", "NGON"), "fill_type", ["NGON", "TRIANGLE_FAN", "GRID"])
        use_beauty = params.get("use_beauty", True)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        if fill_type == "GRID":
            # Grid fill requires operator context
            ensure_object_selected(obj)
            bpy.context.view_layer.objects.active = obj

            bpy.ops.object.mode_set(mode="EDIT")
            bpy.context.tool_settings.mesh_select_mode = (False, True, False)
            bpy.ops.mesh.select_all(action="DESELECT")
            bpy.ops.object.mode_set(mode="OBJECT")

            mesh = obj.data
            for i in edge_indices:
                i = int(i)
                if 0 <= i < len(mesh.edges):
                    mesh.edges[i].select = True

            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.fill_grid()
            bpy.ops.object.mode_set(mode="OBJECT")
        else:
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bm.edges.ensure_lookup_table()

            edges = []
            for i in edge_indices:
                i = int(i)
                if 0 <= i < len(bm.edges):
                    edges.append(bm.edges[i])

            # Collect verts from selected edges
            verts = set()
            for e in edges:
                verts.update(e.verts)

            if fill_type == "TRIANGLE_FAN":
                bmesh.ops.triangle_fill(bm, edges=edges, use_beauty=use_beauty)
            else:
                bmesh.ops.contextual_create(bm, geom=list(verts) + edges)

            bm.to_mesh(obj.data)
            bm.free()
            obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "fill_type": fill_type,
            "edge_count": len(edge_indices),
        }


    def _handle_mesh_subdivide(self, params: dict) -> dict:
        """Subdivide selected edges/faces to add resolution."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        edge_indices = params.get("edge_indices")
        cuts = int(params.get("cuts", 1))
        smoothness = params.get("smoothness", 0.0)
        quad_corner_type = validate_enum(
            params.get("quad_corner_type", "STRAIGHT_CUT"),
            "quad_corner_type",
            ["STRAIGHT_CUT", "INNERVERT", "PATH", "FAN"],
        )

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.edges.ensure_lookup_table()

        before_verts = len(bm.verts)
        before_faces = len(bm.faces)

        if edge_indices is not None:
            edges = []
            for i in edge_indices:
                i = int(i)
                if 0 <= i < len(bm.edges):
                    edges.append(bm.edges[i])
        else:
            edges = list(bm.edges)

        bmesh.ops.subdivide_edges(
            bm,
            edges=edges,
            cuts=cuts,
            smooth=smoothness,
            quad_corner_type=quad_corner_type,
        )

        bm.to_mesh(obj.data)
        after_verts = len(bm.verts)
        after_faces = len(bm.faces)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "cuts": cuts,
            "verts_before": before_verts,
            "verts_after": after_verts,
            "faces_before": before_faces,
            "faces_after": after_faces,
        }


    def _handle_mesh_edge_slide(self, params: dict) -> dict:
        """Slide edges along their connected faces."""
        object_name = require_param(params, "object_name", str)
        edge_indices = require_param(params, "edge_indices", list)
        factor = params.get("factor", 0.0)
        even = params.get("even", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        ensure_object_selected(obj)
        bpy.context.view_layer.objects.active = obj

        mesh = obj.data
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, True, False)
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")

        for i in edge_indices:
            i = int(i)
            if 0 <= i < len(mesh.edges):
                mesh.edges[i].select = True

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.transform.edge_slide(value=factor, single_side=False, even=even)
        bpy.ops.object.mode_set(mode="OBJECT")

        return {
            "success": True,
            "object": object_name,
            "edge_count": len(edge_indices),
            "factor": factor,
            "even": even,
        }


    def _handle_mesh_tris_to_quads(self, params: dict) -> dict:
        """Convert triangles to quads."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        face_indices = params.get("face_indices")
        angle_limit = math.radians(params.get("angle_limit", 40.0))
        compare_uvs = params.get("compare_uvs", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()

        before_faces = len(bm.faces)

        if face_indices is not None:
            faces = []
            for i in face_indices:
                i = int(i)
                if 0 <= i < len(bm.faces):
                    faces.append(bm.faces[i])
        else:
            faces = [f for f in bm.faces if len(f.verts) == 3]

        bmesh.ops.join_triangles(
            bm,
            faces=faces,
            angle_face_threshold=angle_limit,
            angle_shape_threshold=angle_limit,
            cmp_uvs=compare_uvs,
        )

        bm.to_mesh(obj.data)
        after_faces = len(bm.faces)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "faces_before": before_faces,
            "faces_after": after_faces,
            "quads_created": before_faces - after_faces,
        }


    def _handle_mesh_triangulate(self, params: dict) -> dict:
        """Triangulate a mesh's faces.

        Quads and n-gons (e.g. the bevel caps ``bpy.ops.object.convert``
        leaves on a converted text object) can be non-planar and are a
        common cause of the EXACT boolean solver silently producing broken
        geometry. Triangulating a tool mesh before ``boolean_op`` is cheap
        insurance against that.
        """
        import bmesh

        object_name = require_param(params, "object_name", str)
        quad_method = validate_enum(
            params.get("quad_method", "BEAUTY"),
            "quad_method",
            ["BEAUTY", "FIXED", "FIXED_ALTERNATE", "SHORTEST_DIAGONAL"],
        )
        ngon_method = validate_enum(
            params.get("ngon_method", "BEAUTY"),
            "ngon_method",
            ["BEAUTY", "CLIP"],
        )

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        before_faces = len(bm.faces)

        bmesh.ops.triangulate(
            bm,
            faces=bm.faces,
            quad_method=quad_method,
            ngon_method=ngon_method,
        )

        bm.to_mesh(obj.data)
        after_faces = len(bm.faces)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "faces_before": before_faces,
            "faces_after": after_faces,
        }

    # ========== Cutting & Separation Tools ==========


    def _handle_mesh_knife_project(self, params: dict) -> dict:
        """Project a curve/mesh onto a target surface to cut panel lines."""
        target_name = require_param(params, "target_object", str)
        cutter_name = require_param(params, "cutter_object", str)
        cut_through = params.get("cut_through", False)

        target = get_object_or_error(target_name)
        cutter = get_object_or_error(cutter_name)

        if target.type != "MESH":
            raise ValidationError(f"Target '{target_name}' is not a mesh")

        ensure_object_selected(target)
        bpy.context.view_layer.objects.active = target
        cutter.select_set(True)

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")

        try:
            bpy.ops.mesh.knife_project(cut_through=cut_through)
            bpy.ops.object.mode_set(mode="OBJECT")
            return {
                "success": True,
                "target": target_name,
                "cutter": cutter_name,
                "method": "knife_project",
            }
        except RuntimeError:
            bpy.ops.object.mode_set(mode="OBJECT")

        # Fallback: use boolean INTERSECT to cut geometry
        try:
            mod = target.modifiers.new(name="KnifeFallback", type="BOOLEAN")
            mod.operation = "INTERSECT"
            mod.object = cutter
            mod.solver = "EXACT"

            ensure_object_selected(target)
            bpy.context.view_layer.objects.active = target
            bpy.ops.object.modifier_apply(modifier=mod.name)
            cutter.hide_set(True)

            return {
                "success": True,
                "target": target_name,
                "cutter": cutter_name,
                "method": "boolean_intersect_fallback",
                "note": "Knife project requires 3D viewport. Used boolean INTERSECT as fallback.",
            }
        except Exception as e:
            return {
                "success": False,
                "target": target_name,
                "cutter": cutter_name,
                "method": "failed",
                "error": str(e),
                "note": "Both knife_project and boolean fallback failed. Use blender_boolean_op manually.",
            }


    def _handle_mesh_bisect(self, params: dict) -> dict:
        """Cut mesh with an infinite plane."""
        import bmesh
        from mathutils import Vector

        object_name = require_param(params, "object_name", str)
        plane_point = validate_vector3(require_param(params, "plane_point", list), "plane_point")
        plane_normal = validate_vector3(require_param(params, "plane_normal", list), "plane_normal")
        clear_inner = params.get("clear_inner", False)
        clear_outer = params.get("clear_outer", False)
        fill = params.get("fill", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        before_verts = len(bm.verts)

        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)

        result = bmesh.ops.bisect_plane(
            bm,
            geom=geom,
            plane_co=Vector(plane_point),
            plane_no=Vector(plane_normal),
            clear_inner=clear_inner,
            clear_outer=clear_outer,
        )

        if fill:
            # Fill the cut edges
            cut_edges = [e for e in result["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
            if cut_edges:
                verts = set()
                for e in cut_edges:
                    verts.update(e.verts)
                bmesh.ops.contextual_create(bm, geom=list(verts) + cut_edges)

        bm.to_mesh(obj.data)
        after_verts = len(bm.verts)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "plane_point": list(plane_point),
            "plane_normal": list(plane_normal),
            "verts_before": before_verts,
            "verts_after": after_verts,
            "clear_inner": clear_inner,
            "clear_outer": clear_outer,
            "filled": fill,
        }


    def _handle_mesh_separate_selected(self, params: dict) -> dict:
        """Separate selected faces into a new object."""
        object_name = require_param(params, "object_name", str)
        face_indices = require_param(params, "face_indices", list)
        new_name = params.get("new_name")

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        ensure_object_selected(obj)
        bpy.context.view_layer.objects.active = obj

        mesh = obj.data

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")

        for i in face_indices:
            i = int(i)
            if 0 <= i < len(mesh.polygons):
                mesh.polygons[i].select = True

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.separate(type="SELECTED")
        bpy.ops.object.mode_set(mode="OBJECT")

        # The new object is the last selected object that isn't the original
        new_obj = None
        for o in bpy.context.selected_objects:
            if o != obj:
                new_obj = o
                break

        if new_obj and new_name:
            new_obj.name = new_name

        return {
            "success": True,
            "source_object": object_name,
            "new_object": new_obj.name if new_obj else None,
            "separated_faces": len(face_indices),
        }


    def _handle_mesh_split(self, params: dict) -> dict:
        """Split edges or faces without separating into a new object."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        mode = validate_enum(params.get("mode", "EDGES"), "mode", ["EDGES", "FACES"])
        indices = require_param(params, "indices", list)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        before_verts = len(bm.verts)

        if mode == "EDGES":
            edges = []
            for i in indices:
                i = int(i)
                if 0 <= i < len(bm.edges):
                    edges.append(bm.edges[i])
            bmesh.ops.split_edges(bm, edges=edges)
        elif mode == "FACES":
            faces = []
            for i in indices:
                i = int(i)
                if 0 <= i < len(bm.faces):
                    faces.append(bm.faces[i])
            # Split faces by splitting their edges
            edges = set()
            for f in faces:
                edges.update(f.edges)
            bmesh.ops.split_edges(bm, edges=list(edges))

        bm.to_mesh(obj.data)
        after_verts = len(bm.verts)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "mode": mode,
            "split_count": len(indices),
            "verts_before": before_verts,
            "verts_after": after_verts,
        }

    # ========== Reference & Measurement ==========


    def _handle_silhouette_compare(self, params: dict) -> dict:
        """Render silhouette and compare against reference image."""
        from mathutils import Vector

        object_name = require_param(params, "object_name", str)
        reference_image = require_param(params, "reference_image", str)
        camera_angle = validate_enum(
            params.get("camera_angle", "FRONT"),
            "camera_angle",
            ["FRONT", "RIGHT", "TOP", "PERSPECTIVE"],
        )
        resolution = int(params.get("resolution", 512))

        obj = get_object_or_error(object_name)

        if not os.path.exists(reference_image):
            raise ValidationError(f"Reference image not found: {reference_image}")

        output_path = os.path.join(tempfile.gettempdir(), f"silhouette_{object_name}.png")
        os.path.join(tempfile.gettempdir(), f"silhouette_overlay_{object_name}.png")

        # Store original state
        scene = bpy.context.scene
        orig_engine = scene.render.engine
        orig_res_x = scene.render.resolution_x
        orig_res_y = scene.render.resolution_y
        orig_transparent = scene.render.film_transparent
        orig_camera = scene.camera

        # Store original materials
        orig_mats = [slot.material for slot in obj.material_slots]

        try:
            # Create white emission material for silhouette
            sil_mat = bpy.data.materials.new("_silhouette_temp")
            sil_mat.use_nodes = True
            nodes = sil_mat.node_tree.nodes
            nodes.clear()
            emit = nodes.new("ShaderNodeEmission")
            emit.inputs[0].default_value = (1, 1, 1, 1)
            output_node = nodes.new("ShaderNodeOutputMaterial")
            sil_mat.node_tree.links.new(emit.outputs[0], output_node.inputs[0])

            # Apply silhouette material
            obj.data.materials.clear()
            obj.data.materials.append(sil_mat)

            # Set up orthographic camera
            cam_data = bpy.data.cameras.new("_sil_cam")
            cam_obj = bpy.data.objects.new("_sil_cam", cam_data)
            scene.collection.objects.link(cam_obj)
            scene.camera = cam_obj
            cam_data.type = "ORTHO"

            # Position camera based on angle
            bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
            center = sum(bbox, Vector()) / 8
            dims = Vector((
                max(b.x for b in bbox) - min(b.x for b in bbox),
                max(b.y for b in bbox) - min(b.y for b in bbox),
                max(b.z for b in bbox) - min(b.z for b in bbox),
            ))

            angles = {
                "FRONT": (0, -1, 0),
                "RIGHT": (1, 0, 0),
                "TOP": (0, 0, 1),
                "PERSPECTIVE": (1, -1, 0.7),
            }
            angle_vec = Vector(angles[camera_angle]).normalized()
            cam_obj.location = center + angle_vec * max(dims) * 3

            direction = center - cam_obj.location
            rot_quat = direction.to_track_quat("-Z", "Y")
            cam_obj.rotation_euler = rot_quat.to_euler()
            cam_data.ortho_scale = max(dims) * 1.2

            # Render settings
            scene.render.resolution_x = resolution
            scene.render.resolution_y = resolution
            scene.render.film_transparent = True
            scene.render.engine = compat.get_eevee_engine_name()
            scene.render.filepath = output_path

            # Render silhouette
            bpy.ops.render.render(write_still=True)

            # Compare with reference using bpy.data.images pixel comparison
            ref_img = bpy.data.images.load(reference_image)
            sil_img = bpy.data.images.load(output_path)

            # Scale comparison: compute pixel overlap
            ref_pixels = list(ref_img.pixels)
            sil_pixels = list(sil_img.pixels)

            difference_score = 0.0
            total_pixels = 0
            matching_pixels = 0

            # Compare alpha channels (silhouette = where alpha > 0.5)
            min_len = min(len(ref_pixels), len(sil_pixels))
            pixel_count = min_len // 4

            for i in range(pixel_count):
                idx = i * 4
                # Use luminance for reference, alpha for silhouette
                ref_lum = (ref_pixels[idx] + ref_pixels[idx + 1] + ref_pixels[idx + 2]) / 3
                ref_is_object = ref_lum > 0.1 or ref_pixels[idx + 3] > 0.5
                sil_is_object = sil_pixels[idx + 3] > 0.5

                if ref_is_object or sil_is_object:
                    total_pixels += 1
                    if ref_is_object == sil_is_object:
                        matching_pixels += 1

            if total_pixels > 0:
                difference_score = 1.0 - (matching_pixels / total_pixels)
            else:
                difference_score = 0.0

            # Cleanup images
            bpy.data.images.remove(ref_img)
            bpy.data.images.remove(sil_img)

            # Cleanup camera
            bpy.data.objects.remove(cam_obj)
            bpy.data.cameras.remove(cam_data)

            # Cleanup material
            bpy.data.materials.remove(sil_mat)

        finally:
            # Restore original materials
            obj.data.materials.clear()
            for mat in orig_mats:
                obj.data.materials.append(mat)

            # Restore render settings
            scene.render.engine = orig_engine
            scene.render.resolution_x = orig_res_x
            scene.render.resolution_y = orig_res_y
            scene.render.film_transparent = orig_transparent
            scene.camera = orig_camera

        return {
            "success": True,
            "object": object_name,
            "reference_image": reference_image,
            "silhouette_path": output_path,
            "camera_angle": camera_angle,
            "resolution": resolution,
            "difference_score": round(difference_score, 4),
            "matching_ratio": round(1.0 - difference_score, 4),
            "total_compared_pixels": total_pixels,
        }


    def _handle_measure(self, params: dict) -> dict:
        """Measure distances, bounding boxes, edge lengths."""
        import bmesh
        from mathutils import Vector

        object_name = require_param(params, "object_name", str)
        mode = validate_enum(params.get("mode", "BBOX"), "mode", ["BBOX", "DISTANCE", "EDGE_LENGTH", "VERTEX_DISTANCE"])

        obj = get_object_or_error(object_name)

        if mode == "BBOX":
            bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
            x_vals = [b.x for b in bbox]
            y_vals = [b.y for b in bbox]
            z_vals = [b.z for b in bbox]
            dims = {
                "x": max(x_vals) - min(x_vals),
                "y": max(y_vals) - min(y_vals),
                "z": max(z_vals) - min(z_vals),
            }
            center = {
                "x": (max(x_vals) + min(x_vals)) / 2,
                "y": (max(y_vals) + min(y_vals)) / 2,
                "z": (max(z_vals) + min(z_vals)) / 2,
            }
            return {
                "success": True,
                "object": object_name,
                "mode": "BBOX",
                "dimensions": dims,
                "center": center,
                "min": {"x": min(x_vals), "y": min(y_vals), "z": min(z_vals)},
                "max": {"x": max(x_vals), "y": max(y_vals), "z": max(z_vals)},
            }

        elif mode == "DISTANCE":
            point_a = validate_vector3(require_param(params, "point_a", list), "point_a")
            point_b = validate_vector3(require_param(params, "point_b", list), "point_b")
            dist = (Vector(point_a) - Vector(point_b)).length
            return {
                "success": True,
                "mode": "DISTANCE",
                "point_a": list(point_a),
                "point_b": list(point_b),
                "distance": dist,
            }

        elif mode == "EDGE_LENGTH":
            edge_indices = require_param(params, "edge_indices", list)
            if obj.type != "MESH":
                raise ValidationError(f"Object '{object_name}' is not a mesh")
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bm.edges.ensure_lookup_table()

            lengths = {}
            total = 0
            for i in edge_indices:
                i = int(i)
                if 0 <= i < len(bm.edges):
                    length = bm.edges[i].calc_length()
                    lengths[str(i)] = length
                    total += length

            bm.free()
            return {
                "success": True,
                "object": object_name,
                "mode": "EDGE_LENGTH",
                "edge_lengths": lengths,
                "total_length": total,
            }

        elif mode == "VERTEX_DISTANCE":
            vertex_indices = require_param(params, "vertex_indices", list)
            if len(vertex_indices) < 2:
                raise ValidationError("Need at least 2 vertex indices")
            if obj.type != "MESH":
                raise ValidationError(f"Object '{object_name}' is not a mesh")

            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bm.verts.ensure_lookup_table()

            i_a = int(vertex_indices[0])
            i_b = int(vertex_indices[1])
            if i_a >= len(bm.verts) or i_b >= len(bm.verts):
                bm.free()
                raise ValidationError("Vertex index out of range")

            co_a = obj.matrix_world @ bm.verts[i_a].co
            co_b = obj.matrix_world @ bm.verts[i_b].co
            dist = (co_a - co_b).length

            bm.free()
            return {
                "success": True,
                "object": object_name,
                "mode": "VERTEX_DISTANCE",
                "vertex_a": i_a,
                "vertex_b": i_b,
                "distance": dist,
            }


    def _handle_reference_image_setup(self, params: dict) -> dict:
        """Load a reference image as a background empty."""
        from mathutils import Vector

        image_path = require_param(params, "image_path", str)
        axis = validate_enum(params.get("axis", "FRONT"), "axis", ["FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"])
        offset = params.get("offset", -5.0)
        opacity = params.get("opacity", 0.5)
        size = params.get("size", 5.0)

        validate_filepath(image_path)

        # Create image empty
        bpy.ops.object.empty_add(type="IMAGE")
        empty = bpy.context.active_object
        empty.name = f"Ref_{axis}_{os.path.basename(image_path)}"

        # Load image
        img = bpy.data.images.load(image_path)
        empty.data = img
        empty.empty_display_size = size
        empty.empty_image_depth = "BACK"
        empty.color[3] = opacity

        # Position based on axis
        axis_positions = {
            "FRONT": (Vector((0, offset, 0)), (math.radians(90), 0, 0)),
            "BACK": (Vector((0, -offset, 0)), (math.radians(90), 0, math.radians(180))),
            "LEFT": (Vector((offset, 0, 0)), (math.radians(90), 0, math.radians(-90))),
            "RIGHT": (Vector((-offset, 0, 0)), (math.radians(90), 0, math.radians(90))),
            "TOP": (Vector((0, 0, -offset)), (0, 0, 0)),
            "BOTTOM": (Vector((0, 0, offset)), (math.radians(180), 0, 0)),
        }

        pos, rot = axis_positions[axis]
        empty.location = pos
        empty.rotation_euler = rot

        return {
            "success": True,
            "empty_name": empty.name,
            "image": image_path,
            "axis": axis,
            "offset": offset,
            "size": size,
        }

    # ========== Detail Placement & Instancing ==========


    def _handle_array_along_curve(self, params: dict) -> dict:
        """Instance objects along a curve path."""
        source_name = require_param(params, "source_object", str)
        curve_name = require_param(params, "curve_name", str)
        count = int(params.get("count", 10))
        fit_type = validate_enum(params.get("fit_type", "FIT_CURVE"), "fit_type", ["FIXED_COUNT", "FIT_LENGTH", "FIT_CURVE"])
        apply = params.get("apply", False)

        source = get_object_or_error(source_name)
        curve = get_object_or_error(curve_name)

        if curve.type != "CURVE":
            raise ValidationError(f"'{curve_name}' is not a curve object")

        # Add Array modifier
        array_mod = source.modifiers.new(name="ArrayAlongCurve", type="ARRAY")
        array_mod.fit_type = fit_type
        if fit_type == "FIXED_COUNT":
            array_mod.count = count
        elif fit_type == "FIT_CURVE":
            array_mod.curve = curve
        array_mod.use_relative_offset = True
        array_mod.relative_offset_displace = (1, 0, 0)

        # Add Curve modifier
        curve_mod = source.modifiers.new(name="CurveFollow", type="CURVE")
        curve_mod.object = curve

        if apply:
            ensure_object_selected(source)
            bpy.context.view_layer.objects.active = source
            bpy.ops.object.modifier_apply(modifier=array_mod.name)
            bpy.ops.object.modifier_apply(modifier=curve_mod.name)

        return {
            "success": True,
            "source_object": source_name,
            "curve": curve_name,
            "fit_type": fit_type,
            "count": count,
            "applied": apply,
        }


    def _handle_scatter_on_surface(self, params: dict) -> dict:
        """Scatter objects on a mesh surface using particle system."""
        target_name = require_param(params, "target_object", str)
        source_name = require_param(params, "source_object", str)
        count = int(params.get("count", 100))
        seed = int(params.get("seed", 0))
        scale_min = params.get("scale_min", 1.0)
        scale_max = params.get("scale_max", 1.0)
        rotation_random = params.get("rotation_random", 0.0)
        vertex_group = params.get("vertex_group")

        target = get_object_or_error(target_name)
        source = get_object_or_error(source_name)

        if target.type != "MESH":
            raise ValidationError(f"Target '{target_name}' is not a mesh")

        # Add particle system
        target.modifiers.new(name="Scatter", type="PARTICLE_SYSTEM")
        ps = target.particle_systems[-1]
        settings = ps.settings

        settings.type = "HAIR"
        settings.use_advanced_hair = True
        settings.count = count
        settings.hair_length = 1.0
        settings.render_type = "OBJECT"
        settings.instance_object = source
        settings.particle_size = 1.0
        settings.size_random = (scale_max - scale_min) / max(scale_max, 0.001)
        settings.use_rotation_instance = True
        settings.phase_factor_random = rotation_random
        settings.use_emit_random = True
        settings.emit_from = "FACE"
        ps.seed = seed

        if vertex_group and vertex_group in target.vertex_groups:
            ps.vertex_group_density = vertex_group

        return {
            "success": True,
            "target_object": target_name,
            "source_object": source_name,
            "count": count,
            "seed": seed,
        }


    def _handle_collection_instance(self, params: dict) -> dict:
        """Place collection instances at specific locations."""
        from mathutils import Vector

        collection_name = require_param(params, "collection_name", str)
        locations = require_param(params, "locations", list)
        rotations = params.get("rotations")
        scales = params.get("scales")

        if collection_name not in bpy.data.collections:
            raise ValidationError(f"Collection '{collection_name}' not found")

        collection = bpy.data.collections[collection_name]
        created = []

        for i, loc in enumerate(locations):
            empty = bpy.data.objects.new(f"{collection_name}_instance_{i}", None)
            empty.instance_type = "COLLECTION"
            empty.instance_collection = collection
            empty.location = Vector(loc)

            if rotations and i < len(rotations):
                rot = rotations[i]
                empty.rotation_euler = (math.radians(rot[0]), math.radians(rot[1]), math.radians(rot[2]))

            if scales and i < len(scales):
                empty.scale = Vector(scales[i])

            bpy.context.scene.collection.objects.link(empty)
            created.append(empty.name)

        return {
            "success": True,
            "collection": collection_name,
            "instances_created": created,
            "count": len(created),
        }

    # ========== Transform & Deform ==========


    def _handle_mesh_proportional_transform(self, params: dict) -> dict:
        """Move, rotate, or scale vertices with proportional falloff."""
        import bmesh
        from mathutils import Matrix, Vector

        object_name = require_param(params, "object_name", str)
        vertex_indices = require_param(params, "vertex_indices", list)
        transform_type = validate_enum(
            params.get("transform_type", "TRANSLATE"),
            "transform_type",
            ["TRANSLATE", "ROTATE", "SCALE"],
        )
        value = require_param(params, "value", list)
        falloff = validate_enum(
            params.get("falloff", "SMOOTH"),
            "falloff",
            ["SMOOTH", "SPHERE", "ROOT", "LINEAR", "SHARP", "CONSTANT"],
        )
        radius = params.get("radius", 1.0)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        # Get center vertices
        centers = []
        for i in vertex_indices:
            i = int(i)
            if 0 <= i < len(bm.verts):
                centers.append(bm.verts[i].co.copy())

        if not centers:
            bm.free()
            raise ValidationError("No valid vertex indices")

        center = sum(centers, Vector()) / len(centers)

        # Falloff function
        def calc_falloff(dist, r):
            if r <= 0:
                return 0
            t = min(dist / r, 1.0)
            if falloff == "SMOOTH":
                return 3 * (1 - t) ** 2 * t * 0 + 3 * (1 - t) * t ** 2 * 0 + (1 - t) ** 3  # smooth step
            elif falloff == "SPHERE":
                return math.sqrt(max(0, 1 - t * t))
            elif falloff == "ROOT":
                return math.sqrt(max(0, 1 - t))
            elif falloff == "LINEAR":
                return 1 - t
            elif falloff == "SHARP":
                return (1 - t) ** 2
            elif falloff == "CONSTANT":
                return 1.0 if t < 1.0 else 0.0
            return 0

        # Recalculate smooth falloff
        def smooth_falloff(dist, r):
            if r <= 0:
                return 0
            t = min(dist / r, 1.0)
            return 1 - (3 * t * t - 2 * t * t * t)

        if falloff == "SMOOTH":
            calc_falloff = smooth_falloff

        affected = 0
        for v in bm.verts:
            dist = (v.co - center).length
            if dist > radius:
                continue
            weight = calc_falloff(dist, radius)
            if weight <= 0:
                continue

            if transform_type == "TRANSLATE":
                offset = Vector(value[:3]) * weight
                v.co += offset
            elif transform_type == "SCALE":
                scale_vec = Vector(value[:3])
                diff = v.co - center
                v.co = center + Vector((diff.x * (1 + (scale_vec.x - 1) * weight),
                                        diff.y * (1 + (scale_vec.y - 1) * weight),
                                        diff.z * (1 + (scale_vec.z - 1) * weight)))
            elif transform_type == "ROTATE":
                if len(value) >= 4:
                    angle = math.radians(value[0]) * weight
                    axis = Vector(value[1:4]).normalized()
                    rot_mat = Matrix.Rotation(angle, 3, axis)
                    diff = v.co - center
                    v.co = center + rot_mat @ diff

            affected += 1

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "transform_type": transform_type,
            "falloff": falloff,
            "radius": radius,
            "affected_vertices": affected,
        }


    def _handle_mesh_shrinkwrap(self, params: dict) -> dict:
        """Snap vertices to another object's surface."""
        import bmesh
        from mathutils import Vector
        from mathutils.bvhtree import BVHTree

        object_name = require_param(params, "object_name", str)
        target_name = require_param(params, "target_object", str)
        vertex_indices = params.get("vertex_indices")
        mode = validate_enum(params.get("mode", "NEAREST_SURFACE"), "mode", ["NEAREST_SURFACE", "PROJECT", "NEAREST_VERTEX"])
        offset = params.get("offset", 0.0)

        obj = get_object_or_error(object_name)
        target = get_object_or_error(target_name)

        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")
        if target.type != "MESH":
            raise ValidationError(f"Target '{target_name}' is not a mesh")

        # Use modifier approach for simplicity and reliability
        if vertex_indices is None:
            # Use Shrinkwrap modifier for all vertices
            mod = obj.modifiers.new(name="Shrinkwrap", type="SHRINKWRAP")
            mod.target = target
            mod.offset = offset
            if mode == "NEAREST_SURFACE":
                mod.wrap_method = "NEAREST_SURFACEPOINT"
            elif mode == "PROJECT":
                mod.wrap_method = "PROJECT"
            elif mode == "NEAREST_VERTEX":
                mod.wrap_method = "NEAREST_VERTEX"

            ensure_object_selected(obj)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)

            return {
                "success": True,
                "object": object_name,
                "target": target_name,
                "mode": mode,
                "method": "modifier",
                "affected_vertices": len(obj.data.vertices),
            }
        else:
            # Use BVHTree for specific vertices
            bm_target = bmesh.new()
            bm_target.from_mesh(target.data)
            bvh = BVHTree.FromBMesh(bm_target)

            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bm.verts.ensure_lookup_table()

            target_matrix = target.matrix_world
            target_inv = target_matrix.inverted()
            obj_matrix = obj.matrix_world

            affected = 0
            for i in vertex_indices:
                i = int(i)
                if 0 <= i < len(bm.verts):
                    v = bm.verts[i]
                    world_co = obj_matrix @ v.co
                    local_co = target_inv @ world_co

                    if mode in ("NEAREST_SURFACE", "PROJECT"):
                        location, normal, idx, distance = bvh.find_nearest(local_co)
                        if location is not None:
                            new_world = target_matrix @ (location + (Vector(normal) * offset if normal else Vector()))
                            v.co = obj.matrix_world.inverted() @ new_world
                            affected += 1
                    elif mode == "NEAREST_VERTEX":
                        min_dist = float("inf")
                        nearest_co = None
                        for tv in bm_target.verts:
                            d = (tv.co - local_co).length
                            if d < min_dist:
                                min_dist = d
                                nearest_co = tv.co.copy()
                        if nearest_co is not None:
                            new_world = target_matrix @ nearest_co
                            v.co = obj.matrix_world.inverted() @ new_world
                            affected += 1

            bm.to_mesh(obj.data)
            bm.free()
            bm_target.free()
            obj.data.update()

            return {
                "success": True,
                "object": object_name,
                "target": target_name,
                "mode": mode,
                "method": "bvhtree",
                "affected_vertices": affected,
            }


    def _handle_mesh_flatten(self, params: dict) -> dict:
        """Flatten selected vertices to a plane."""
        import bmesh
        from mathutils import Vector

        object_name = require_param(params, "object_name", str)
        vertex_indices = require_param(params, "vertex_indices", list)
        plane = validate_enum(params.get("plane", "BEST_FIT"), "plane", ["XY", "XZ", "YZ", "NORMAL", "BEST_FIT"])

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        verts = []
        for i in vertex_indices:
            i = int(i)
            if 0 <= i < len(bm.verts):
                verts.append(bm.verts[i])

        if not verts:
            bm.free()
            raise ValidationError("No valid vertex indices")

        # Calculate center
        center = sum((v.co for v in verts), Vector()) / len(verts)

        if plane == "XY":
            for v in verts:
                v.co.z = center.z
        elif plane == "XZ":
            for v in verts:
                v.co.y = center.y
        elif plane == "YZ":
            for v in verts:
                v.co.x = center.x
        elif plane == "NORMAL":
            # Average normal of connected faces
            normal = Vector()
            for v in verts:
                for f in v.link_faces:
                    normal += f.normal
            if normal.length > 0:
                normal.normalize()
            else:
                normal = Vector((0, 0, 1))
            # Project onto plane defined by center + normal
            for v in verts:
                diff = v.co - center
                v.co -= diff.dot(normal) * normal
        elif plane == "BEST_FIT":
            # PCA-based best fit plane
            coords = [v.co.copy() for v in verts]
            # Compute covariance matrix
            cx = sum((c.x - center.x) ** 2 for c in coords)
            cy = sum((c.y - center.y) ** 2 for c in coords)
            cz = sum((c.z - center.z) ** 2 for c in coords)
            sum((c.x - center.x) * (c.y - center.y) for c in coords)
            sum((c.x - center.x) * (c.z - center.z) for c in coords)
            sum((c.y - center.y) * (c.z - center.z) for c in coords)

            # Find axis with least variance (normal to best-fit plane)
            variances = [cx, cy, cz]
            min_axis = variances.index(min(variances))

            if min_axis == 0:
                normal = Vector((1, 0, 0))
            elif min_axis == 1:
                normal = Vector((0, 1, 0))
            else:
                normal = Vector((0, 0, 1))

            for v in verts:
                diff = v.co - center
                v.co -= diff.dot(normal) * normal

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        return {
            "success": True,
            "object": object_name,
            "plane": plane,
            "flattened_vertices": len(verts),
        }

    # ========== Script Execution Handler ==========

