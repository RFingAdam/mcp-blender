"""Object-related command handlers."""

import math

import bpy

from ..utils import (
    ensure_object_selected,
    get_object_or_error,
    serialize_object,
)
from ..validation import (
    require_param,
    validate_enum,
    validate_vector3,
)


class ObjectHandlersMixin:
    """Mixin for object-related handlers."""

    def _handle_object_create(self, params: dict) -> dict:
        """Create a primitive object."""
        # Validate parameters
        valid_types = [
            "cube", "sphere", "cylinder", "plane", "cone", "torus",
            "monkey", "circle", "grid", "empty", "camera", "light"
        ]
        obj_type = validate_enum(
            params.get("type", "cube"), "type", valid_types
        )

        location = params.get("location", [0, 0, 0])
        if location != [0, 0, 0]:
            location = validate_vector3(location, "location")

        rotation = params.get("rotation", [0, 0, 0])
        if rotation != [0, 0, 0]:
            rotation = validate_vector3(rotation, "rotation")

        scale = params.get("scale", [1, 1, 1])
        if scale != [1, 1, 1]:
            scale = validate_vector3(scale, "scale")

        # Map type to creation operator
        creation_ops = {
            "CUBE": lambda: bpy.ops.mesh.primitive_cube_add(location=location),
            "SPHERE": lambda: bpy.ops.mesh.primitive_uv_sphere_add(location=location),
            "CYLINDER": lambda: bpy.ops.mesh.primitive_cylinder_add(location=location),
            "PLANE": lambda: bpy.ops.mesh.primitive_plane_add(location=location),
            "CONE": lambda: bpy.ops.mesh.primitive_cone_add(location=location),
            "TORUS": lambda: bpy.ops.mesh.primitive_torus_add(location=location),
            "MONKEY": lambda: bpy.ops.mesh.primitive_monkey_add(location=location),
            "CIRCLE": lambda: bpy.ops.mesh.primitive_circle_add(location=location),
            "GRID": lambda: bpy.ops.mesh.primitive_grid_add(location=location),
            "EMPTY": lambda: bpy.ops.object.empty_add(location=location),
            "CAMERA": lambda: bpy.ops.object.camera_add(location=location),
            "LIGHT": lambda: bpy.ops.object.light_add(location=location),
        }

        creation_ops[obj_type]()
        obj = bpy.context.active_object

        # Apply name if provided
        if params.get("name"):
            obj.name = params["name"]

        # Apply rotation and scale
        obj.rotation_euler = [math.radians(r) if abs(r) > 2 * math.pi else r for r in rotation]
        obj.scale = scale

        return serialize_object(obj)


    def _handle_object_delete(self, params: dict) -> dict:
        """Delete an object by name."""
        obj = get_object_or_error(params["name"])
        bpy.data.objects.remove(obj, do_unlink=True)
        return {"deleted": params["name"]}


    def _handle_object_list(self, params: dict) -> dict:
        """List all objects in the scene."""
        type_filter = params.get("type_filter")
        objects = []
        for obj in bpy.context.scene.objects:
            if type_filter is None or obj.type == type_filter.upper():
                objects.append({
                    "name": obj.name,
                    "type": obj.type,
                })
        return {"objects": objects}


    def _handle_object_get(self, params: dict) -> dict:
        """Get detailed properties of an object."""
        obj = get_object_or_error(params["name"])
        return serialize_object(obj)


    def _handle_object_transform(self, params: dict) -> dict:
        """Set object transform."""
        obj = get_object_or_error(params["name"])

        if "location" in params:
            obj.location = params["location"]
        if "rotation" in params:
            rotation = params["rotation"]
            obj.rotation_euler = [math.radians(r) if abs(r) > 2 * math.pi else r for r in rotation]
        if "scale" in params:
            obj.scale = params["scale"]

        return serialize_object(obj)


    def _handle_object_duplicate(self, params: dict) -> dict:
        """Duplicate an object."""
        obj = get_object_or_error(params["name"])
        linked = params.get("linked", False)

        # Duplicate
        new_obj = obj.copy()
        if not linked and obj.data:
            new_obj.data = obj.data.copy()

        if params.get("new_name"):
            new_obj.name = params["new_name"]

        bpy.context.collection.objects.link(new_obj)
        return serialize_object(new_obj)


    def _handle_object_join(self, params: dict) -> dict:
        """Join multiple objects into one."""
        names = params["names"]
        if len(names) < 2:
            raise ValueError("Need at least 2 objects to join")

        objects = [get_object_or_error(name) for name in names]

        # Deselect all and select the objects to join
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]

        bpy.ops.object.join()
        return serialize_object(bpy.context.active_object)


    def _handle_object_separate(self, params: dict) -> dict:
        """Separate an object by loose parts."""
        obj = get_object_or_error(params["name"])
        mode = params.get("mode", "LOOSE").upper()

        ensure_object_selected(obj)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.separate(type=mode)
        bpy.ops.object.mode_set(mode="OBJECT")

        # Return list of resulting objects
        return {"objects": [o.name for o in bpy.context.selected_objects]}


    def _handle_object_parent(self, params: dict) -> dict:
        """Set parent relationship."""
        child = get_object_or_error(params["child"])
        parent_name = params.get("parent")

        if parent_name:
            parent = get_object_or_error(parent_name)
            child.parent = parent
        else:
            child.parent = None

        return {"child": child.name, "parent": child.parent.name if child.parent else None}


    def _handle_object_select(self, params: dict) -> dict:
        """Select objects by name or pattern."""
        if params.get("deselect_others", True):
            bpy.ops.object.select_all(action="DESELECT")

        selected = []

        if params.get("names"):
            for name in params["names"]:
                obj = bpy.data.objects.get(name)
                if obj:
                    obj.select_set(True)
                    selected.append(obj.name)

        if params.get("pattern"):
            import fnmatch
            for obj in bpy.data.objects:
                if fnmatch.fnmatch(obj.name, params["pattern"]):
                    obj.select_set(True)
                    selected.append(obj.name)

        return {"selected": selected}


    def _handle_mesh_from_data(self, params: dict) -> dict:
        """Create a mesh from vertex/face arrays using from_pydata."""
        name = require_param(params, "name", str)
        vertices = require_param(params, "vertices", list)
        faces = require_param(params, "faces", list)
        edges = params.get("edges", [])
        location = params.get("location", [0, 0, 0])
        smooth_shade = params.get("smooth_shade", False)

        # Convert to tuples for from_pydata
        verts = [tuple(v) for v in vertices]
        face_list = [tuple(f) for f in faces]
        edge_list = [tuple(e) for e in edges]

        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(verts, edge_list, face_list)
        mesh.update()

        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        obj.location = location

        if smooth_shade:
            for poly in mesh.polygons:
                poly.use_smooth = True

        return serialize_object(obj)


    def _handle_object_set_origin(self, params: dict) -> dict:
        """Set object origin / pivot point."""
        obj = get_object_or_error(require_param(params, "object_name", str))
        origin_type = params.get("origin_type", "GEOMETRY_CENTER")

        # Optionally move cursor first
        if params.get("cursor_location"):
            bpy.context.scene.cursor.location = tuple(params["cursor_location"])

        # Select only this object
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # Map to valid bpy.ops enum
        type_map = {
            "GEOMETRY_CENTER": "GEOMETRY_ORIGIN",
            "ORIGIN_CURSOR": "ORIGIN_CURSOR",
            "ORIGIN_CENTER_OF_MASS": "ORIGIN_CENTER_OF_MASS",
            "ORIGIN_CENTER_OF_VOLUME": "ORIGIN_CENTER_OF_VOLUME",
        }
        bpy_type = type_map.get(origin_type, "GEOMETRY_ORIGIN")
        bpy.ops.object.origin_set(type=bpy_type)

        return serialize_object(obj)


    def _handle_object_apply_transforms(self, params: dict) -> dict:
        """Apply object transforms to mesh data."""
        obj = get_object_or_error(require_param(params, "object_name", str))
        apply_loc = params.get("location", True)
        apply_rot = params.get("rotation", True)
        apply_scale = params.get("scale", True)

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(
            location=apply_loc, rotation=apply_rot, scale=apply_scale
        )

        return serialize_object(obj)


    def _handle_object_rename(self, params: dict) -> dict:
        """Rename an object.

        Blender auto-suffixes (``.001``) if ``new_name`` collides with an
        existing object, so the returned ``name`` should be checked against
        the requested ``new_name`` when uniqueness matters.
        """
        obj = get_object_or_error(require_param(params, "name", str))
        new_name = require_param(params, "new_name", str)
        obj.name = new_name
        return {"success": True, "old_name": params["name"], "name": obj.name}


    def _handle_object_get_bounds(self, params: dict) -> dict:
        """Get an object's world-space axis-aligned bounding box.

        Works for any object type with a bounding box (mesh, curve/font,
        etc.) via the evaluated ``bound_box``, so it can size/position a
        FONT object before ``text_to_mesh`` bakes it - no need to convert
        to a mesh just to measure it.
        """
        from mathutils import Vector

        obj = get_object_or_error(require_param(params, "name", str))
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        zs = [c.z for c in corners]
        bbox_min = [min(xs), min(ys), min(zs)]
        bbox_max = [max(xs), max(ys), max(zs)]

        return {
            "name": obj.name,
            "min": bbox_min,
            "max": bbox_max,
            "dimensions": [bbox_max[i] - bbox_min[i] for i in range(3)],
            "center": [(bbox_min[i] + bbox_max[i]) / 2 for i in range(3)],
        }

    # ========== Material Handlers ==========

