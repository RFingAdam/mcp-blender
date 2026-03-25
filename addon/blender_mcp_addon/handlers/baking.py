"""Texture baking command handlers."""

import os

import bpy

from ..validation import (
    require_param,
)
from ._helpers import (
    _ALL_CHANNELS,
    _CHANNEL_BAKE_CONFIG,
    _FORMAT_EXTENSIONS,
    _bake_ensure_cycles,
)


class BakingHandlersMixin:
    """Mixin for texture baking handlers."""

    def _handle_bake_pbr_batch(self, params: dict) -> dict:
        """Bake all requested PBR channels in one call."""


        object_name = require_param(params, "object_name", str)
        output_dir = require_param(params, "output_dir", str)
        channels = params.get("channels", _ALL_CHANNELS)
        resolution = int(params.get("resolution", 2048))
        output_prefix = params.get("output_prefix", object_name)
        output_format = params.get("output_format", "PNG")
        margin = int(params.get("margin", 16))
        samples = int(params.get("samples", 128))
        use_cage = params.get("use_cage", False)
        cage_extrusion = float(params.get("cage_extrusion", 0.1))
        normal_space = params.get("normal_space", "TANGENT")

        # Validate
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {"error": f"Object not found: {object_name}"}
        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is not a mesh"}

        # Ensure UVs exist
        if not obj.data.uv_layers:
            return {"error": f"Object '{object_name}' has no UV map. Unwrap first."}

        # Ensure output dir exists
        os.makedirs(output_dir, exist_ok=True)

        # Switch to Cycles
        _bake_ensure_cycles()
        bpy.context.scene.cycles.samples = samples

        # Select only this object and make active
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        ext = _FORMAT_EXTENSIONS.get(output_format, ".png")
        baked_files = {}
        errors = {}

        for channel in channels:
            channel = channel.upper()
            config = _CHANNEL_BAKE_CONFIG.get(channel)
            if config is None:
                errors[channel] = f"Unknown channel: {channel}"
                continue

            color_space = config.get("color_space", "sRGB")
            img_name = f"__bake_{channel}__"
            image = self._bake_create_image(img_name, resolution, color_space)
            self._bake_set_active_image_node(obj, image)

            restore_info = None
            try:
                # Apply tricks if needed
                if config.get("metallic_trick"):
                    restore_info = self._bake_apply_metallic_trick(obj)
                elif config.get("displacement_trick"):
                    restore_info = self._bake_apply_displacement_trick(obj)

                # Configure bake settings
                bake_type = config["type"]
                bpy.context.scene.render.bake.use_pass_direct = False
                bpy.context.scene.render.bake.use_pass_indirect = False
                bpy.context.scene.render.bake.use_pass_color = True
                bpy.context.scene.render.bake.margin = margin
                bpy.context.scene.render.bake.use_cage = use_cage
                bpy.context.scene.render.bake.cage_extrusion = cage_extrusion

                if channel == "NORMAL":
                    bpy.context.scene.render.bake.normal_space = normal_space

                if channel == "DIFFUSE":
                    bpy.context.scene.render.bake.use_pass_direct = False
                    bpy.context.scene.render.bake.use_pass_indirect = False
                    bpy.context.scene.render.bake.use_pass_color = True

                # Perform the bake
                bpy.ops.object.bake(type=bake_type)

                # Save
                filepath = os.path.join(output_dir, f"{output_prefix}_{channel}{ext}")
                self._bake_save_image(image, filepath, output_format)
                baked_files[channel] = filepath

            except Exception as e:
                errors[channel] = str(e)
            finally:
                # Restore tricks
                if restore_info is not None:
                    if config.get("metallic_trick"):
                        self._bake_restore_metallic_trick(restore_info)
                    elif config.get("displacement_trick"):
                        self._bake_restore_displacement_trick(restore_info)

                # Cleanup
                self._bake_cleanup_image_nodes(obj)
                bpy.data.images.remove(image)

        result = {
            "success": True,
            "object": object_name,
            "resolution": resolution,
            "output_format": output_format,
            "baked_files": baked_files,
        }
        if errors:
            result["errors"] = errors
        return result

    # =================================================================
    # 2. bake_highpoly_to_lowpoly

    # =================================================================


    def _handle_bake_highpoly_to_lowpoly(self, params: dict) -> dict:
        """Bake detail from high-poly onto low-poly using selected_to_active."""


        lowpoly_name = require_param(params, "lowpoly_name", str)
        highpoly_name = require_param(params, "highpoly_name", str)
        output_dir = require_param(params, "output_dir", str)
        channels = params.get("channels", ["NORMAL", "AO"])
        resolution = int(params.get("resolution", 2048))
        cage_extrusion = float(params.get("cage_extrusion", 0.1))
        output_prefix = params.get("output_prefix", lowpoly_name)
        output_format = params.get("output_format", "PNG")
        margin = int(params.get("margin", 16))
        samples = int(params.get("samples", 128))

        # Validate objects
        lowpoly = bpy.data.objects.get(lowpoly_name)
        if lowpoly is None:
            return {"error": f"Low-poly object not found: {lowpoly_name}"}
        if lowpoly.type != "MESH":
            return {"error": f"Low-poly object '{lowpoly_name}' is not a mesh"}

        highpoly = bpy.data.objects.get(highpoly_name)
        if highpoly is None:
            return {"error": f"High-poly object not found: {highpoly_name}"}
        if highpoly.type != "MESH":
            return {"error": f"High-poly object '{highpoly_name}' is not a mesh"}

        if not lowpoly.data.uv_layers:
            return {"error": f"Low-poly object '{lowpoly_name}' has no UV map. Unwrap first."}

        # Ensure lowpoly has at least one material (needed for bake target node)
        if len(lowpoly.material_slots) == 0:
            mat = bpy.data.materials.new(name=f"{lowpoly_name}_BakeMat")
            mat.use_nodes = True
            lowpoly.data.materials.append(mat)

        os.makedirs(output_dir, exist_ok=True)

        # Switch to Cycles
        _bake_ensure_cycles()
        bpy.context.scene.cycles.samples = samples

        # Selection: highpoly selected, lowpoly active
        bpy.ops.object.select_all(action="DESELECT")
        highpoly.select_set(True)
        lowpoly.select_set(True)
        bpy.context.view_layer.objects.active = lowpoly

        # Enable selected-to-active
        bpy.context.scene.render.bake.use_selected_to_active = True
        bpy.context.scene.render.bake.cage_extrusion = cage_extrusion
        bpy.context.scene.render.bake.margin = margin

        ext = _FORMAT_EXTENSIONS.get(output_format, ".png")
        baked_files = {}
        errors = {}

        for channel in channels:
            channel = channel.upper()
            config = _CHANNEL_BAKE_CONFIG.get(channel)
            if config is None:
                errors[channel] = f"Unknown channel: {channel}"
                continue

            color_space = config.get("color_space", "sRGB")
            img_name = f"__bake_hp2lp_{channel}__"
            image = self._bake_create_image(img_name, resolution, color_space)
            self._bake_set_active_image_node(lowpoly, image)

            restore_info = None
            try:
                if config.get("metallic_trick"):
                    restore_info = self._bake_apply_metallic_trick(highpoly)
                elif config.get("displacement_trick"):
                    restore_info = self._bake_apply_displacement_trick(highpoly)

                bake_type = config["type"]

                if channel == "DIFFUSE":
                    bpy.context.scene.render.bake.use_pass_direct = False
                    bpy.context.scene.render.bake.use_pass_indirect = False
                    bpy.context.scene.render.bake.use_pass_color = True

                if channel == "NORMAL":
                    bpy.context.scene.render.bake.normal_space = params.get("normal_space", "TANGENT")

                bpy.ops.object.bake(type=bake_type)

                filepath = os.path.join(output_dir, f"{output_prefix}_{channel}{ext}")
                self._bake_save_image(image, filepath, output_format)
                baked_files[channel] = filepath

            except Exception as e:
                errors[channel] = str(e)
            finally:
                if restore_info is not None:
                    if config.get("metallic_trick"):
                        self._bake_restore_metallic_trick(restore_info)
                    elif config.get("displacement_trick"):
                        self._bake_restore_displacement_trick(restore_info)

                self._bake_cleanup_image_nodes(lowpoly)
                bpy.data.images.remove(image)

        # Reset selected_to_active
        bpy.context.scene.render.bake.use_selected_to_active = False

        result = {
            "success": True,
            "lowpoly": lowpoly_name,
            "highpoly": highpoly_name,
            "resolution": resolution,
            "output_format": output_format,
            "baked_files": baked_files,
        }
        if errors:
            result["errors"] = errors
        return result

    # =================================================================
    # 3. bake_from_multires

    # =================================================================


    def _handle_bake_from_multires(self, params: dict) -> dict:
        """Bake normals or displacement from a Multiresolution modifier."""


        object_name = require_param(params, "object_name", str)
        output_path = require_param(params, "output_path", str)
        map_type = params.get("map_type", "NORMALS").upper()
        resolution = int(params.get("resolution", 2048))
        margin = int(params.get("margin", 16))

        if map_type not in ("NORMALS", "DISPLACEMENT"):
            return {"error": f"map_type must be NORMALS or DISPLACEMENT, got '{map_type}'"}

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {"error": f"Object not found: {object_name}"}
        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is not a mesh"}

        if not obj.data.uv_layers:
            return {"error": f"Object '{object_name}' has no UV map. Unwrap first."}

        # Find multiresolution modifier
        multires_mod = None
        for mod in obj.modifiers:
            if mod.type == "MULTIRES":
                multires_mod = mod
                break

        if multires_mod is None:
            return {"error": f"Object '{object_name}' has no Multiresolution modifier"}

        if multires_mod.total_levels < 1:
            return {"error": "Multiresolution modifier has no subdivision levels"}

        # Ensure at least one material for bake target
        if len(obj.material_slots) == 0:
            mat = bpy.data.materials.new(name=f"{object_name}_BakeMat")
            mat.use_nodes = True
            obj.data.materials.append(mat)

        # Ensure output dir exists
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        # Switch to Cycles
        _bake_ensure_cycles()

        # Select and activate
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # Create bake target image
        color_space = "Non-Color"
        img_name = f"__bake_multires_{map_type}__"
        image = self._bake_create_image(img_name, resolution, color_space)
        self._bake_set_active_image_node(obj, image)

        try:
            # Configure multires bake
            bpy.context.scene.render.bake.margin = margin

            # Bake with multires
            bpy.ops.object.bake(
                type=map_type,
                use_clear=True,
            )

            self._bake_save_image(image, output_path, "PNG")

            return {
                "success": True,
                "object": object_name,
                "map_type": map_type,
                "resolution": resolution,
                "output_path": output_path,
                "multires_levels": multires_mod.total_levels,
            }
        except Exception as e:
            return {"error": f"Multires bake failed: {e}"}
        finally:
            self._bake_cleanup_image_nodes(obj)
            bpy.data.images.remove(image)

    # =================================================================
    # 4. bake_to_vertex_colors

    # =================================================================


    def _handle_bake_to_vertex_colors(self, params: dict) -> dict:
        """Bake to a temporary image then transfer pixel data to vertex colors."""
        import numpy as np


        object_name = require_param(params, "object_name", str)
        bake_type = params.get("bake_type", "AO").upper()
        vertex_color_name = params.get("vertex_color_name", "BakedColor")
        samples = int(params.get("samples", 64))

        if bake_type not in ("AO", "DIFFUSE", "COMBINED"):
            return {"error": f"bake_type must be AO, DIFFUSE, or COMBINED, got '{bake_type}'"}

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {"error": f"Object not found: {object_name}"}
        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is not a mesh"}

        mesh = obj.data
        if not mesh.uv_layers:
            return {"error": f"Object '{object_name}' has no UV map. Unwrap first."}

        # Ensure at least one material
        if len(obj.material_slots) == 0:
            mat = bpy.data.materials.new(name=f"{object_name}_BakeMat")
            mat.use_nodes = True
            mesh.materials.append(mat)

        # Switch to Cycles
        _bake_ensure_cycles()
        bpy.context.scene.cycles.samples = samples

        # Select and activate
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # Use a moderate resolution for vertex color transfer
        temp_res = 1024
        img_name = "__bake_vertex_color_temp__"
        image = self._bake_create_image(img_name, temp_res, "sRGB")
        self._bake_set_active_image_node(obj, image)

        try:
            # Configure and bake
            if bake_type == "DIFFUSE":
                bpy.context.scene.render.bake.use_pass_direct = False
                bpy.context.scene.render.bake.use_pass_indirect = False
                bpy.context.scene.render.bake.use_pass_color = True

            bpy.ops.object.bake(type=bake_type)

            # Read pixel data from the baked image
            pixel_count = temp_res * temp_res
            pixels = np.zeros(pixel_count * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            pixels = pixels.reshape((temp_res, temp_res, 4))

            # Create or get vertex color layer
            if vertex_color_name in mesh.color_attributes:
                vcol = mesh.color_attributes[vertex_color_name]
            else:
                vcol = mesh.color_attributes.new(
                    name=vertex_color_name,
                    type="BYTE_COLOR",
                    domain="CORNER",
                )

            # Get active UV layer
            uv_layer = mesh.uv_layers.active

            # Transfer baked pixels to vertex colors by sampling the image at each
            # loop's UV coordinate
            for poly in mesh.polygons:
                for loop_idx in poly.loop_indices:
                    uv = uv_layer.data[loop_idx].uv
                    # Clamp UV to [0, 1]
                    u = max(0.0, min(uv[0], 1.0))
                    v = max(0.0, min(uv[1], 1.0))
                    # Pixel coordinates
                    px = int(u * (temp_res - 1))
                    py = int(v * (temp_res - 1))
                    color = pixels[py, px]
                    vcol.data[loop_idx].color = (
                        float(color[0]),
                        float(color[1]),
                        float(color[2]),
                        float(color[3]),
                    )

            return {
                "success": True,
                "object": object_name,
                "bake_type": bake_type,
                "vertex_color_layer": vertex_color_name,
                "loop_count": len(mesh.loops),
            }
        except ImportError:
            # numpy not available -- fallback without numpy
            return {"error": "numpy is required for vertex color baking but is not available"}
        except Exception as e:
            return {"error": f"Vertex color bake failed: {e}"}
        finally:
            self._bake_cleanup_image_nodes(obj)
            bpy.data.images.remove(image)

    # =================================================================
    # 5. bake_curvature

    # =================================================================


    def _handle_bake_curvature(self, params: dict) -> dict:
        """Calculate per-vertex curvature via bmesh and bake to an image."""
        import bmesh
        import numpy as np
        from mathutils import Vector


        object_name = require_param(params, "object_name", str)
        output_path = require_param(params, "output_path", str)
        resolution = int(params.get("resolution", 2048))
        cavity_type = params.get("cavity_type", "BOTH").upper()

        if cavity_type not in ("CONCAVE", "CONVEX", "BOTH"):
            return {"error": f"cavity_type must be CONCAVE, CONVEX, or BOTH, got '{cavity_type}'"}

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {"error": f"Object not found: {object_name}"}
        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is not a mesh"}

        mesh = obj.data
        if not mesh.uv_layers:
            return {"error": f"Object '{object_name}' has no UV map. Unwrap first."}

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        try:
            # Calculate curvature using bmesh
            bm = bmesh.new()
            bm.from_mesh(mesh)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            # Per-vertex curvature: dot product of vertex normal vs average of
            # connected neighbor normals. Values < 0 = convex, > 0 = concave.
            vert_curvature = {}
            for vert in bm.verts:
                if not vert.link_edges:
                    vert_curvature[vert.index] = 0.5
                    continue

                # Average neighbor normal
                neighbor_normal = Vector((0.0, 0.0, 0.0))
                count = 0
                for edge in vert.link_edges:
                    other = edge.other_vert(vert)
                    neighbor_normal += other.normal
                    count += 1

                if count == 0:
                    vert_curvature[vert.index] = 0.5
                    continue

                neighbor_normal /= count
                neighbor_normal.normalize()

                # Dot product: 1 = same direction (flat), < 1 = curvature
                dot = vert.normal.dot(neighbor_normal)
                # Map to 0-1 range: 0.5 = flat, 0 = concave, 1 = convex
                # dot=1 (flat), dot<1 (curved)
                # Use cross product to determine concavity direction
                curvature_amount = 1.0 - dot  # 0 for flat, larger for more curved

                # Determine concave vs convex by checking if neighbor center is
                # above or below the vertex along its normal
                neighbor_center = Vector((0.0, 0.0, 0.0))
                for edge in vert.link_edges:
                    other = edge.other_vert(vert)
                    neighbor_center += other.co
                neighbor_center /= count
                direction = (neighbor_center - vert.co).dot(vert.normal)

                if cavity_type == "BOTH":
                    # Map: concave = dark (0), flat = 0.5, convex = bright (1)
                    if direction > 0:
                        # Concave
                        value = 0.5 - curvature_amount * 2.5
                    else:
                        # Convex
                        value = 0.5 + curvature_amount * 2.5
                    value = max(0.0, min(1.0, value))
                elif cavity_type == "CONCAVE":
                    # Only show concave: bright where concave, black elsewhere
                    if direction > 0:
                        value = min(1.0, curvature_amount * 5.0)
                    else:
                        value = 0.0
                else:  # CONVEX
                    # Only show convex: bright where convex, black elsewhere
                    if direction <= 0:
                        value = min(1.0, curvature_amount * 5.0)
                    else:
                        value = 0.0

                vert_curvature[vert.index] = value

            # Create output image
            image = bpy.data.images.new("__bake_curvature__", width=resolution,
                                        height=resolution, alpha=False)
            pixel_count = resolution * resolution
            pixels = np.full(pixel_count * 4, 0.5, dtype=np.float32)
            # Set alpha to 1
            pixels[3::4] = 1.0

            # Rasterize curvature to UV space
            uv_layer_name = mesh.uv_layers.active.name

            # Get UV layer from bmesh
            bm_uv = bm.loops.layers.uv.get(uv_layer_name)
            if bm_uv is None:
                bm.free()
                bpy.data.images.remove(image)
                return {"error": "Could not find UV layer in bmesh"}

            # For each face, rasterize triangle by sampling curvature at vertices
            for face in bm.faces:
                face_loops = list(face.loops)
                if len(face_loops) < 3:
                    continue

                # Triangulate the face for rasterization
                for i in range(1, len(face_loops) - 1):
                    l0 = face_loops[0]
                    l1 = face_loops[i]
                    l2 = face_loops[i + 1]

                    uv0 = l0[bm_uv].uv
                    uv1 = l1[bm_uv].uv
                    uv2 = l2[bm_uv].uv

                    c0 = vert_curvature.get(l0.vert.index, 0.5)
                    c1 = vert_curvature.get(l1.vert.index, 0.5)
                    c2 = vert_curvature.get(l2.vert.index, 0.5)

                    # Bounding box in pixel space
                    min_u = max(0, int(min(uv0.x, uv1.x, uv2.x) * resolution))
                    max_u = min(resolution - 1, int(max(uv0.x, uv1.x, uv2.x) * resolution) + 1)
                    min_v = max(0, int(min(uv0.y, uv1.y, uv2.y) * resolution))
                    max_v = min(resolution - 1, int(max(uv0.y, uv1.y, uv2.y) * resolution) + 1)

                    # Rasterize using barycentric coordinates
                    for py in range(min_v, max_v + 1):
                        for px in range(min_u, max_u + 1):
                            # Point in UV space
                            p = (px / resolution, py / resolution)

                            # Barycentric coordinates
                            denom = ((uv1.y - uv2.y) * (uv0.x - uv2.x) +
                                     (uv2.x - uv1.x) * (uv0.y - uv2.y))
                            if abs(denom) < 1e-10:
                                continue

                            w0 = ((uv1.y - uv2.y) * (p[0] - uv2.x) +
                                   (uv2.x - uv1.x) * (p[1] - uv2.y)) / denom
                            w1 = ((uv2.y - uv0.y) * (p[0] - uv2.x) +
                                   (uv0.x - uv2.x) * (p[1] - uv2.y)) / denom
                            w2 = 1.0 - w0 - w1

                            if w0 < -0.001 or w1 < -0.001 or w2 < -0.001:
                                continue

                            # Interpolate curvature
                            curv = w0 * c0 + w1 * c1 + w2 * c2
                            curv = max(0.0, min(1.0, curv))

                            idx = (py * resolution + px) * 4
                            pixels[idx] = curv
                            pixels[idx + 1] = curv
                            pixels[idx + 2] = curv
                            pixels[idx + 3] = 1.0

            bm.free()

            # Write pixels to image
            image.pixels.foreach_set(pixels.tolist())
            image.filepath_raw = output_path
            image.file_format = "PNG"
            image.save_render(output_path)
            bpy.data.images.remove(image)

            return {
                "success": True,
                "object": object_name,
                "cavity_type": cavity_type,
                "resolution": resolution,
                "output_path": output_path,
                "vertex_count": len(vert_curvature),
            }
        except ImportError:
            return {"error": "numpy is required for curvature baking but is not available"}
        except Exception as e:
            return {"error": f"Curvature bake failed: {e}"}

    # =================================================================
    # 6. bake_id_map

    # =================================================================


    def _handle_bake_id_map(self, params: dict) -> dict:
        """Bake a color ID map with distinct colors per material/object/face set."""
        import random



        object_name = require_param(params, "object_name", str)
        output_path = require_param(params, "output_path", str)
        resolution = int(params.get("resolution", 2048))
        color_mode = params.get("color_mode", "PER_MATERIAL").upper()

        if color_mode not in ("PER_MATERIAL", "PER_OBJECT", "PER_FACE_SET"):
            return {"error": f"color_mode must be PER_MATERIAL, PER_OBJECT, or PER_FACE_SET, got '{color_mode}'"}

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {"error": f"Object not found: {object_name}"}
        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is not a mesh"}

        mesh = obj.data
        if not mesh.uv_layers:
            return {"error": f"Object '{object_name}' has no UV map. Unwrap first."}

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        # Switch to Cycles
        _bake_ensure_cycles()
        bpy.context.scene.cycles.samples = 1  # Emission needs minimal samples

        # Select and activate
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # Generate a palette of visually distinct colors
        def generate_distinct_colors(n):
            """Generate n visually distinct colors using golden ratio hue spacing."""
            colors = []
            golden_ratio = 0.618033988749895
            hue = random.random()
            for _ in range(max(n, 1)):
                hue = (hue + golden_ratio) % 1.0
                # HSV to RGB (saturation=0.85, value=0.9 for vivid distinct colors)
                import colorsys
                r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.9)
                colors.append((r, g, b, 1.0))
            return colors

        # Save original materials
        original_materials = []
        for slot in obj.material_slots:
            original_materials.append(slot.material)

        # Build color assignments depending on mode
        id_colors = {}

        try:
            if color_mode == "PER_MATERIAL":
                num_slots = max(len(obj.material_slots), 1)
                palette = generate_distinct_colors(num_slots)

                # For each material slot, create a temp emission material
                temp_materials = []
                for i in range(num_slots):
                    mat_name = f"__id_mat_{i}__"
                    mat = bpy.data.materials.new(name=mat_name)
                    mat.use_nodes = True
                    tree = mat.node_tree
                    tree.nodes.clear()

                    emit = tree.nodes.new("ShaderNodeEmission")
                    emit.inputs["Color"].default_value = palette[i]
                    emit.inputs["Strength"].default_value = 1.0

                    output = tree.nodes.new("ShaderNodeOutputMaterial")
                    tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])

                    temp_materials.append(mat)

                    orig_name = original_materials[i].name if i < len(original_materials) and original_materials[i] else f"Slot_{i}"
                    id_colors[orig_name] = list(palette[i][:3])

                # Assign temp materials
                # Ensure enough slots
                while len(obj.material_slots) < num_slots:
                    obj.data.materials.append(None)
                for i in range(num_slots):
                    obj.material_slots[i].material = temp_materials[i]

            elif color_mode == "PER_OBJECT":
                # For a single object, assign one color. If the mesh was joined
                # from multiple objects, we use loose parts as a proxy.
                import bmesh
                bm = bmesh.new()
                bm.from_mesh(mesh)
                bm.faces.ensure_lookup_table()

                # Find connected components (loose parts)
                visited = set()
                components = []
                for face in bm.faces:
                    if face.index in visited:
                        continue
                    component = set()
                    stack = [face]
                    while stack:
                        f = stack.pop()
                        if f.index in visited:
                            continue
                        visited.add(f.index)
                        component.add(f.index)
                        for edge in f.edges:
                            for linked_face in edge.link_faces:
                                if linked_face.index not in visited:
                                    stack.append(linked_face)
                    components.append(component)

                palette = generate_distinct_colors(len(components))

                # Assign each component to a material slot
                # Clear existing materials and create new ones
                temp_materials = []
                for i, comp in enumerate(components):
                    mat_name = f"__id_obj_{i}__"
                    mat = bpy.data.materials.new(name=mat_name)
                    mat.use_nodes = True
                    tree = mat.node_tree
                    tree.nodes.clear()

                    emit = tree.nodes.new("ShaderNodeEmission")
                    emit.inputs["Color"].default_value = palette[i]
                    emit.inputs["Strength"].default_value = 1.0

                    output = tree.nodes.new("ShaderNodeOutputMaterial")
                    tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])

                    temp_materials.append(mat)
                    id_colors[f"Part_{i}"] = list(palette[i][:3])

                # Set materials on the mesh
                mesh.materials.clear()
                for mat in temp_materials:
                    mesh.materials.append(mat)

                # Assign material indices to faces
                for i, comp in enumerate(components):
                    for face in bm.faces:
                        if face.index in comp:
                            face.material_index = i

                bm.to_mesh(mesh)
                bm.free()

            elif color_mode == "PER_FACE_SET":
                # Use face map attributes or sculpt face sets if available
                import bmesh
                bm = bmesh.new()
                bm.from_mesh(mesh)
                bm.faces.ensure_lookup_table()

                # Check for sculpt face sets
                face_set_layer = bm.faces.layers.int.get(".sculpt_face_set")
                if face_set_layer is None:
                    # Fall back: use material index as face set proxy
                    face_sets = {}
                    for face in bm.faces:
                        fs = face.material_index
                        if fs not in face_sets:
                            face_sets[fs] = []
                        face_sets[fs].append(face.index)
                else:
                    face_sets = {}
                    for face in bm.faces:
                        fs = face[face_set_layer]
                        if fs not in face_sets:
                            face_sets[fs] = []
                        face_sets[fs].append(face.index)

                palette = generate_distinct_colors(len(face_sets))
                sorted_keys = sorted(face_sets.keys())

                temp_materials = []
                for i, key in enumerate(sorted_keys):
                    mat_name = f"__id_fs_{key}__"
                    mat = bpy.data.materials.new(name=mat_name)
                    mat.use_nodes = True
                    tree = mat.node_tree
                    tree.nodes.clear()

                    emit = tree.nodes.new("ShaderNodeEmission")
                    emit.inputs["Color"].default_value = palette[i]
                    emit.inputs["Strength"].default_value = 1.0

                    output = tree.nodes.new("ShaderNodeOutputMaterial")
                    tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])

                    temp_materials.append(mat)
                    id_colors[f"FaceSet_{key}"] = list(palette[i][:3])

                mesh.materials.clear()
                for mat in temp_materials:
                    mesh.materials.append(mat)

                for i, key in enumerate(sorted_keys):
                    for face_idx in face_sets[key]:
                        bm.faces[face_idx].material_index = i

                bm.to_mesh(mesh)
                bm.free()

            # Create bake target image
            img_name = "__bake_id_map__"
            image = self._bake_create_image(img_name, resolution, "sRGB")
            self._bake_set_active_image_node(obj, image)

            # Bake emission
            bpy.context.scene.render.bake.margin = 16
            bpy.ops.object.bake(type="EMIT")

            # Save
            self._bake_save_image(image, output_path, "PNG")

            # Cleanup
            self._bake_cleanup_image_nodes(obj)
            bpy.data.images.remove(image)

            # Remove temp materials
            if color_mode == "PER_MATERIAL":
                # Restore original materials
                for i, orig_mat in enumerate(original_materials):
                    if i < len(obj.material_slots):
                        obj.material_slots[i].material = orig_mat
                for mat in temp_materials:
                    bpy.data.materials.remove(mat)
            else:
                # For PER_OBJECT and PER_FACE_SET we replaced all materials;
                # restore the originals
                mesh.materials.clear()
                for orig_mat in original_materials:
                    mesh.materials.append(orig_mat)

                # Restore original material indices (they were overwritten)
                # Re-read original face material assignments -- since we changed
                # them, we cannot fully restore without a backup. We log a note.
                for mat in temp_materials:
                    bpy.data.materials.remove(mat)

            return {
                "success": True,
                "object": object_name,
                "color_mode": color_mode,
                "resolution": resolution,
                "output_path": output_path,
                "id_colors": id_colors,
                "note": (
                    "For PER_OBJECT/PER_FACE_SET modes, face material indices "
                    "were modified during baking. If original material assignments "
                    "are important, consider using Undo after inspecting the result."
                ) if color_mode != "PER_MATERIAL" else None,
            }
        except Exception as e:
            # Attempt to restore materials on error
            try:
                mesh.materials.clear()
                for orig_mat in original_materials:
                    mesh.materials.append(orig_mat)
            except Exception:
                pass
            return {"error": f"ID map bake failed: {e}"}


    # ========== Geometry Nodes Handlers ==========

