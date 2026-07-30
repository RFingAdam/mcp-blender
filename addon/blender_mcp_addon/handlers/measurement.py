"""Measurement and validation command handlers."""

import math
from typing import Any

import bpy

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


class MeasurementHandlersMixin:
    """Mixin for measurement and validation handlers."""

    def _handle_measure_surface_area(self, params: dict) -> dict:
        """Calculate total surface area with optional per-material breakdown."""
        import bmesh


        object_name = require_param(params, "object_name", str)
        per_material = params.get("per_material", False)
        world_space = params.get("world_space", True)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.faces.ensure_lookup_table()

            # Optionally transform verts into world space
            if world_space:
                bm.transform(obj.matrix_world)

            total_area = 0.0
            material_areas: dict[str, float] = {}

            for face in bm.faces:
                area = face.calc_area()
                total_area += area

                if per_material:
                    mat_idx = face.material_index
                    mat_name = "unassigned"
                    if mat_idx < len(obj.data.materials) and obj.data.materials[mat_idx]:
                        mat_name = obj.data.materials[mat_idx].name
                    material_areas[mat_name] = material_areas.get(mat_name, 0.0) + area

            result: dict[str, Any] = {
                "success": True,
                "object": object_name,
                "total_area": round(total_area, 6),
                "units": "m^2",
                "face_count": len(bm.faces),
                "world_space": world_space,
            }

            if per_material:
                result["per_material"] = {
                    k: round(v, 6) for k, v in sorted(material_areas.items())
                }

            return result
        finally:
            bm.free()

    # ── 2. Volume ────────────────────────────────────────────────────


    def _handle_measure_volume(self, params: dict) -> dict:
        """Calculate mesh volume using the signed-tetrahedron method."""
        import bmesh


        object_name = require_param(params, "object_name", str)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.transform(obj.matrix_world)
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()

            # Check manifold-ness: every edge must have exactly 2 linked faces
            non_manifold_edges = [
                e.index for e in bm.edges if not e.is_manifold
            ]
            is_manifold = len(non_manifold_edges) == 0

            # Signed tetrahedron volume method
            # For each triangle face, compute signed volume of tetrahedron
            # formed with the origin.  Works for any closed mesh;
            # triangulate first to handle quads/ngons.
            volume = 0.0

            # Triangulate a copy so we don't mutate the mesh
            bmesh.ops.triangulate(bm, faces=bm.faces[:])
            bm.faces.ensure_lookup_table()

            for face in bm.faces:
                verts = face.verts
                v0 = verts[0].co
                v1 = verts[1].co
                v2 = verts[2].co
                # Signed volume of tetrahedron with origin
                volume += v0.dot(v1.cross(v2)) / 6.0

            volume = abs(volume)

            return {
                "success": True,
                "object": object_name,
                "volume": round(volume, 6),
                "units": "m^3",
                "is_manifold": is_manifold,
                "non_manifold_edge_count": len(non_manifold_edges),
                "note": (
                    "Volume is accurate only for watertight (manifold) meshes."
                    if not is_manifold
                    else ""
                ),
            }
        finally:
            bm.free()

    # ── 3. Clearance ─────────────────────────────────────────────────


    def _handle_measure_clearance(self, params: dict) -> dict:
        """Min/avg/max distance between two mesh objects via BVHTree."""
        import bmesh
        from mathutils.bvhtree import BVHTree


        name_a = require_param(params, "object_a", str)
        name_b = require_param(params, "object_b", str)
        sample_count = int(params.get("sample_count", 1000))

        obj_a = get_object_or_error(name_a)
        obj_b = get_object_or_error(name_b)

        if obj_a.type != "MESH":
            raise ValidationError(f"Object '{name_a}' is not a mesh")
        if obj_b.type != "MESH":
            raise ValidationError(f"Object '{name_b}' is not a mesh")

        # Build BVH trees in world space
        bm_a = bmesh.new()
        bm_a.from_mesh(obj_a.data)
        bm_a.transform(obj_a.matrix_world)
        bvh_a = BVHTree.FromBMesh(bm_a)

        bm_b = bmesh.new()
        bm_b.from_mesh(obj_b.data)
        bm_b.transform(obj_b.matrix_world)
        bvh_b = BVHTree.FromBMesh(bm_b)

        try:
            # Check intersection
            overlap_pairs = bvh_a.overlap(bvh_b)
            objects_intersecting = len(overlap_pairs) > 0

            # Sample vertices from A and find closest on B
            bm_a.verts.ensure_lookup_table()
            total_verts = len(bm_a.verts)

            # Determine sampling stride
            if total_verts <= sample_count:
                stride = 1
            else:
                stride = max(1, total_verts // sample_count)

            min_dist = float("inf")
            max_dist = 0.0
            total_dist = 0.0
            count = 0
            closest_a = None
            closest_b = None

            for i in range(0, total_verts, stride):
                co = bm_a.verts[i].co
                location, normal, index, dist = bvh_b.find_nearest(co)
                if location is None:
                    continue

                d = (co - location).length
                total_dist += d
                count += 1

                if d < min_dist:
                    min_dist = d
                    closest_a = [round(co.x, 6), round(co.y, 6), round(co.z, 6)]
                    closest_b = [
                        round(location.x, 6),
                        round(location.y, 6),
                        round(location.z, 6),
                    ]
                if d > max_dist:
                    max_dist = d

            # Also sample B→A so we don't miss the global minimum
            bm_b.verts.ensure_lookup_table()
            total_verts_b = len(bm_b.verts)
            stride_b = max(1, total_verts_b // sample_count) if total_verts_b > sample_count else 1

            for i in range(0, total_verts_b, stride_b):
                co = bm_b.verts[i].co
                location, normal, index, dist = bvh_a.find_nearest(co)
                if location is None:
                    continue

                d = (co - location).length
                total_dist += d
                count += 1

                if d < min_dist:
                    min_dist = d
                    closest_b = [round(co.x, 6), round(co.y, 6), round(co.z, 6)]
                    closest_a = [
                        round(location.x, 6),
                        round(location.y, 6),
                        round(location.z, 6),
                    ]
                if d > max_dist:
                    max_dist = d

            avg_dist = total_dist / count if count > 0 else 0.0

            return {
                "success": True,
                "object_a": name_a,
                "object_b": name_b,
                "min_distance": round(min_dist, 6) if min_dist != float("inf") else None,
                "avg_distance": round(avg_dist, 6),
                "max_distance": round(max_dist, 6),
                "objects_intersecting": objects_intersecting,
                "intersection_face_pairs": len(overlap_pairs),
                "samples_evaluated": count,
                "closest_points": {
                    "on_a": closest_a,
                    "on_b": closest_b,
                },
            }
        finally:
            bm_a.free()
            bm_b.free()

    # ── 4. Validate Dimensions ───────────────────────────────────────


    def _handle_validate_dimensions(self, params: dict) -> dict:
        """Check object bbox dimensions against expected with tolerance."""
        from mathutils import Vector


        object_name = require_param(params, "object_name", str)
        expected = require_param(params, "expected", dict)
        tolerance = float(params.get("tolerance", 0.01))
        axis_mapping_raw = params.get("axis_mapping", {})

        obj = get_object_or_error(object_name)

        # Default axis mapping: length=X, width=Y, height=Z
        axis_map = {
            "length": axis_mapping_raw.get("length", "x").lower(),
            "width": axis_mapping_raw.get("width", "y").lower(),
            "height": axis_mapping_raw.get("height", "z").lower(),
        }

        # Compute world-space bounding box dimensions
        bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        x_vals = [b.x for b in bbox]
        y_vals = [b.y for b in bbox]
        z_vals = [b.z for b in bbox]

        actual_dims = {
            "x": max(x_vals) - min(x_vals),
            "y": max(y_vals) - min(y_vals),
            "z": max(z_vals) - min(z_vals),
        }

        results: dict[str, Any] = {}
        all_within = True

        for dim_name in ("length", "width", "height"):
            if dim_name not in expected:
                continue
            expected_val = float(expected[dim_name])
            axis = axis_map[dim_name]
            if axis not in actual_dims:
                raise ValidationError(
                    f"Invalid axis '{axis}' in axis_mapping for '{dim_name}'"
                )
            actual_val = actual_dims[axis]
            deviation = abs(actual_val - expected_val)
            within = deviation <= tolerance

            if not within:
                all_within = False

            results[dim_name] = {
                "axis": axis.upper(),
                "expected": round(expected_val, 6),
                "actual": round(actual_val, 6),
                "deviation": round(deviation, 6),
                "within_tolerance": within,
            }

        return {
            "success": True,
            "object": object_name,
            "tolerance": tolerance,
            "all_within_tolerance": all_within,
            "dimensions": results,
            "bbox_actual": {
                "x": round(actual_dims["x"], 6),
                "y": round(actual_dims["y"], 6),
                "z": round(actual_dims["z"], 6),
            },
        }

    # ── 5. Calibrate from Reference ──────────────────────────────────


    def _handle_calibrate_from_reference(self, params: dict) -> dict:
        """Scale object to match a known real-world dimension on one axis."""
        from mathutils import Vector

        from ..utils import get_object_or_error
        from ..validation import ValidationError, require_param

        object_name = require_param(params, "object_name", str)
        known_dimension = float(require_param(params, "known_dimension", (int, float)))
        dimension_axis = validate_enum(
            require_param(params, "dimension_axis", str),
            "dimension_axis",
            ["X", "Y", "Z"],
        )
        target_units = validate_enum(
            params.get("target_units", "METERS"),
            "target_units",
            ["METERS", "CM", "MM", "INCHES", "FEET"],
        )

        if known_dimension <= 0:
            raise ValidationError("known_dimension must be positive")

        # Convert known_dimension to meters (Blender scene units)
        unit_to_meters = {
            "METERS": 1.0,
            "CM": 0.01,
            "MM": 0.001,
            "INCHES": 0.0254,
            "FEET": 0.3048,
        }
        known_meters = known_dimension * unit_to_meters[target_units]

        obj = get_object_or_error(object_name)

        # Record original bbox in world space
        bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        x_vals = [b.x for b in bbox]
        y_vals = [b.y for b in bbox]
        z_vals = [b.z for b in bbox]

        original_bbox = {
            "x": round(max(x_vals) - min(x_vals), 6),
            "y": round(max(y_vals) - min(y_vals), 6),
            "z": round(max(z_vals) - min(z_vals), 6),
        }

        axis_idx = {"X": 0, "Y": 1, "Z": 2}[dimension_axis]
        dims = [
            max(x_vals) - min(x_vals),
            max(y_vals) - min(y_vals),
            max(z_vals) - min(z_vals),
        ]
        current_dim = dims[axis_idx]

        if current_dim < 1e-8:
            raise ValidationError(
                f"Object has near-zero extent on {dimension_axis} axis; "
                "cannot calibrate"
            )

        scale_factor = known_meters / current_dim

        # Apply uniform scale
        obj.scale *= scale_factor

        # Apply transforms so scale resets to (1,1,1)
        ensure_object_selected(obj)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        # Re-measure after calibration
        bbox2 = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        x2 = [b.x for b in bbox2]
        y2 = [b.y for b in bbox2]
        z2 = [b.z for b in bbox2]

        calibrated_bbox = {
            "x": round(max(x2) - min(x2), 6),
            "y": round(max(y2) - min(y2), 6),
            "z": round(max(z2) - min(z2), 6),
        }

        return {
            "success": True,
            "object": object_name,
            "scale_factor": round(scale_factor, 6),
            "dimension_axis": dimension_axis,
            "known_dimension": known_dimension,
            "target_units": target_units,
            "original_bbox": original_bbox,
            "calibrated_bbox": calibrated_bbox,
        }

    # ── 6. Edge Angle ────────────────────────────────────────────────


    def _handle_measure_edge_angle(self, params: dict) -> dict:
        """Measure dihedral angles at mesh edges."""
        import bmesh


        object_name = require_param(params, "object_name", str)
        edge_indices = params.get("edge_indices", None)
        threshold_min = params.get("threshold_min", None)
        threshold_max = params.get("threshold_max", None)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            # Determine which edges to measure
            if edge_indices is not None:
                target_indices = set(int(i) for i in edge_indices)
                edges_to_check = [
                    e for e in bm.edges
                    if e.index in target_indices and len(e.link_faces) >= 2
                ]
            else:
                edges_to_check = [
                    e for e in bm.edges if len(e.link_faces) >= 2
                ]

            angles: dict[str, float] = {}
            flagged_below: list[int] = []
            flagged_above: list[int] = []

            for edge in edges_to_check:
                try:
                    angle_rad = edge.calc_face_angle()
                except ValueError:
                    # Edge has no valid face angle (e.g. degenerate faces)
                    continue

                angle_deg = math.degrees(angle_rad)
                angles[str(edge.index)] = round(angle_deg, 4)

                if threshold_min is not None and angle_deg < float(threshold_min):
                    flagged_below.append(edge.index)
                if threshold_max is not None and angle_deg > float(threshold_max):
                    flagged_above.append(edge.index)

            result: dict[str, Any] = {
                "success": True,
                "object": object_name,
                "edge_count_measured": len(angles),
                "angles": angles,
            }

            if threshold_min is not None:
                result["threshold_min"] = float(threshold_min)
                result["flagged_below"] = flagged_below
                result["flagged_below_count"] = len(flagged_below)

            if threshold_max is not None:
                result["threshold_max"] = float(threshold_max)
                result["flagged_above"] = flagged_above
                result["flagged_above_count"] = len(flagged_above)

            # Summary statistics
            if angles:
                angle_vals = list(angles.values())
                result["min_angle"] = round(min(angle_vals), 4)
                result["max_angle"] = round(max(angle_vals), 4)
                result["avg_angle"] = round(
                    sum(angle_vals) / len(angle_vals), 4
                )

            return result
        finally:
            bm.free()

    # ── 7. Validate Mesh Quality ─────────────────────────────────────


    def _handle_validate_mesh_quality(self, params: dict) -> dict:
        """Comprehensive mesh quality audit."""
        import bmesh
        from mathutils import Vector


        ALL_CHECKS = [
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
        ]

        object_name = require_param(params, "object_name", str)
        requested_checks = params.get("checks", None)
        if requested_checks is None:
            checks_to_run = ALL_CHECKS
        else:
            checks_to_run = [c.upper() for c in requested_checks]

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            total_faces = len(bm.faces)
            total_edges = len(bm.edges)
            total_verts = len(bm.verts)

            check_results: dict[str, dict] = {}
            blocking_issues: list[str] = []
            passed_count = 0
            run_count = 0

            # Helper for scoring
            EPSILON = 1e-6

            # ── NON_MANIFOLD ──
            if "NON_MANIFOLD" in checks_to_run:
                run_count += 1
                non_manifold = [
                    e.index for e in bm.edges if not e.is_manifold
                ]
                passed = len(non_manifold) == 0
                if passed:
                    passed_count += 1
                else:
                    blocking_issues.append(
                        f"{len(non_manifold)} non-manifold edge(s)"
                    )
                check_results["NON_MANIFOLD"] = {
                    "passed": passed,
                    "count": len(non_manifold),
                    "indices": non_manifold[:50],  # Cap for response size
                    "detail": (
                        "All edges are manifold"
                        if passed
                        else f"{len(non_manifold)} non-manifold edges found"
                    ),
                }

            # ── DEGENERATE ──
            if "DEGENERATE" in checks_to_run:
                run_count += 1
                degenerate = [
                    f.index
                    for f in bm.faces
                    if f.calc_area() < EPSILON
                    or any(e.calc_length() < EPSILON for e in f.edges)
                ]
                passed = len(degenerate) == 0
                if passed:
                    passed_count += 1
                else:
                    blocking_issues.append(
                        f"{len(degenerate)} degenerate face(s)"
                    )
                check_results["DEGENERATE"] = {
                    "passed": passed,
                    "count": len(degenerate),
                    "indices": degenerate[:50],
                    "detail": (
                        "No degenerate faces"
                        if passed
                        else f"{len(degenerate)} degenerate faces (near-zero area or edge length)"
                    ),
                }

            # ── FLIPPED_NORMALS ──
            if "FLIPPED_NORMALS" in checks_to_run:
                run_count += 1
                # Heuristic: recalculate normals outside and compare
                # We check if face normals are consistent by looking at
                # edge-linked face pairs and checking dot product of normals.
                flipped_count = 0
                for edge in bm.edges:
                    if len(edge.link_faces) == 2:
                        f1, f2 = edge.link_faces
                        # Adjacent faces sharing an edge should have normals
                        # pointing in roughly the same direction (dot > 0)
                        # relative to the shared edge.  A simple consistency
                        # check: for a manifold mesh the winding should be
                        # opposite on the shared edge.
                        # Use the standard check: loop directions
                        shared_verts = set(f1.verts) & set(f2.verts)
                        if len(shared_verts) >= 2:
                            sv = list(shared_verts)
                            v0, v1 = sv[0], sv[1]
                            # Find order of v0→v1 in each face
                            def edge_order(face, va, vb):
                                verts = list(face.verts)
                                ia = verts.index(va)
                                ib = verts.index(vb)
                                n = len(verts)
                                if (ia + 1) % n == ib:
                                    return 1  # va→vb is forward
                                elif (ib + 1) % n == ia:
                                    return -1  # vb→va is forward
                                return 0

                            o1 = edge_order(f1, v0, v1)
                            o2 = edge_order(f2, v0, v1)
                            # Consistent mesh: adjacent faces traverse
                            # shared edge in opposite directions
                            if o1 != 0 and o2 != 0 and o1 == o2:
                                flipped_count += 1

                passed = flipped_count == 0
                if passed:
                    passed_count += 1
                check_results["FLIPPED_NORMALS"] = {
                    "passed": passed,
                    "count": flipped_count,
                    "detail": (
                        "Normals are consistent"
                        if passed
                        else f"{flipped_count} inconsistent normal pair(s) detected"
                    ),
                }

            # ── ZERO_AREA ──
            if "ZERO_AREA" in checks_to_run:
                run_count += 1
                zero_area = [
                    f.index for f in bm.faces if f.calc_area() < EPSILON
                ]
                passed = len(zero_area) == 0
                if passed:
                    passed_count += 1
                else:
                    blocking_issues.append(
                        f"{len(zero_area)} zero-area face(s)"
                    )
                check_results["ZERO_AREA"] = {
                    "passed": passed,
                    "count": len(zero_area),
                    "indices": zero_area[:50],
                    "detail": (
                        "No zero-area faces"
                        if passed
                        else f"{len(zero_area)} faces with near-zero area"
                    ),
                }

            # ── NGONS ──
            if "NGONS" in checks_to_run:
                run_count += 1
                ngons = [
                    f.index for f in bm.faces if len(f.verts) > 4
                ]
                # N-gons are not strictly blocking but noteworthy
                passed = len(ngons) == 0
                if passed:
                    passed_count += 1
                check_results["NGONS"] = {
                    "passed": passed,
                    "count": len(ngons),
                    "indices": ngons[:50],
                    "percentage": (
                        round(len(ngons) / total_faces * 100, 2)
                        if total_faces > 0
                        else 0
                    ),
                    "detail": (
                        "No n-gons (all faces are tris or quads)"
                        if passed
                        else f"{len(ngons)} n-gon(s) ({round(len(ngons) / total_faces * 100, 1)}% of faces)"
                    ),
                }

            # ── TRIS ──
            if "TRIS" in checks_to_run:
                run_count += 1
                tris = [
                    f.index for f in bm.faces if len(f.verts) == 3
                ]
                # Tris are fine for game engines, just informational
                passed = True  # Tris are not a failure
                passed_count += 1
                check_results["TRIS"] = {
                    "passed": passed,
                    "count": len(tris),
                    "percentage": (
                        round(len(tris) / total_faces * 100, 2)
                        if total_faces > 0
                        else 0
                    ),
                    "detail": (
                        f"{len(tris)} triangle(s) "
                        f"({round(len(tris) / total_faces * 100, 1)}% of faces)"
                        if total_faces > 0
                        else "No faces"
                    ),
                }

            # ── UV_COVERAGE ──
            if "UV_COVERAGE" in checks_to_run:
                run_count += 1
                uv_layers = obj.data.uv_layers
                has_uv = len(uv_layers) > 0

                uv_coverage_ratio = 0.0

                if has_uv:
                    uv_layer = bm.loops.layers.uv.active
                    if uv_layer:
                        # Check how many faces have non-degenerate UVs
                        faces_with_uv = 0
                        for face in bm.faces:
                            uvs = [loop[uv_layer].uv for loop in face.loops]
                            # Non-degenerate if not all UVs are identical
                            if len(set((round(uv.x, 6), round(uv.y, 6)) for uv in uvs)) > 1:
                                faces_with_uv += 1
                        uv_coverage_ratio = (
                            faces_with_uv / total_faces if total_faces > 0 else 0.0
                        )

                passed = has_uv and uv_coverage_ratio > 0.5
                if passed:
                    passed_count += 1
                else:
                    if not has_uv:
                        blocking_issues.append("No UV layer found")

                check_results["UV_COVERAGE"] = {
                    "passed": passed,
                    "has_uv_layer": has_uv,
                    "uv_layer_count": len(uv_layers),
                    "coverage_ratio": round(uv_coverage_ratio, 4),
                    "detail": (
                        f"UV coverage: {round(uv_coverage_ratio * 100, 1)}%"
                        if has_uv
                        else "No UV layer present"
                    ),
                }

            # ── UV_OVERLAP ──
            if "UV_OVERLAP" in checks_to_run:
                run_count += 1
                # Simple overlap detection: check if any UV triangles
                # share the same 2D bounding box region.
                # Full overlap detection is expensive; we use a sampling approach.
                uv_layers = obj.data.uv_layers
                has_uv = len(uv_layers) > 0
                overlap_detected = False
                overlap_estimate = 0

                if has_uv:
                    uv_layer = bm.loops.layers.uv.active
                    if uv_layer and total_faces > 0:
                        # Grid-based overlap estimation
                        grid_size = 64
                        grid: dict[tuple[int, int], list[int]] = {}
                        for face in bm.faces:
                            uvs = [loop[uv_layer].uv for loop in face.loops]
                            u_vals = [uv.x for uv in uvs]
                            v_vals = [uv.y for uv in uvs]
                            # Map UV center to grid cell
                            cu = int(
                                (sum(u_vals) / len(u_vals)) * grid_size
                            ) % grid_size
                            cv = int(
                                (sum(v_vals) / len(v_vals)) * grid_size
                            ) % grid_size
                            key = (cu, cv)
                            if key not in grid:
                                grid[key] = []
                            grid[key].append(face.index)

                        # Count cells with multiple faces that have
                        # similar UV footprints (crude overlap proxy)
                        for cell_faces in grid.values():
                            if len(cell_faces) > 3:
                                overlap_estimate += len(cell_faces) - 1

                        overlap_detected = overlap_estimate > total_faces * 0.05

                passed = not overlap_detected
                if passed:
                    passed_count += 1
                check_results["UV_OVERLAP"] = {
                    "passed": passed,
                    "has_uv_layer": has_uv,
                    "estimated_overlapping_faces": overlap_estimate,
                    "detail": (
                        "No significant UV overlap detected"
                        if passed
                        else f"Estimated {overlap_estimate} overlapping UV face(s)"
                    ),
                }

            # ── MATERIAL_ASSIGNMENT ──
            if "MATERIAL_ASSIGNMENT" in checks_to_run:
                run_count += 1
                mat_count = len(obj.data.materials)
                unassigned = []
                invalid_idx = []

                if mat_count == 0:
                    # No materials at all
                    unassigned = list(range(total_faces))
                else:
                    for face in bm.faces:
                        if face.material_index >= mat_count:
                            invalid_idx.append(face.index)
                        elif obj.data.materials[face.material_index] is None:
                            unassigned.append(face.index)

                passed = len(unassigned) == 0 and len(invalid_idx) == 0
                if passed:
                    passed_count += 1
                check_results["MATERIAL_ASSIGNMENT"] = {
                    "passed": passed,
                    "material_slot_count": mat_count,
                    "unassigned_faces": len(unassigned),
                    "invalid_index_faces": len(invalid_idx),
                    "detail": (
                        f"All {total_faces} faces have valid material assignments"
                        if passed
                        else (
                            f"{len(unassigned)} unassigned, "
                            f"{len(invalid_idx)} invalid material index"
                        )
                    ),
                }

            # ── SCALE_APPLIED ──
            if "SCALE_APPLIED" in checks_to_run:
                run_count += 1
                scale = obj.scale
                is_unit = all(
                    abs(s - 1.0) < 1e-4 for s in scale
                )
                passed = is_unit
                if passed:
                    passed_count += 1
                else:
                    blocking_issues.append(
                        f"Unapplied scale: ({scale.x:.4f}, {scale.y:.4f}, {scale.z:.4f})"
                    )
                check_results["SCALE_APPLIED"] = {
                    "passed": passed,
                    "scale": [round(scale.x, 4), round(scale.y, 4), round(scale.z, 4)],
                    "detail": (
                        "Scale is (1, 1, 1)"
                        if passed
                        else f"Scale is ({scale.x:.4f}, {scale.y:.4f}, {scale.z:.4f})"
                    ),
                }

            # ── ORIGIN_CENTERED ──
            if "ORIGIN_CENTERED" in checks_to_run:
                run_count += 1
                # Check if origin is near the geometry center
                if total_verts > 0:
                    bbox = [Vector(c) for c in obj.bound_box]
                    geo_center = sum(bbox, Vector()) / len(bbox)
                    origin_local = Vector((0, 0, 0))
                    offset = (geo_center - origin_local).length
                    # Relative to bbox diagonal
                    bbox_min = Vector((
                        min(b.x for b in bbox),
                        min(b.y for b in bbox),
                        min(b.z for b in bbox),
                    ))
                    bbox_max = Vector((
                        max(b.x for b in bbox),
                        max(b.y for b in bbox),
                        max(b.z for b in bbox),
                    ))
                    diagonal = (bbox_max - bbox_min).length
                    relative_offset = offset / diagonal if diagonal > 0 else 0.0
                    passed = relative_offset < 0.1  # Within 10% of bbox diagonal
                else:
                    offset = 0.0
                    relative_offset = 0.0
                    passed = True

                if passed:
                    passed_count += 1
                check_results["ORIGIN_CENTERED"] = {
                    "passed": passed,
                    "offset": round(offset, 6),
                    "relative_offset": round(relative_offset, 4),
                    "detail": (
                        f"Origin is {round(relative_offset * 100, 1)}% of bbox diagonal from geometry center"
                    ),
                }

            # ── Overall scoring ──
            overall_score = passed_count / run_count if run_count > 0 else 1.0

            # Export-ready: no blocking issues and score >= 0.7
            export_ready = len(blocking_issues) == 0 and overall_score >= 0.7

            return {
                "success": True,
                "object": object_name,
                "overall_score": round(overall_score, 3),
                "checks_run": run_count,
                "checks_passed": passed_count,
                "export_ready": export_ready,
                "blocking_issues": blocking_issues,
                "mesh_stats": {
                    "vertices": total_verts,
                    "edges": total_edges,
                    "faces": total_faces,
                },
                "results": check_results,
            }
        finally:
            bm.free()


    def _handle_mesh_check_watertight(self, params: dict) -> dict:
        """3D-print-focused watertightness check: manifold, single shell, positive volume.

        ``validate_mesh_quality`` covers export-readiness broadly (UVs,
        materials, n-gons, ...); this is the narrower "will this hold water /
        slice cleanly" check - the same three criteria (0 open edges, 0
        non-manifold edges, exactly 1 shell) used throughout this project's
        CNC/3D-printing workflow, in one call instead of hand-rolled bmesh
        connected-component scripts.
        """
        import bmesh

        object_name = require_param(params, "object_name", str)
        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.transform(obj.matrix_world)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            non_manifold = [e.index for e in bm.edges if not e.is_manifold]
            boundary = [e.index for e in bm.edges if len(e.link_faces) == 1]

            # Connected-component count via BFS over vertex adjacency.
            visited: set[int] = set()
            shell_sizes: list[int] = []
            for start in bm.verts:
                if start.index in visited:
                    continue
                stack = [start]
                visited.add(start.index)
                count = 0
                while stack:
                    v = stack.pop()
                    count += 1
                    for e in v.link_edges:
                        other = e.other_vert(v)
                        if other.index not in visited:
                            visited.add(other.index)
                            stack.append(other)
                shell_sizes.append(count)
            shell_sizes.sort(reverse=True)

            bmesh.ops.triangulate(bm, faces=bm.faces[:])
            volume = 0.0
            for face in bm.faces:
                v0, v1, v2 = (v.co for v in face.verts)
                volume += v0.dot(v1.cross(v2)) / 6.0

            watertight = (
                len(non_manifold) == 0
                and len(boundary) == 0
                and len(shell_sizes) == 1
                and volume > 0
            )

            return {
                "success": True,
                "object": object_name,
                "watertight": watertight,
                "non_manifold_edge_count": len(non_manifold),
                "non_manifold_edge_indices": non_manifold[:50],
                "boundary_edge_count": len(boundary),
                "boundary_edge_indices": boundary[:50],
                "shell_count": len(shell_sizes),
                "shell_vertex_counts": shell_sizes[:10],
                "signed_volume": round(volume, 6),
            }
        finally:
            bm.free()

    def _handle_mesh_bake_heightmap(self, params: dict) -> dict:
        """Rasterize an object's top surface into a 2D height grid via raycasting.

        Casts one ray straight down per grid cell across an XY box, recording
        the world-Z of the first hit (or ``miss_value`` if the ray misses
        entirely). This is the standard first step for isolating or replacing
        one specific inscribed region (text, a logo, ...) on a complex organic
        relief that has no per-region objects to select directly: bake once,
        then threshold/connected-component the array in ordinary numpy/scipy
        code outside Blender to find the region's pixel mask and bounding box.

        The grid is written to ``output_path`` as a ``.npy`` file rather than
        returned inline - at any usable resolution (a few hundred px upward)
        the array is megabytes, too large to round-trip as JSON over the
        socket, and .npy is the natural format for the numpy analysis this
        feeds into.
        """
        import numpy as np
        from mathutils import Vector
        from mathutils.bvhtree import BVHTree
        import bmesh

        object_name = require_param(params, "object_name", str)
        bb_min = validate_vector3(require_param(params, "bb_min", list), "bb_min")
        bb_max = validate_vector3(require_param(params, "bb_max", list), "bb_max")
        output_path = validate_filepath(require_param(params, "output_path", str), "output_path")
        resolution_x = int(params.get("resolution_x", params.get("resolution", 512)))
        resolution_y = int(params.get("resolution_y", params.get("resolution", 512)))
        miss_value = float(params.get("miss_value", 0.0))
        ray_start_z = params.get("ray_start_z")

        if resolution_x < 1 or resolution_y < 1:
            raise ValidationError("resolution_x/resolution_y must be >= 1")
        if resolution_x > 4096 or resolution_y > 4096:
            raise ValidationError(
                "resolution_x/resolution_y capped at 4096 (Python-loop raycasting - "
                "bake a smaller region or lower resolution and upsample downstream if you need more)"
            )
        if bb_max[0] <= bb_min[0] or bb_max[1] <= bb_min[1]:
            raise ValidationError("bb_max must be greater than bb_min in x and y")

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.transform(obj.matrix_world)
            bvh = BVHTree.FromBMesh(bm)
        finally:
            bm.free()
            eval_obj.to_mesh_clear()

        start_z = float(ray_start_z) if ray_start_z is not None else bb_max[2] + 5.0
        ray_len = start_z - (bb_min[2] - 5.0)
        direction = Vector((0.0, 0.0, -1.0))

        heights = np.full((resolution_y, resolution_x), miss_value, dtype=np.float64)
        dx = (bb_max[0] - bb_min[0]) / max(resolution_x - 1, 1)
        dy = (bb_max[1] - bb_min[1]) / max(resolution_y - 1, 1)
        hit_count = 0
        for j in range(resolution_y):
            y = bb_min[1] + j * dy
            for i in range(resolution_x):
                x = bb_min[0] + i * dx
                origin = Vector((x, y, start_z))
                location, _normal, _index, _dist = bvh.ray_cast(origin, direction, ray_len)
                if location is not None:
                    heights[j, i] = location.z
                    hit_count += 1

        actual_path = output_path if output_path.endswith(".npy") else output_path + ".npy"
        np.save(output_path, heights)

        hit_mask = heights != miss_value
        return {
            "success": True,
            "output_path": actual_path,
            "object": object_name,
            "shape": [resolution_y, resolution_x],
            "bb_min": list(bb_min),
            "bb_max": list(bb_max),
            "hit_ratio": round(hit_count / (resolution_x * resolution_y), 4),
            "height_min": float(heights[hit_mask].min()) if hit_count else None,
            "height_max": float(heights[hit_mask].max()) if hit_count else None,
        }

    # ========== Collection & System Handlers ==========

