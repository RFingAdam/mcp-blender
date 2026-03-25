"""Annotation and grease pencil command handlers."""

import math
import os

import bpy

from ..validation import (
    require_param,
    validate_color,
    validate_enum,
    validate_filepath,
    validate_vector3,
)
from ._helpers import _markup_with_compositor, _markup_with_pillow


class AnnotationHandlersMixin:
    """Mixin for annotation and grease pencil handlers."""

    def _handle_annotation_add(self, params: dict) -> dict:
        """Add 3D annotation strokes to an annotation layer."""
        points = require_param(params, "points", list)
        color = params.get("color", [1, 0, 0, 1])
        thickness = int(params.get("thickness", 3))
        layer_name = params.get("layer_name", "Annotations")

        if len(points) < 2:
            return {"error": "At least 2 points are required for a stroke"}

        # Validate color
        color = validate_color(color, "color")

        # Validate points
        validated_points = []
        for i, pt in enumerate(points):
            validated_points.append(validate_vector3(pt, f"points[{i}]"))

        # Get or create annotation grease pencil data
        scene = bpy.context.scene
        gpd = scene.grease_pencil
        if gpd is None:
            gpd = bpy.data.grease_pencils.new("Annotations")
            scene.grease_pencil = gpd

        # Get or create the layer
        gpl = gpd.layers.get(layer_name)
        if gpl is None:
            gpl = gpd.layers.new(layer_name, set_active=True)

        # Set layer color
        gpl.color = (color[0], color[1], color[2])

        # Set annotation line thickness on the layer
        gpl.thickness = thickness

        # Get or create a frame at the current frame
        current_frame = bpy.context.scene.frame_current
        gpf = None
        for frame in gpl.frames:
            if frame.frame_number == current_frame:
                gpf = frame
                break
        if gpf is None:
            gpf = gpl.frames.new(current_frame)

        # Create the stroke
        stroke = gpf.strokes.new()
        stroke.display_mode = '3DSPACE'
        stroke.line_width = thickness

        # Add points to the stroke
        stroke.points.add(len(validated_points))
        for i, pt in enumerate(validated_points):
            stroke.points[i].co = (pt[0], pt[1], pt[2])
            stroke.points[i].pressure = 1.0
            stroke.points[i].strength = color[3]

        return {
            "success": True,
            "layer": layer_name,
            "stroke_points": len(validated_points),
            "color": color,
            "thickness": thickness,
            "frame": current_frame,
        }


    def _handle_annotation_text(self, params: dict) -> dict:
        """Add a text object at a 3D location as an annotation."""
        text_content = require_param(params, "text", str)
        location = require_param(params, "location", list)
        size = float(params.get("size", 1.0))
        color = params.get("color", [1, 1, 1, 1])

        location = validate_vector3(location, "location")
        color = validate_color(color, "color")

        # Create a new text curve data block
        text_data = bpy.data.curves.new(name=f"Annotation_{text_content[:20]}", type='FONT')
        text_data.body = text_content
        text_data.size = size
        text_data.align_x = 'LEFT'
        text_data.align_y = 'BOTTOM'

        # Create the object
        text_obj = bpy.data.objects.new(name=f"Text_{text_content[:20]}", object_data=text_data)
        text_obj.location = (location[0], location[1], location[2])

        # Link to scene
        bpy.context.collection.objects.link(text_obj)

        # Create and assign a material with the specified color
        mat_name = f"AnnotationText_{text_content[:10]}"
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True

        # Set the Principled BSDF base color
        if mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    node.inputs["Base Color"].default_value = (
                        color[0], color[1], color[2], color[3]
                    )
                    # Make it emissive so it's always visible
                    node.inputs["Emission Color"].default_value = (
                        color[0], color[1], color[2], 1.0
                    )
                    node.inputs["Emission Strength"].default_value = 1.0
                    break

        text_obj.data.materials.append(mat)

        return {
            "success": True,
            "object": text_obj.name,
            "text": text_content,
            "location": location,
            "size": size,
            "color": color,
            "material": mat_name,
        }


    def _handle_annotation_dimension(self, params: dict) -> dict:
        """Add a dimension line between two points with distance measurement."""
        point_a = require_param(params, "point_a", list)
        point_b = require_param(params, "point_b", list)
        offset = float(params.get("offset", 0.5))
        units = params.get("units", "METERS")
        label_override = params.get("label")

        point_a = validate_vector3(point_a, "point_a")
        point_b = validate_vector3(point_b, "point_b")
        units = validate_enum(
            units, "units", ["METERS", "CM", "MM", "INCHES", "FEET"]
        )

        # Calculate distance
        dx = point_b[0] - point_a[0]
        dy = point_b[1] - point_a[1]
        dz = point_b[2] - point_a[2]
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)

        # Convert distance to requested units
        unit_factors = {
            "METERS": 1.0,
            "CM": 100.0,
            "MM": 1000.0,
            "INCHES": 39.3701,
            "FEET": 3.28084,
        }
        unit_suffixes = {
            "METERS": "m",
            "CM": "cm",
            "MM": "mm",
            "INCHES": "in",
            "FEET": "ft",
        }
        display_distance = distance * unit_factors[units]
        unit_suffix = unit_suffixes[units]

        # Build label
        if label_override:
            label_text = label_override
        else:
            label_text = f"{display_distance:.3f} {unit_suffix}"

        # Calculate offset direction (perpendicular to the line in a reasonable plane)
        # Use cross product with a reference vector to get perpendicular direction
        line_vec = [dx, dy, dz]
        line_length = distance
        if line_length < 1e-8:
            return {"error": "Points A and B are at the same location"}

        # Normalize line vector
        line_norm = [v / line_length for v in line_vec]

        # Choose a reference vector not parallel to the line
        ref = [0, 0, 1]
        dot = abs(line_norm[0] * ref[0] + line_norm[1] * ref[1] + line_norm[2] * ref[2])
        if dot > 0.9:
            ref = [0, 1, 0]

        # Cross product: perp = line_norm x ref
        perp = [
            line_norm[1] * ref[2] - line_norm[2] * ref[1],
            line_norm[2] * ref[0] - line_norm[0] * ref[2],
            line_norm[0] * ref[1] - line_norm[1] * ref[0],
        ]
        perp_len = math.sqrt(perp[0] ** 2 + perp[1] ** 2 + perp[2] ** 2)
        if perp_len > 1e-8:
            perp = [v / perp_len for v in perp]
        else:
            perp = [0, 0, 1]

        # Offset points
        off = [p * offset for p in perp]
        a_off = [point_a[i] + off[i] for i in range(3)]
        b_off = [point_b[i] + off[i] for i in range(3)]

        # Midpoint for label
        mid = [(a_off[i] + b_off[i]) / 2 for i in range(3)]
        # Offset the label slightly further from the line
        label_pos = [mid[i] + perp[i] * 0.1 for i in range(3)]

        # Create the dimension line mesh
        # Vertices: A, A_offset, B_offset, B (for the connecting lines + main dimension line)
        verts = [
            tuple(point_a),    # 0: endpoint A
            tuple(a_off),      # 1: offset A
            tuple(b_off),      # 2: offset B
            tuple(point_b),    # 3: endpoint B
        ]
        edges = [
            (0, 1),  # Extension line A
            (1, 2),  # Dimension line
            (2, 3),  # Extension line B
        ]

        # Create mesh
        mesh = bpy.data.meshes.new(f"Dimension_{label_text}")
        mesh.from_pydata(verts, edges, [])
        mesh.update()

        dim_obj = bpy.data.objects.new(f"Dimension_{label_text}", mesh)
        bpy.context.collection.objects.link(dim_obj)

        # Create and assign a wireframe material
        mat = bpy.data.materials.new(name=f"DimensionLine_{label_text}")
        mat.use_nodes = True
        if mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    node.inputs["Base Color"].default_value = (1, 1, 0, 1)
                    node.inputs["Emission Color"].default_value = (1, 1, 0, 1)
                    node.inputs["Emission Strength"].default_value = 2.0
                    break
        dim_obj.data.materials.append(mat)

        # Set display as wire for visibility
        dim_obj.display_type = 'WIRE'

        # Create text label
        text_data = bpy.data.curves.new(name=f"DimText_{label_text}", type='FONT')
        text_data.body = label_text
        text_data.size = max(0.1, distance * 0.08)
        text_data.align_x = 'CENTER'
        text_data.align_y = 'BOTTOM'

        text_obj = bpy.data.objects.new(name=f"DimLabel_{label_text}", object_data=text_data)
        text_obj.location = tuple(label_pos)
        bpy.context.collection.objects.link(text_obj)

        # Assign a text material
        text_mat = bpy.data.materials.new(name=f"DimLabel_{label_text}")
        text_mat.use_nodes = True
        if text_mat.node_tree:
            for node in text_mat.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    node.inputs["Base Color"].default_value = (1, 1, 0, 1)
                    node.inputs["Emission Color"].default_value = (1, 1, 0, 1)
                    node.inputs["Emission Strength"].default_value = 2.0
                    break
        text_obj.data.materials.append(text_mat)

        # Orient the text to face the perpendicular direction
        # Compute rotation so text faces the offset direction
        text_obj.rotation_euler[0] = math.pi / 2  # Stand upright

        # Parent text to dimension line
        text_obj.parent = dim_obj

        return {
            "success": True,
            "dimension_object": dim_obj.name,
            "label_object": text_obj.name,
            "distance_raw": distance,
            "distance_display": display_distance,
            "units": units,
            "label": label_text,
            "point_a": point_a,
            "point_b": point_b,
            "offset_direction": perp,
        }


    def _handle_annotation_clear(self, params: dict) -> dict:
        """Clear annotation layers."""
        layer_name = params.get("layer_name")

        scene = bpy.context.scene
        gpd = scene.grease_pencil

        if gpd is None:
            return {
                "success": True,
                "message": "No annotations found to clear",
                "layers_removed": 0,
            }

        removed_layers = []

        if layer_name:
            # Remove a specific layer
            gpl = gpd.layers.get(layer_name)
            if gpl is None:
                available = [layer.info for layer in gpd.layers]
                return {
                    "error": f"Annotation layer '{layer_name}' not found. "
                    f"Available layers: {available}"
                }
            removed_layers.append(gpl.info)
            gpd.layers.remove(gpl)
        else:
            # Remove all layers
            for gpl in list(gpd.layers):
                removed_layers.append(gpl.info)
                gpd.layers.remove(gpl)

        return {
            "success": True,
            "layers_removed": len(removed_layers),
            "removed": removed_layers,
        }


    def _handle_grease_pencil_create(self, params: dict) -> dict:
        """Create a grease pencil object with strokes."""
        name = params.get("name", "GPencil")
        strokes_data = require_param(params, "strokes", list)
        color = params.get("color", [0, 0, 0, 1])

        color = validate_color(color, "color")

        if len(strokes_data) == 0:
            return {"error": "At least one stroke is required"}

        # Create new grease pencil data
        gpd = bpy.data.grease_pencils.new(name)

        # Create layer
        gpl = gpd.layers.new("Layer", set_active=True)
        gpl.color = (color[0], color[1], color[2])

        # Create frame at current frame
        current_frame = bpy.context.scene.frame_current
        gpf = gpl.frames.new(current_frame)

        stroke_count = 0
        total_points = 0

        for s_idx, stroke_def in enumerate(strokes_data):
            pts = stroke_def.get("points", [])
            stroke_thickness = int(stroke_def.get("thickness", 10))

            if len(pts) < 2:
                continue

            # Validate points
            validated_pts = []
            for i, pt in enumerate(pts):
                validated_pts.append(
                    validate_vector3(pt, f"strokes[{s_idx}].points[{i}]")
                )

            # Create the stroke
            stroke = gpf.strokes.new()
            stroke.display_mode = '3DSPACE'
            stroke.line_width = stroke_thickness

            stroke.points.add(len(validated_pts))
            for i, pt in enumerate(validated_pts):
                stroke.points[i].co = (pt[0], pt[1], pt[2])
                stroke.points[i].pressure = 1.0
                stroke.points[i].strength = 1.0

            stroke_count += 1
            total_points += len(validated_pts)

        # Create the grease pencil object and link to scene
        gp_obj = bpy.data.objects.new(name, gpd)
        bpy.context.collection.objects.link(gp_obj)

        # Create a material for the grease pencil
        gp_mat = bpy.data.materials.new(name=f"{name}_Material")
        bpy.data.materials.create_gpencil_data(gp_mat)
        gp_mat.grease_pencil.color = (color[0], color[1], color[2], color[3])
        gpd.materials.append(gp_mat)

        return {
            "success": True,
            "object": gp_obj.name,
            "strokes_created": stroke_count,
            "total_points": total_points,
            "color": color,
            "layer": gpl.info,
            "frame": current_frame,
        }


    def _handle_grease_pencil_markup(self, params: dict) -> dict:
        """Overlay markup annotations on a rendered image."""
        render_path = require_param(params, "render_path", str)
        annotations = require_param(params, "annotations", list)
        output_path = require_param(params, "output_path", str)

        render_path = validate_filepath(render_path, "render_path", must_exist=True)

        if len(annotations) == 0:
            return {"error": "At least one annotation is required"}

        # Ensure output directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        # Try Pillow first (preferred for 2D image markup)
        try:
            from PIL import Image, ImageDraw, ImageFont

            return _markup_with_pillow(
                render_path, annotations, output_path, Image, ImageDraw, ImageFont
            )
        except ImportError:
            pass

        # Fallback: use Blender compositor nodes
        return _markup_with_compositor(render_path, annotations, output_path)


    # ========== Material Inspection & Manipulation Handlers ==========

