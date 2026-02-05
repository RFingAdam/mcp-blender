"""Command handlers for MCP socket server."""

import math
import os
from typing import Any

import bpy

from . import compat
from .utils import (
    ensure_object_selected,
    get_material_or_error,
    get_object_or_error,
    serialize_material,
    serialize_object,
    serialize_scene,
)
from .validation import (
    ValidationError,
    require_param,
    validate_color,
    validate_enum,
    validate_filepath,
    validate_vector3,
)


class CommandHandlers:
    """Handles all MCP commands from the socket server."""

    def __init__(self):
        self._handlers: dict[str, callable] = {}
        self._register_handlers()

    def _register_handlers(self):
        """Register all command handlers."""
        # Scene handlers
        self._handlers["ping"] = self._handle_ping
        self._handlers["scene_info"] = self._handle_scene_info
        self._handlers["scene_new"] = self._handle_scene_new
        self._handlers["scene_clear"] = self._handle_scene_clear
        self._handlers["scene_set_frame_range"] = self._handle_scene_set_frame_range
        self._handlers["get_version"] = self._handle_get_version

        # Object handlers
        self._handlers["object_create"] = self._handle_object_create
        self._handlers["object_delete"] = self._handle_object_delete
        self._handlers["object_list"] = self._handle_object_list
        self._handlers["object_get"] = self._handle_object_get
        self._handlers["object_transform"] = self._handle_object_transform
        self._handlers["object_duplicate"] = self._handle_object_duplicate
        self._handlers["object_join"] = self._handle_object_join
        self._handlers["object_separate"] = self._handle_object_separate
        self._handlers["object_parent"] = self._handle_object_parent
        self._handlers["object_select"] = self._handle_object_select

        # Material handlers
        self._handlers["material_create"] = self._handle_material_create
        self._handlers["material_assign"] = self._handle_material_assign
        self._handlers["material_set_color"] = self._handle_material_set_color
        self._handlers["material_set_principled"] = self._handle_material_set_principled
        self._handlers["material_add_texture"] = self._handle_material_add_texture
        self._handlers["material_list"] = self._handle_material_list

        # Modifier handlers
        self._handlers["modifier_add"] = self._handle_modifier_add
        self._handlers["modifier_remove"] = self._handle_modifier_remove
        self._handlers["modifier_apply"] = self._handle_modifier_apply
        self._handlers["modifier_configure"] = self._handle_modifier_configure
        self._handlers["modifier_list"] = self._handle_modifier_list

        # Animation handlers
        self._handlers["keyframe_insert"] = self._handle_keyframe_insert
        self._handlers["keyframe_delete"] = self._handle_keyframe_delete
        self._handlers["keyframe_list"] = self._handle_keyframe_list
        self._handlers["action_create"] = self._handle_action_create
        self._handlers["action_list"] = self._handle_action_list
        self._handlers["animation_play"] = self._handle_animation_play
        self._handlers["animation_goto_frame"] = self._handle_animation_goto_frame

        # Render handlers
        self._handlers["render_image"] = self._handle_render_image
        self._handlers["render_animation"] = self._handle_render_animation
        self._handlers["render_set_engine"] = self._handle_render_set_engine
        self._handlers["render_set_resolution"] = self._handle_render_set_resolution
        self._handlers["render_screenshot"] = self._handle_render_screenshot

        # Export handlers
        self._handlers["export_gltf"] = self._handle_export_gltf
        self._handlers["export_fbx"] = self._handle_export_fbx
        self._handlers["export_obj"] = self._handle_export_obj
        self._handlers["export_stl"] = self._handle_export_stl
        self._handlers["export_usd"] = self._handle_export_usd
        self._handlers["import_file"] = self._handle_import_file

        # External integration handlers
        self._handlers["polyhaven_search"] = self._handle_polyhaven_search
        self._handlers["polyhaven_download"] = self._handle_polyhaven_download
        self._handlers["ai_generate_model"] = self._handle_ai_generate_model
        self._handlers["ai_model_status"] = self._handle_ai_model_status

    def handle(self, method: str, params: dict) -> Any:
        """Handle a command by method name."""
        handler = self._handlers.get(method)
        if handler is None:
            raise ValueError(f"Unknown method: {method}")
        return handler(params)

    # ========== Scene Handlers ==========

    def _handle_ping(self, params: dict) -> dict:
        """Simple ping/pong for connectivity testing."""
        return {"pong": True, "blender_version": bpy.app.version_string}

    def _handle_scene_info(self, params: dict) -> dict:
        """Get current scene information."""
        return serialize_scene(bpy.context.scene)

    def _handle_scene_new(self, params: dict) -> dict:
        """Create a new scene."""
        name = params.get("name", "New Scene")
        scene = bpy.data.scenes.new(name)
        bpy.context.window.scene = scene
        return {"name": scene.name}

    def _handle_scene_clear(self, params: dict) -> dict:
        """Remove all objects from the current scene."""
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        return {"cleared": True}

    def _handle_scene_set_frame_range(self, params: dict) -> dict:
        """Set animation frame range."""
        scene = bpy.context.scene
        scene.frame_start = params.get("start", 1)
        scene.frame_end = params.get("end", 250)
        return {
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
        }

    def _handle_get_version(self, params: dict) -> dict:
        """Get Blender version information."""
        return compat.get_version_info()

    # ========== Object Handlers ==========

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

    # ========== Material Handlers ==========

    def _handle_material_create(self, params: dict) -> dict:
        """Create a new material."""
        name = params.get("name", "Material")
        use_nodes = params.get("use_nodes", True)

        mat = bpy.data.materials.new(name)
        mat.use_nodes = use_nodes

        return serialize_material(mat)

    def _handle_material_assign(self, params: dict) -> dict:
        """Assign a material to an object."""
        object_name = require_param(params, "object_name", str)
        material_name = require_param(params, "material_name", str)

        obj = get_object_or_error(object_name)
        mat = get_material_or_error(material_name)

        if obj.type != "MESH":
            raise ValidationError(
                f"Cannot assign material: '{obj.name}' is a {obj.type}, not a MESH"
            )

        slot_index = params.get("slot_index")
        if slot_index is not None and slot_index < len(obj.material_slots):
            obj.material_slots[slot_index].material = mat
        else:
            obj.data.materials.append(mat)

        return {"object": obj.name, "material": mat.name}

    def _handle_material_set_color(self, params: dict) -> dict:
        """Set material base color."""
        material_name = require_param(params, "material_name", str)
        mat = get_material_or_error(material_name)
        color = validate_color(params.get("color"), "color")

        if not mat.use_nodes:
            mat.use_nodes = True

        # Find Principled BSDF
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                node.inputs["Base Color"].default_value = color
                break

        return {"material": mat.name, "color": list(color)}

    def _handle_material_set_principled(self, params: dict) -> dict:
        """Configure Principled BSDF parameters."""
        mat = get_material_or_error(params["material_name"])

        if not mat.use_nodes:
            mat.use_nodes = True

        input_mapping = compat.get_principled_bsdf_inputs()

        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                for key, value in params.items():
                    if key == "material_name":
                        continue
                    input_name = input_mapping.get(key)
                    if input_name and input_name in node.inputs:
                        inp = node.inputs[input_name]
                        if isinstance(value, (list, tuple)):
                            inp.default_value = value
                        else:
                            inp.default_value = float(value)
                break

        return serialize_material(mat)

    def _handle_material_add_texture(self, params: dict) -> dict:
        """Add image texture node to material."""
        mat = get_material_or_error(params["material_name"])
        image_path = params["image_path"]
        connect_to = params.get("connect_to", "Base Color")

        if not mat.use_nodes:
            mat.use_nodes = True

        # Load image
        image = bpy.data.images.load(image_path)

        # Create texture node
        tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex_node.image = image
        tex_node.location = (-300, 300)

        # Find Principled BSDF and connect
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                if connect_to in node.inputs:
                    mat.node_tree.links.new(tex_node.outputs["Color"], node.inputs[connect_to])
                break

        return {"material": mat.name, "image": image.name}

    def _handle_material_list(self, params: dict) -> dict:
        """List all materials."""
        materials = [{"name": mat.name, "users": mat.users} for mat in bpy.data.materials]
        return {"materials": materials}

    # ========== Modifier Handlers ==========

    # Common modifier types supported
    MODIFIER_TYPES = [
        "SUBSURF", "BEVEL", "SOLIDIFY", "ARRAY", "MIRROR", "BOOLEAN",
        "DECIMATE", "SMOOTH", "WEIGHTED_NORMAL", "TRIANGULATE", "WIREFRAME",
        "SKIN", "REMESH", "SCREW", "SHRINKWRAP", "SIMPLE_DEFORM", "WELD",
        "EDGE_SPLIT", "MASK", "LATTICE", "CURVE", "CAST", "WAVE",
        "DISPLACE", "BUILD", "OCEAN", "CLOTH", "COLLISION", "SOFT_BODY",
    ]

    # Default configurations for common modifiers
    MODIFIER_PRESETS = {
        "SUBSURF": {"levels": 2, "render_levels": 2},
        "BEVEL": {"width": 0.02, "segments": 3},
        "SOLIDIFY": {"thickness": 0.1},
        "ARRAY": {"count": 3, "relative_offset_displace": (1, 0, 0)},
        "MIRROR": {"use_axis": (True, False, False)},
        "DECIMATE": {"ratio": 0.5},
        "SMOOTH": {"factor": 0.5, "iterations": 1},
        "WIREFRAME": {"thickness": 0.02},
        "TRIANGULATE": {"quad_method": "BEAUTY"},
    }

    def _handle_modifier_add(self, params: dict) -> dict:
        """Add modifier to object with optional preset configuration."""
        object_name = require_param(params, "object_name", str)
        modifier_type = require_param(params, "modifier_type", str).upper()

        obj = get_object_or_error(object_name)

        if obj.type != "MESH":
            raise ValidationError(
                f"Cannot add modifier: '{obj.name}' is a {obj.type}, not a MESH"
            )

        if modifier_type not in self.MODIFIER_TYPES:
            raise ValidationError(
                f"Unknown modifier type: '{modifier_type}'. "
                f"Supported types: {', '.join(self.MODIFIER_TYPES[:10])}..."
            )

        mod_name = params.get("modifier_name") or modifier_type
        use_preset = params.get("use_preset", True)

        mod = obj.modifiers.new(name=mod_name, type=modifier_type)

        # Apply preset configuration if available and requested
        if use_preset and modifier_type in self.MODIFIER_PRESETS:
            preset = self.MODIFIER_PRESETS[modifier_type]
            for key, value in preset.items():
                if hasattr(mod, key):
                    try:
                        setattr(mod, key, value)
                    except (TypeError, AttributeError):
                        pass  # Skip incompatible presets

        # Apply any custom properties from params
        if "properties" in params:
            for key, value in params["properties"].items():
                if hasattr(mod, key):
                    setattr(mod, key, value)

        return {
            "object": obj.name,
            "modifier": mod.name,
            "type": mod.type,
            "preset_applied": use_preset and modifier_type in self.MODIFIER_PRESETS,
        }

    def _handle_modifier_remove(self, params: dict) -> dict:
        """Remove modifier from object."""
        object_name = require_param(params, "object_name", str)
        modifier_name = require_param(params, "modifier_name", str)

        obj = get_object_or_error(object_name)
        mod = obj.modifiers.get(modifier_name)

        if mod is None:
            available = [m.name for m in obj.modifiers]
            raise ValidationError(
                f"Modifier '{modifier_name}' not found on '{obj.name}'. "
                f"Available modifiers: {available or 'none'}"
            )

        obj.modifiers.remove(mod)
        return {"object": obj.name, "removed": modifier_name}

    def _handle_modifier_apply(self, params: dict) -> dict:
        """Apply modifier to mesh (makes it permanent)."""
        object_name = require_param(params, "object_name", str)
        modifier_name = require_param(params, "modifier_name", str)

        obj = get_object_or_error(object_name)

        if modifier_name not in obj.modifiers:
            raise ValidationError(f"Modifier '{modifier_name}' not found on '{obj.name}'")

        ensure_object_selected(obj)

        # Need to be in object mode to apply
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.modifier_apply(modifier=modifier_name)
        return {"object": obj.name, "applied": modifier_name}

    def _handle_modifier_configure(self, params: dict) -> dict:
        """Configure modifier properties."""
        object_name = require_param(params, "object_name", str)
        modifier_name = require_param(params, "modifier_name", str)
        properties = require_param(params, "properties", dict)

        obj = get_object_or_error(object_name)
        mod = obj.modifiers.get(modifier_name)

        if mod is None:
            raise ValidationError(f"Modifier '{modifier_name}' not found on '{obj.name}'")

        applied_props = []
        failed_props = []

        for key, value in properties.items():
            if hasattr(mod, key):
                try:
                    setattr(mod, key, value)
                    applied_props.append(key)
                except (TypeError, ValueError) as e:
                    failed_props.append(f"{key}: {e}")
            else:
                failed_props.append(f"{key}: property not found")

        result = {
            "object": obj.name,
            "modifier": mod.name,
            "applied_properties": applied_props,
        }

        if failed_props:
            result["failed_properties"] = failed_props

        return result

    def _handle_modifier_list(self, params: dict) -> dict:
        """List modifiers on an object or list available modifier types."""
        object_name = params.get("object_name")

        if object_name:
            obj = get_object_or_error(object_name)
            modifiers = []
            for mod in obj.modifiers:
                modifiers.append({
                    "name": mod.name,
                    "type": mod.type,
                    "show_viewport": mod.show_viewport,
                    "show_render": mod.show_render,
                })
            return {"object": obj.name, "modifiers": modifiers}
        else:
            return {"available_types": self.MODIFIER_TYPES}

    # ========== Animation Handlers ==========

    # Common animatable properties
    ANIMATABLE_PROPERTIES = [
        "location", "rotation_euler", "rotation_quaternion", "scale",
        "delta_location", "delta_rotation_euler", "delta_scale",
    ]

    def _handle_keyframe_insert(self, params: dict) -> dict:
        """Insert keyframe for an object property."""
        object_name = require_param(params, "object_name", str)
        data_path = require_param(params, "data_path", str)

        obj = get_object_or_error(object_name)
        frame = params.get("frame", bpy.context.scene.frame_current)
        index = params.get("index", -1)

        # Optionally set value before inserting keyframe
        if "value" in params:
            value = params["value"]
            try:
                if index >= 0:
                    getattr(obj, data_path)[index] = value
                else:
                    setattr(obj, data_path, value)
            except (AttributeError, TypeError, IndexError) as e:
                raise ValidationError(f"Cannot set {data_path}: {e}")

        try:
            compat.insert_keyframe_compat(obj, data_path, frame, index)
        except RuntimeError as e:
            raise ValidationError(f"Failed to insert keyframe: {e}")

        return {
            "object": obj.name,
            "data_path": data_path,
            "frame": frame,
            "index": index,
        }

    def _handle_keyframe_delete(self, params: dict) -> dict:
        """Delete keyframe from an object property."""
        object_name = require_param(params, "object_name", str)
        data_path = require_param(params, "data_path", str)

        obj = get_object_or_error(object_name)
        frame = params.get("frame", bpy.context.scene.frame_current)
        index = params.get("index", -1)

        success = compat.delete_keyframe_compat(obj, data_path, frame, index)

        return {
            "object": obj.name,
            "data_path": data_path,
            "frame": frame,
            "deleted": success,
        }

    def _handle_keyframe_list(self, params: dict) -> dict:
        """List all keyframes for an object."""
        object_name = require_param(params, "object_name", str)
        obj = get_object_or_error(object_name)

        keyframes = compat.get_object_keyframes(obj)

        return {
            "object": obj.name,
            "has_animation": obj.animation_data is not None,
            "action": obj.animation_data.action.name if obj.animation_data and obj.animation_data.action else None,
            "keyframes": keyframes,
        }

    def _handle_action_create(self, params: dict) -> dict:
        """Create a new action and optionally assign to object."""
        name = params.get("name", "Action")
        action = compat.create_action(name)

        result = {
            "action": action.name,
            "frame_range": list(action.frame_range),
        }

        if params.get("object_name"):
            obj = get_object_or_error(params["object_name"])
            compat.assign_action_to_object(obj, action)
            result["assigned_to"] = obj.name

        return result

    def _handle_action_list(self, params: dict) -> dict:
        """List all actions in the file."""
        actions = compat.list_actions()
        return {"actions": actions, "count": len(actions)}

    def _handle_animation_play(self, params: dict) -> dict:
        """Play or pause the animation playback."""
        play = params.get("play", True)
        if play:
            bpy.ops.screen.animation_play()
        else:
            bpy.ops.screen.animation_cancel()
        return {
            "playing": play,
            "frame": bpy.context.scene.frame_current,
        }

    def _handle_animation_goto_frame(self, params: dict) -> dict:
        """Jump to a specific frame."""
        frame = require_param(params, "frame", int)

        scene = bpy.context.scene
        scene.frame_set(frame)

        return {
            "frame": scene.frame_current,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
        }

    # ========== Render Handlers ==========

    def _handle_render_image(self, params: dict) -> dict:
        """Render current frame to file."""
        output_path = validate_filepath(
            require_param(params, "output_path", str),
            "output_path"
        )
        valid_formats = ["PNG", "JPEG", "BMP", "TIFF", "OPEN_EXR", "HDR"]
        file_format = validate_enum(
            params.get("file_format", "PNG"),
            "file_format",
            valid_formats
        )

        scene = bpy.context.scene
        scene.render.image_settings.file_format = file_format
        scene.render.filepath = output_path

        bpy.ops.render.render(write_still=True)
        return {"output_path": output_path}

    def _handle_render_animation(self, params: dict) -> dict:
        """Render animation."""
        output_path = params["output_path"]
        file_format = params.get("file_format", "PNG").upper()

        scene = bpy.context.scene
        scene.render.image_settings.file_format = file_format
        scene.render.filepath = output_path

        if params.get("start_frame"):
            scene.frame_start = params["start_frame"]
        if params.get("end_frame"):
            scene.frame_end = params["end_frame"]

        bpy.ops.render.render(animation=True)
        return {"output_path": output_path}

    def _handle_render_set_engine(self, params: dict) -> dict:
        """Set render engine."""
        engine = params["engine"].upper()

        # Handle EEVEE naming across versions
        if engine in ("EEVEE", "BLENDER_EEVEE"):
            engine = compat.get_eevee_engine_name()

        bpy.context.scene.render.engine = engine
        return {"engine": bpy.context.scene.render.engine}

    def _handle_render_set_resolution(self, params: dict) -> dict:
        """Set render resolution."""
        scene = bpy.context.scene
        scene.render.resolution_x = params["width"]
        scene.render.resolution_y = params["height"]
        scene.render.resolution_percentage = params.get("percentage", 100)
        return {
            "width": scene.render.resolution_x,
            "height": scene.render.resolution_y,
            "percentage": scene.render.resolution_percentage,
        }

    def _handle_render_screenshot(self, params: dict) -> dict:
        """Capture viewport screenshot."""
        output_path = params["output_path"]
        bpy.ops.screen.screenshot(filepath=output_path)
        return {"output_path": output_path}

    # ========== Export Handlers ==========

    def _handle_export_gltf(self, params: dict) -> dict:
        """Export to glTF/GLB."""
        filepath = validate_filepath(
            require_param(params, "filepath", str),
            "filepath"
        )
        export_format = validate_enum(
            params.get("export_format", "GLB"),
            "export_format",
            ["GLB", "GLTF_SEPARATE", "GLTF_EMBEDDED"]
        )

        bpy.ops.export_scene.gltf(
            filepath=filepath,
            export_format=export_format,
            use_selection=params.get("selected_only", False),
            export_animations=params.get("export_animations", True),
            export_materials="EXPORT" if params.get("export_materials", True) else "NONE",
        )
        return {"filepath": filepath}

    def _handle_export_fbx(self, params: dict) -> dict:
        """Export to FBX with comprehensive options."""
        filepath = validate_filepath(
            require_param(params, "filepath", str),
            "filepath"
        )

        export_kwargs = {
            "filepath": filepath,
            "use_selection": params.get("selected_only", False),
            "use_mesh_modifiers": params.get("apply_modifiers", True),
        }

        # Optional parameters
        if "scale" in params:
            export_kwargs["global_scale"] = params["scale"]
        if "apply_unit_scale" in params:
            export_kwargs["apply_unit_scale"] = params["apply_unit_scale"]
        if "bake_anim" in params:
            export_kwargs["bake_anim"] = params["bake_anim"]
        if "axis_forward" in params:
            export_kwargs["axis_forward"] = params["axis_forward"]
        if "axis_up" in params:
            export_kwargs["axis_up"] = params["axis_up"]

        bpy.ops.export_scene.fbx(**export_kwargs)

        return {
            "filepath": filepath,
            "format": "FBX",
            "selected_only": export_kwargs["use_selection"],
        }

    def _handle_export_obj(self, params: dict) -> dict:
        """Export to OBJ with options."""
        filepath = validate_filepath(
            require_param(params, "filepath", str),
            "filepath"
        )

        export_kwargs = {
            "filepath": filepath,
            "export_selected_objects": params.get("selected_only", False),
            "apply_modifiers": params.get("apply_modifiers", True),
        }

        # Optional parameters
        if "scale" in params:
            export_kwargs["global_scale"] = params["scale"]
        if "forward_axis" in params:
            export_kwargs["forward_axis"] = params["forward_axis"]
        if "up_axis" in params:
            export_kwargs["up_axis"] = params["up_axis"]
        if "export_materials" in params:
            export_kwargs["export_materials"] = params["export_materials"]

        bpy.ops.wm.obj_export(**export_kwargs)

        return {
            "filepath": filepath,
            "format": "OBJ",
            "selected_only": export_kwargs["export_selected_objects"],
        }

    def _handle_export_stl(self, params: dict) -> dict:
        """Export to STL (for 3D printing)."""
        filepath = validate_filepath(
            require_param(params, "filepath", str),
            "filepath"
        )

        export_kwargs = {
            "filepath": filepath,
            "use_selection": params.get("selected_only", False),
            "use_mesh_modifiers": params.get("apply_modifiers", True),
        }

        # Optional parameters
        if "scale" in params:
            export_kwargs["global_scale"] = params["scale"]
        if "ascii" in params:
            export_kwargs["ascii"] = params["ascii"]

        bpy.ops.export_mesh.stl(**export_kwargs)

        return {
            "filepath": filepath,
            "format": "STL",
            "selected_only": export_kwargs["use_selection"],
        }

    def _handle_import_file(self, params: dict) -> dict:
        """Import file with auto-format detection."""
        filepath = validate_filepath(
            require_param(params, "filepath", str),
            "filepath",
            must_exist=True
        )
        ext = os.path.splitext(filepath)[1].lower()

        # Count objects before import
        objects_before = set(obj.name for obj in bpy.data.objects)

        import_ops = {
            ".gltf": lambda: bpy.ops.import_scene.gltf(filepath=filepath),
            ".glb": lambda: bpy.ops.import_scene.gltf(filepath=filepath),
            ".fbx": lambda: bpy.ops.import_scene.fbx(filepath=filepath),
            ".obj": lambda: bpy.ops.wm.obj_import(filepath=filepath),
            ".stl": lambda: bpy.ops.import_mesh.stl(filepath=filepath),
            ".dae": lambda: bpy.ops.wm.collada_import(filepath=filepath),
            ".abc": lambda: bpy.ops.wm.alembic_import(filepath=filepath),
            ".usd": lambda: bpy.ops.wm.usd_import(filepath=filepath),
            ".usda": lambda: bpy.ops.wm.usd_import(filepath=filepath),
            ".usdc": lambda: bpy.ops.wm.usd_import(filepath=filepath),
            ".ply": lambda: bpy.ops.wm.ply_import(filepath=filepath),
            ".svg": lambda: bpy.ops.import_curve.svg(filepath=filepath),
        }

        if ext not in import_ops:
            supported = ", ".join(sorted(import_ops.keys()))
            raise ValidationError(
                f"Unsupported file format: '{ext}'. Supported: {supported}"
            )

        import_ops[ext]()

        # Identify imported objects
        objects_after = set(obj.name for obj in bpy.data.objects)
        imported_objects = list(objects_after - objects_before)

        return {
            "filepath": filepath,
            "format": ext[1:].upper(),
            "imported_objects": imported_objects,
            "count": len(imported_objects),
        }

    def _handle_export_usd(self, params: dict) -> dict:
        """Export to Universal Scene Description (USD) format."""
        filepath = validate_filepath(
            require_param(params, "filepath", str),
            "filepath"
        )

        export_kwargs = {
            "filepath": filepath,
            "selected_objects_only": params.get("selected_only", False),
        }

        if "export_animation" in params:
            export_kwargs["export_animation"] = params["export_animation"]
        if "export_materials" in params:
            export_kwargs["export_materials"] = params["export_materials"]

        bpy.ops.wm.usd_export(**export_kwargs)

        return {
            "filepath": filepath,
            "format": "USD",
        }

    # ========== External Integration Handlers ==========

    def _handle_polyhaven_search(self, params: dict) -> dict:
        """Search Poly Haven assets."""
        # This will be implemented in the external module
        from .external.polyhaven import search_polyhaven
        return search_polyhaven(
            query=params.get("query", ""),
            asset_type=params.get("asset_type"),
            categories=params.get("categories"),
        )

    def _handle_polyhaven_download(self, params: dict) -> dict:
        """Download and apply Poly Haven asset."""
        from .external.polyhaven import download_polyhaven
        return download_polyhaven(
            asset_id=params["asset_id"],
            resolution=params.get("resolution", "2k"),
            apply_to=params.get("apply_to"),
        )

    def _handle_ai_generate_model(self, params: dict) -> dict:
        """Generate 3D model via AI (text-to-3D or image-to-3D)."""
        from .external.ai_models import generate_model, generate_model_from_image

        # Check if this is image-to-3D or text-to-3D
        image_path = params.get("image_path")
        if image_path:
            return generate_model_from_image(
                image_path=image_path,
                prompt=params.get("prompt"),
                style=params.get("style"),
                quality=params.get("quality", "medium"),
                output_format=params.get("output_format", "glb"),
            )
        else:
            return generate_model(
                prompt=params["prompt"],
                style=params.get("style"),
                quality=params.get("quality", "medium"),
                output_format=params.get("output_format", "glb"),
            )

    def _handle_ai_model_status(self, params: dict) -> dict:
        """Check AI model generation status."""
        from .external.ai_models import check_status
        return check_status(
            job_id=params["job_id"],
            auto_import=params.get("auto_import", True),
        )
