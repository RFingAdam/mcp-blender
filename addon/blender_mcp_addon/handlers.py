"""Command handlers for MCP socket server."""

import contextlib
import io
import math
import os
import tempfile
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
        self._handlers: dict[str, Any] = {}
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

        # Texture generation handlers
        self._handlers["ai_generate_texture"] = self._handle_ai_generate_texture
        self._handlers["ai_generate_reference_image"] = self._handle_ai_generate_reference_image
        self._handlers["ai_inpaint_texture"] = self._handle_ai_inpaint_texture
        self._handlers["ai_texture_from_render"] = self._handle_ai_texture_from_render

        # New AI backend management handlers
        self._handlers["ai_list_backends"] = self._handle_ai_list_backends
        self._handlers["ai_set_backend"] = self._handle_ai_set_backend
        self._handlers["ai_get_backend_info"] = self._handle_ai_get_backend_info
        self._handlers["ai_configure_backend"] = self._handle_ai_configure_backend

        # New AI generation enhancement handlers
        self._handlers["ai_generate_variations"] = self._handle_ai_generate_variations
        self._handlers["ai_cancel_generation"] = self._handle_ai_cancel_generation
        self._handlers["ai_redo_generation"] = self._handle_ai_redo_generation

        # Mesh processing handlers
        self._handlers["ai_mesh_cleanup"] = self._handle_ai_mesh_cleanup
        self._handlers["ai_mesh_decimate"] = self._handle_ai_mesh_decimate
        self._handlers["ai_mesh_remesh"] = self._handle_ai_mesh_remesh
        self._handlers["ai_mesh_optimize"] = self._handle_ai_mesh_optimize
        self._handlers["ai_auto_uv"] = self._handle_ai_auto_uv
        self._handlers["ai_fix_mesh_issues"] = self._handle_ai_fix_mesh_issues
        self._handlers["ai_mesh_stats"] = self._handle_ai_mesh_stats

        # Queue management handlers
        self._handlers["ai_queue_list"] = self._handle_ai_queue_list
        self._handlers["ai_queue_clear"] = self._handle_ai_queue_clear
        self._handlers["ai_get_history"] = self._handle_ai_get_history

        # MSFS content creation handlers
        self._handlers["msfs_create_lod_hierarchy"] = self._handle_msfs_create_lod_hierarchy
        self._handlers["msfs_decimate_for_lod"] = self._handle_msfs_decimate_for_lod
        self._handlers["msfs_setup_lod_distances"] = self._handle_msfs_setup_lod_distances
        self._handlers["msfs_get_lod_info"] = self._handle_msfs_get_lod_info
        self._handlers["msfs_setup_material"] = self._handle_msfs_setup_material
        self._handlers["msfs_create_glass_material"] = self._handle_msfs_create_glass_material
        self._handlers["msfs_create_emissive_material"] = self._handle_msfs_create_emissive_material
        self._handlers["msfs_get_material_presets"] = self._handle_msfs_get_material_presets
        self._handlers["msfs_create_collision_mesh"] = self._handle_msfs_create_collision_mesh
        self._handlers["msfs_create_collision_box"] = self._handle_msfs_create_collision_box
        self._handlers["msfs_create_collision_convex"] = self._handle_msfs_create_collision_convex
        self._handlers["msfs_tag_collision_type"] = self._handle_msfs_tag_collision_type
        self._handlers["msfs_add_animation_tag"] = self._handle_msfs_add_animation_tag
        self._handlers["msfs_setup_visibility_animation"] = self._handle_msfs_setup_visibility_animation
        self._handlers["msfs_configure_animation_loop"] = self._handle_msfs_configure_animation_loop
        self._handlers["msfs_list_animation_tags"] = self._handle_msfs_list_animation_tags
        self._handlers["msfs_export_model"] = self._handle_msfs_export_model
        self._handlers["msfs_validate_for_export"] = self._handle_msfs_validate_for_export
        self._handlers["msfs_get_export_settings"] = self._handle_msfs_get_export_settings
        self._handlers["msfs_batch_export_lods"] = self._handle_msfs_batch_export_lods

        # MSFS livery handlers
        self._handlers["msfs_livery_setup_paint_mode"] = self._handle_msfs_livery_setup_paint_mode
        self._handlers["msfs_livery_create_paint_layers"] = self._handle_msfs_livery_create_paint_layers
        self._handlers["msfs_livery_load_template_overlay"] = self._handle_msfs_livery_load_template_overlay
        self._handlers["msfs_livery_export_uv_layout"] = self._handle_msfs_livery_export_uv_layout
        self._handlers["msfs_livery_set_paint_brush"] = self._handle_msfs_livery_set_paint_brush
        self._handlers["msfs_livery_sample_color"] = self._handle_msfs_livery_sample_color
        self._handlers["msfs_livery_get_paint_presets"] = self._handle_msfs_livery_get_paint_presets
        self._handlers["msfs_livery_get_aircraft_templates"] = self._handle_msfs_livery_get_aircraft_templates
        self._handlers["msfs_livery_get_template_info"] = self._handle_msfs_livery_get_template_info
        self._handlers["msfs_livery_download_template"] = self._handle_msfs_livery_download_template
        self._handlers["msfs_livery_analyze"] = self._handle_msfs_livery_analyze
        self._handlers["msfs_livery_transfer"] = self._handle_msfs_livery_transfer
        self._handlers["msfs_livery_extract_colors"] = self._handle_msfs_livery_extract_colors
        self._handlers["msfs_livery_map_elements"] = self._handle_msfs_livery_map_elements
        self._handlers["msfs_livery_export_textures"] = self._handle_msfs_livery_export_textures
        self._handlers["msfs_livery_create_package"] = self._handle_msfs_livery_create_package
        self._handlers["msfs_livery_convert_to_dds"] = self._handle_msfs_livery_convert_to_dds
        self._handlers["msfs_livery_validate_package"] = self._handle_msfs_livery_validate_package

        # Script execution handler
        self._handlers["execute_script"] = self._handle_execute_script

        # Multi-angle rendering handler
        self._handlers["render_multi_angle"] = self._handle_render_multi_angle

        # Vision analysis handler
        self._handlers["analyze_viewport"] = self._handle_analyze_viewport

        # Refinement iteration handler
        self._handlers["refine_iteration"] = self._handle_refine_iteration

        # Refinement session management handlers
        self._handlers["refine_create_session"] = self._handle_refine_create_session
        self._handlers["refine_get_session"] = self._handle_refine_get_session
        self._handlers["refine_list_sessions"] = self._handle_refine_list_sessions

    def handle(self, method: str, params: dict) -> Any:
        """Handle a command by method name."""
        handler = self._handlers.get(method)
        if handler is None:
            raise ValueError(f"Unknown method: {method}")
        return handler(params)

    # ========== Scene Handlers ==========

    def _handle_ping(self, params: dict) -> dict:
        """Simple ping/pong for connectivity testing."""
        return {
            "pong": True,
            "blender_version": bpy.app.version_string,
            "handler_count": len(self._handlers),
            "has_ai_list_backends": "ai_list_backends" in self._handlers,
            "has_ai_queue_list": "ai_queue_list" in self._handlers,
        }

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
        bpy.ops.screen.screenshot_area(filepath=output_path)
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

        # Use new STL export operator (Blender 4.x+)
        stl_kwargs = {
            "filepath": filepath,
            "export_selected_objects": export_kwargs.get("use_selection", False),
        }
        if "global_scale" in export_kwargs:
            stl_kwargs["global_scale"] = export_kwargs["global_scale"]
        if "ascii" in export_kwargs:
            stl_kwargs["ascii_format"] = export_kwargs["ascii"]
        bpy.ops.wm.stl_export(**stl_kwargs)

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

    # ========== Texture Generation Handlers ==========

    def _handle_ai_generate_texture(self, params: dict) -> dict:
        """Generate PBR texture set from text, optionally apply to object."""
        from .external.ai_models import generate_texture

        return generate_texture(
            prompt=require_param(params, "prompt", str),
            workflow_type="pbr_texture",
            object_name=params.get("object_name"),
            auto_apply=params.get("auto_apply", True),
            texture_types=params.get("texture_types"),
            width=params.get("resolution", 1024),
            height=params.get("resolution", 1024),
            negative_prompt=params.get("negative_prompt", "blurry, low quality, watermark, text, logo"),
            seed=params.get("seed"),
        )

    def _handle_ai_generate_reference_image(self, params: dict) -> dict:
        """Generate concept art / reference image from text."""
        from .external.ai_models import generate_texture

        return generate_texture(
            prompt=require_param(params, "prompt", str),
            workflow_type="reference_image",
            width=params.get("resolution", 1024),
            height=params.get("resolution", 1024),
            negative_prompt=params.get("negative_prompt", "blurry, low quality, watermark, text, logo"),
            seed=params.get("seed"),
        )

    def _handle_ai_inpaint_texture(self, params: dict) -> dict:
        """Inpaint a region of an existing texture."""
        from .external.ai_models import generate_texture

        image_path = require_param(params, "image_path", str)
        mask_path = require_param(params, "mask_path", str)
        validate_filepath(image_path, must_exist=True)
        validate_filepath(mask_path, must_exist=True)

        return generate_texture(
            prompt=require_param(params, "prompt", str),
            workflow_type="inpaint",
            image_path=image_path,
            mask_path=mask_path,
            denoise=params.get("strength", 0.85),
            negative_prompt=params.get("negative_prompt", "blurry, low quality, watermark"),
            seed=params.get("seed"),
        )

    def _handle_ai_texture_from_render(self, params: dict) -> dict:
        """Generate texture from depth/normal render via ControlNet."""
        from .external.ai_models import generate_texture

        object_name = require_param(params, "object_name", str)
        control_type = params.get("control_type", "depth")
        validate_enum(control_type, ["depth", "normal"], "control_type")

        # Render the object to get control image
        render_path = self._render_control_image(object_name, control_type)
        if not render_path:
            return {"success": False, "error": f"Failed to render {control_type} pass for '{object_name}'"}

        return generate_texture(
            prompt=require_param(params, "prompt", str),
            workflow_type="controlnet_texture",
            object_name=object_name,
            auto_apply=params.get("auto_apply", True),
            image_path=render_path,
            controlnet_strength=params.get("controlnet_strength", 0.85),
            negative_prompt=params.get("negative_prompt", "blurry, low quality, watermark"),
            seed=params.get("seed"),
        )

    def _render_control_image(self, object_name: str, control_type: str) -> str | None:
        """Render a depth or normal pass of an object for ControlNet input."""
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return None

        scene = bpy.context.scene
        render = scene.render

        # Save current settings
        old_engine = render.engine
        old_film = render.film_transparent
        old_filepath = render.filepath
        old_res_x = render.resolution_x
        old_res_y = render.resolution_y

        try:
            render.engine = "BLENDER_EEVEE_NEXT"
            render.film_transparent = True
            render.resolution_x = 1024
            render.resolution_y = 1024

            output_path = tempfile.mktemp(suffix=".png", prefix=f"control_{control_type}_")
            render.filepath = output_path

            # Enable the appropriate render pass via view layer
            scene.use_nodes = True
            view_layer = bpy.context.view_layer
            if control_type == "depth":
                view_layer.use_pass_z = True
            elif control_type == "normal":
                view_layer.use_pass_normal = True

            bpy.ops.render.render(write_still=True)
            return output_path

        except Exception:
            return None
        finally:
            render.engine = old_engine
            render.film_transparent = old_film
            render.filepath = old_filepath
            render.resolution_x = old_res_x
            render.resolution_y = old_res_y

    # ========== New AI Backend Management Handlers ==========

    def _handle_ai_list_backends(self, params: dict) -> dict:
        """List all available AI generation backends."""
        from .external.ai_models import list_backends
        return list_backends(
            available_only=params.get("available_only", True),
        )

    def _handle_ai_set_backend(self, params: dict) -> dict:
        """Set the preferred AI backend."""
        from .external.ai_models import set_preferred_backend
        return set_preferred_backend(
            backend=params.get("backend"),
            prefer_local=params.get("prefer_local"),
        )

    def _handle_ai_get_backend_info(self, params: dict) -> dict:
        """Get detailed information about a specific backend."""
        from .external.ai_models import get_backend_info
        return get_backend_info(
            backend=require_param(params, "backend", str),
        )

    def _handle_ai_configure_backend(self, params: dict) -> dict:
        """Configure a specific AI backend."""
        from .external.ai_models import configure_backend
        return configure_backend(
            backend=require_param(params, "backend", str),
            config=params.get("config", {}),
        )

    # ========== New AI Generation Enhancement Handlers ==========

    def _handle_ai_generate_variations(self, params: dict) -> dict:
        """Generate multiple variations of a prompt."""
        from .external.ai_models import generate_model

        prompt = require_param(params, "prompt", str)
        num_variations = params.get("num_variations", 3)
        style = params.get("style")
        quality = params.get("quality", "medium")
        output_format = params.get("output_format", "glb")
        backend = params.get("backend")

        results = []
        for i in range(num_variations):
            result = generate_model(
                prompt=prompt,
                style=style,
                quality=quality,
                output_format=output_format,
                backend=backend,
            )
            results.append({
                "variation": i + 1,
                **result,
            })

        return {
            "success": True,
            "prompt": prompt,
            "num_variations": num_variations,
            "results": results,
        }

    def _handle_ai_cancel_generation(self, params: dict) -> dict:
        """Cancel an in-progress generation job."""
        from .external.ai_models import cancel_generation
        return cancel_generation(
            job_id=require_param(params, "job_id", str),
            backend=params.get("backend"),
        )

    def _handle_ai_redo_generation(self, params: dict) -> dict:
        """Redo the last generation with optional modifications."""
        from .external.ai_models import generate_model, generate_model_from_image
        from .external.job_queue import get_job_queue

        queue = get_job_queue()
        last_job = queue.get_last_job(backend=params.get("backend"))

        if not last_job:
            return {"success": False, "error": "No previous generation found"}

        # Allow overriding parameters
        prompt = params.get("prompt", last_job.prompt)
        style = params.get("style", last_job.style)
        quality = params.get("quality", last_job.quality)
        output_format = params.get("output_format", last_job.output_format)
        backend = params.get("backend", last_job.backend)

        if last_job.image_path:
            return generate_model_from_image(
                image_path=last_job.image_path,
                prompt=prompt,
                style=style,
                quality=quality,
                output_format=output_format,
                backend=backend if backend != "auto" else None,
            )
        else:
            return generate_model(
                prompt=prompt,
                style=style,
                quality=quality,
                output_format=output_format,
                backend=backend if backend != "auto" else None,
            )

    # ========== Mesh Processing Handlers ==========

    def _handle_ai_mesh_cleanup(self, params: dict) -> dict:
        """Clean up a generated mesh."""
        from .external.mesh_processing import cleanup_mesh
        return cleanup_mesh(
            object_name=require_param(params, "object_name", str),
            remove_doubles=params.get("remove_doubles", True),
            merge_distance=params.get("merge_distance", 0.0001),
            fix_normals=params.get("fix_normals", True),
            remove_loose=params.get("remove_loose", True),
            remove_degenerate=params.get("remove_degenerate", True),
        )

    def _handle_ai_mesh_decimate(self, params: dict) -> dict:
        """Reduce polygon count of a mesh."""
        from .external.mesh_processing import decimate_mesh
        return decimate_mesh(
            object_name=require_param(params, "object_name", str),
            ratio=params.get("ratio", 0.5),
            method=params.get("method", "COLLAPSE"),
            triangulate=params.get("triangulate", False),
            preserve_uvs=params.get("preserve_uvs", True),
            vertex_group=params.get("vertex_group"),
            invert_vertex_group=params.get("invert_vertex_group", False),
        )

    def _handle_ai_mesh_remesh(self, params: dict) -> dict:
        """Retopologize a mesh."""
        from .external.mesh_processing import remesh_object
        return remesh_object(
            object_name=require_param(params, "object_name", str),
            method=params.get("method", "VOXEL"),
            voxel_size=params.get("voxel_size", 0.05),
            octree_depth=params.get("octree_depth", 5),
            smooth_normals=params.get("smooth_normals", True),
            apply_smooth=params.get("apply_smooth", True),
            smooth_factor=params.get("smooth_factor", 0.5),
            smooth_iterations=params.get("smooth_iterations", 2),
        )

    def _handle_ai_mesh_optimize(self, params: dict) -> dict:
        """Run full optimization pipeline on a mesh."""
        from .external.mesh_processing import optimize_mesh
        return optimize_mesh(
            object_name=require_param(params, "object_name", str),
            cleanup=params.get("cleanup", True),
            decimate=params.get("decimate", True),
            decimate_ratio=params.get("decimate_ratio", 0.5),
            auto_uv=params.get("auto_uv", True),
            smooth_normals=params.get("smooth_normals", True),
        )

    def _handle_ai_auto_uv(self, params: dict) -> dict:
        """Generate UV maps for a mesh."""
        from .external.mesh_processing import auto_uv_unwrap
        return auto_uv_unwrap(
            object_name=require_param(params, "object_name", str),
            method=params.get("method", "SMART"),
            angle_limit=params.get("angle_limit", 66.0),
            island_margin=params.get("island_margin", 0.02),
            area_weight=params.get("area_weight", 0.0),
            correct_aspect=params.get("correct_aspect", True),
            scale_to_bounds=params.get("scale_to_bounds", True),
            uv_layer_name=params.get("uv_layer_name"),
        )

    def _handle_ai_fix_mesh_issues(self, params: dict) -> dict:
        """Fix common mesh problems."""
        from .external.mesh_processing import fix_mesh_issues
        return fix_mesh_issues(
            object_name=require_param(params, "object_name", str),
            fix_non_manifold=params.get("fix_non_manifold", True),
            fill_holes=params.get("fill_holes", True),
            max_hole_edges=params.get("max_hole_edges", 12),
            fix_normals=params.get("fix_normals", True),
            remove_interior_faces=params.get("remove_interior_faces", True),
        )

    def _handle_ai_mesh_stats(self, params: dict) -> dict:
        """Get detailed statistics about a mesh."""
        from .external.mesh_processing import get_mesh_stats
        return get_mesh_stats(
            object_name=require_param(params, "object_name", str),
        )

    # ========== Queue Management Handlers ==========

    def _handle_ai_queue_list(self, params: dict) -> dict:
        """List all generation jobs."""
        from .external.job_queue import get_job_queue

        queue = get_job_queue()
        jobs = queue.list_jobs(
            status=params.get("status"),
            backend=params.get("backend"),
            limit=params.get("limit"),
            include_completed=params.get("include_completed", True),
        )

        return {
            "success": True,
            "jobs": [job.to_dict() for job in jobs],
            "count": len(jobs),
        }

    def _handle_ai_queue_clear(self, params: dict) -> dict:
        """Clear completed or failed jobs from the queue."""
        from .external.job_queue import get_job_queue

        queue = get_job_queue()

        if params.get("clear_failed", False):
            cleared = queue.clear_failed()
            clear_type = "failed"
        else:
            cleared = queue.clear_completed(
                older_than_hours=params.get("older_than_hours"),
            )
            clear_type = "completed"

        return {
            "success": True,
            "cleared": cleared,
            "type": clear_type,
        }

    def _handle_ai_get_history(self, params: dict) -> dict:
        """Get generation history."""
        from .external.ai_models import get_generation_history
        return get_generation_history(
            limit=params.get("limit", 50),
        )

    # ========== MSFS Content Creation Handlers ==========

    def _handle_msfs_create_lod_hierarchy(self, params: dict) -> dict:
        """Create LOD hierarchy from a base object."""
        from .msfs import create_lod_hierarchy
        return create_lod_hierarchy(
            base_object_name=require_param(params, "base_object_name", str),
            lod_count=params.get("lod_count", 4),
            auto_decimate=params.get("auto_decimate", True),
            decimate_ratios=params.get("decimate_ratios"),
        )

    def _handle_msfs_decimate_for_lod(self, params: dict) -> dict:
        """Decimate a mesh for LOD creation."""
        from .msfs import decimate_for_lod
        return decimate_for_lod(
            object_name=require_param(params, "object_name", str),
            ratio=require_param(params, "ratio", (int, float)),
            preserve_uvs=params.get("preserve_uvs", True),
            preserve_vertex_groups=params.get("preserve_vertex_groups", True),
        )

    def _handle_msfs_setup_lod_distances(self, params: dict) -> dict:
        """Set up LOD switching distances."""
        from .msfs import setup_lod_distances
        return setup_lod_distances(
            base_name=require_param(params, "base_name", str),
            distances=params.get("distances"),
        )

    def _handle_msfs_get_lod_info(self, params: dict) -> dict:
        """Get information about an LOD hierarchy."""
        from .msfs import get_lod_info
        return get_lod_info(
            base_name=require_param(params, "base_name", str),
        )

    def _handle_msfs_setup_material(self, params: dict) -> dict:
        """Set up a material with MSFS-specific properties."""
        from .msfs import setup_msfs_material
        return setup_msfs_material(
            material_name=require_param(params, "material_name", str),
            msfs_type=params.get("msfs_type", "standard"),
            base_color=params.get("base_color"),
            metallic=params.get("metallic", 0.0),
            roughness=params.get("roughness", 0.5),
            emissive_color=params.get("emissive_color"),
            emissive_strength=params.get("emissive_strength", 0.0),
            alpha=params.get("alpha", 1.0),
            double_sided=params.get("double_sided", False),
        )

    def _handle_msfs_create_glass_material(self, params: dict) -> dict:
        """Create a glass material optimized for MSFS."""
        from .msfs import create_glass_material
        return create_glass_material(
            material_name=require_param(params, "material_name", str),
            tint_color=params.get("tint_color"),
            opacity=params.get("opacity", 0.1),
            ior=params.get("ior", 1.45),
            is_windshield=params.get("is_windshield", False),
        )

    def _handle_msfs_create_emissive_material(self, params: dict) -> dict:
        """Create an emissive/light material for MSFS."""
        from .msfs import create_emissive_material
        return create_emissive_material(
            material_name=require_param(params, "material_name", str),
            base_color=params.get("base_color"),
            emissive_color=params.get("emissive_color"),
            emissive_strength=params.get("emissive_strength", 1.0),
            is_day_night=params.get("is_day_night", False),
        )

    def _handle_msfs_get_material_presets(self, params: dict) -> dict:
        """Get list of available material presets."""
        from .msfs import get_material_presets
        return get_material_presets()

    def _handle_msfs_create_collision_mesh(self, params: dict) -> dict:
        """Create a collision mesh from a source object."""
        from .msfs import create_collision_mesh
        return create_collision_mesh(
            source_object_name=require_param(params, "source_object_name", str),
            collision_type=params.get("collision_type", "collider"),
            simplify=params.get("simplify", True),
            simplify_ratio=params.get("simplify_ratio", 0.3),
        )

    def _handle_msfs_create_collision_box(self, params: dict) -> dict:
        """Create a box collision primitive for an object."""
        from .msfs import create_collision_box
        return create_collision_box(
            object_name=require_param(params, "object_name", str),
            collision_type=params.get("collision_type", "collider"),
            padding=params.get("padding", 0.0),
        )

    def _handle_msfs_create_collision_convex(self, params: dict) -> dict:
        """Create a convex hull collision mesh."""
        from .msfs import create_collision_convex
        return create_collision_convex(
            object_name=require_param(params, "object_name", str),
            collision_type=params.get("collision_type", "collider"),
        )

    def _handle_msfs_tag_collision_type(self, params: dict) -> dict:
        """Tag an existing object as a collision mesh."""
        from .msfs.collision import tag_collision_type
        return tag_collision_type(
            object_name=require_param(params, "object_name", str),
            collision_type=require_param(params, "collision_type", str),
        )

    def _handle_msfs_add_animation_tag(self, params: dict) -> dict:
        """Add an animation tag/event marker."""
        from .msfs import add_animation_tag
        return add_animation_tag(
            object_name=require_param(params, "object_name", str),
            tag_type=require_param(params, "tag_type", str),
            frame=require_param(params, "frame", int),
            tag_data=params.get("tag_data"),
        )

    def _handle_msfs_setup_visibility_animation(self, params: dict) -> dict:
        """Set up visibility animation for an object."""
        from .msfs import setup_visibility_animation
        return setup_visibility_animation(
            object_name=require_param(params, "object_name", str),
            visible_range=params.get("visible_range"),
            hidden_range=params.get("hidden_range"),
        )

    def _handle_msfs_configure_animation_loop(self, params: dict) -> dict:
        """Configure animation looping behavior."""
        from .msfs import configure_animation_loop
        return configure_animation_loop(
            object_name=require_param(params, "object_name", str),
            behavior=params.get("behavior", "loop"),
            loop_start=params.get("loop_start"),
            loop_end=params.get("loop_end"),
            loop_count=params.get("loop_count", 0),
        )

    def _handle_msfs_list_animation_tags(self, params: dict) -> dict:
        """List all animation tags."""
        from .msfs import list_animation_tags
        return list_animation_tags(
            object_name=params.get("object_name"),
        )

    def _handle_msfs_export_model(self, params: dict) -> dict:
        """Export model(s) in MSFS-compatible glTF format."""
        from .msfs import export_msfs_model
        return export_msfs_model(
            filepath=require_param(params, "filepath", str),
            objects=params.get("objects"),
            include_lods=params.get("include_lods", True),
            include_collision=params.get("include_collision", True),
            include_animations=params.get("include_animations", True),
            export_format=params.get("export_format", "GLB"),
        )

    def _handle_msfs_validate_for_export(self, params: dict) -> dict:
        """Validate model(s) for MSFS compatibility."""
        from .msfs import validate_for_msfs
        return validate_for_msfs(
            object_name=params.get("object_name"),
        )

    def _handle_msfs_get_export_settings(self, params: dict) -> dict:
        """Get available export settings and their defaults."""
        from .msfs import get_export_settings
        return get_export_settings()

    def _handle_msfs_batch_export_lods(self, params: dict) -> dict:
        """Export LOD hierarchy with proper MSFS structure."""
        from .msfs import batch_export_lods
        return batch_export_lods(
            base_name=require_param(params, "base_name", str),
            output_dir=require_param(params, "output_dir", str),
            separate_files=params.get("separate_files", False),
        )

    # ========== MSFS Livery Handlers ==========

    def _handle_msfs_livery_setup_paint_mode(self, params: dict) -> dict:
        """Set up an object for texture painting."""
        from .msfs.livery import setup_paint_mode
        resolution = params.get("texture_resolution", [4096, 4096])
        return setup_paint_mode(
            object_name=require_param(params, "object_name", str),
            texture_resolution=tuple(resolution),
            create_uvs=params.get("create_uvs", True),
        )

    def _handle_msfs_livery_create_paint_layers(self, params: dict) -> dict:
        """Create paint layer images for livery workflow."""
        from .msfs.livery import create_paint_layers
        resolution = params.get("texture_resolution", [4096, 4096])
        return create_paint_layers(
            object_name=require_param(params, "object_name", str),
            layers=params.get("layers"),
            texture_resolution=tuple(resolution),
        )

    def _handle_msfs_livery_load_template_overlay(self, params: dict) -> dict:
        """Load a reference template image as overlay."""
        from .msfs.livery import load_template_overlay
        return load_template_overlay(
            image_path=require_param(params, "image_path", str),
            object_name=params.get("object_name"),
            opacity=params.get("opacity", 0.5),
        )

    def _handle_msfs_livery_export_uv_layout(self, params: dict) -> dict:
        """Export UV layout as image for painting reference."""
        from .msfs.livery import export_uv_layout
        resolution = params.get("resolution", [4096, 4096])
        return export_uv_layout(
            object_name=require_param(params, "object_name", str),
            output_path=require_param(params, "output_path", str),
            resolution=tuple(resolution),
            fill_opacity=params.get("fill_opacity", 0.0),
            line_thickness=params.get("line_thickness", 1.0),
        )

    def _handle_msfs_livery_set_paint_brush(self, params: dict) -> dict:
        """Configure paint brush settings."""
        from .msfs.livery import set_paint_brush
        return set_paint_brush(
            preset=params.get("preset"),
            color=params.get("color"),
            size=params.get("size"),
            strength=params.get("strength"),
        )

    def _handle_msfs_livery_sample_color(self, params: dict) -> dict:
        """Sample a color from an image."""
        from .msfs.livery import sample_color_from_image
        return sample_color_from_image(
            image_path=require_param(params, "image_path", str),
            x=require_param(params, "x", int),
            y=require_param(params, "y", int),
        )

    def _handle_msfs_livery_get_paint_presets(self, params: dict) -> dict:
        """Get available paint presets."""
        from .msfs.livery.painting import get_paint_presets
        return get_paint_presets()

    def _handle_msfs_livery_get_aircraft_templates(self, params: dict) -> dict:
        """Get list of supported aircraft templates."""
        from .msfs.livery import get_aircraft_templates
        return get_aircraft_templates()

    def _handle_msfs_livery_get_template_info(self, params: dict) -> dict:
        """Get detailed template info for an aircraft."""
        from .msfs.livery import get_template_info
        return get_template_info(
            aircraft_id=require_param(params, "aircraft_id", str),
        )

    def _handle_msfs_livery_download_template(self, params: dict) -> dict:
        """Download or generate template files."""
        from .msfs.livery import download_template
        return download_template(
            aircraft_id=require_param(params, "aircraft_id", str),
            output_dir=require_param(params, "output_dir", str),
        )

    def _handle_msfs_livery_analyze(self, params: dict) -> dict:
        """Analyze a livery image for colors, patterns, elements."""
        from .msfs.livery import analyze_livery
        return analyze_livery(
            image_path=require_param(params, "image_path", str),
            aircraft_type=params.get("aircraft_type"),
        )

    def _handle_msfs_livery_transfer(self, params: dict) -> dict:
        """Transfer livery design between aircraft."""
        from .msfs.livery import transfer_livery
        return transfer_livery(
            source_image=require_param(params, "source_image", str),
            source_aircraft=require_param(params, "source_aircraft", str),
            target_aircraft=require_param(params, "target_aircraft", str),
            output_dir=require_param(params, "output_dir", str),
            preserve_colors=params.get("preserve_colors", True),
            preserve_text=params.get("preserve_text", True),
        )

    def _handle_msfs_livery_extract_colors(self, params: dict) -> dict:
        """Extract color palette from livery image."""
        from .msfs.livery import extract_color_palette
        return extract_color_palette(
            image_path=require_param(params, "image_path", str),
            num_colors=params.get("num_colors", 8),
            exclude_white=params.get("exclude_white", True),
        )

    def _handle_msfs_livery_map_elements(self, params: dict) -> dict:
        """Map design elements between aircraft templates."""
        from .msfs.livery import map_design_elements
        return map_design_elements(
            source_aircraft=require_param(params, "source_aircraft", str),
            target_aircraft=require_param(params, "target_aircraft", str),
            elements=params.get("elements"),
        )

    def _handle_msfs_livery_export_textures(self, params: dict) -> dict:
        """Export livery textures from an object."""
        from .msfs.livery import export_livery_textures
        return export_livery_textures(
            object_name=require_param(params, "object_name", str),
            output_dir=require_param(params, "output_dir", str),
            texture_types=params.get("texture_types"),
            format=params.get("format", "PNG"),
        )

    def _handle_msfs_livery_create_package(self, params: dict) -> dict:
        """Create MSFS livery package folder structure."""
        from .msfs.livery import create_livery_package
        return create_livery_package(
            aircraft_id=require_param(params, "aircraft_id", str),
            livery_name=require_param(params, "livery_name", str),
            output_dir=require_param(params, "output_dir", str),
            texture_dir=params.get("texture_dir"),
            airline=params.get("airline", ""),
            description=params.get("description", ""),
            author=params.get("author", ""),
        )

    def _handle_msfs_livery_convert_to_dds(self, params: dict) -> dict:
        """Convert texture to DDS format for MSFS."""
        from .msfs.livery import convert_to_dds
        return convert_to_dds(
            input_path=require_param(params, "input_path", str),
            output_path=params.get("output_path"),
            texture_type=params.get("texture_type", "albedo"),
        )

    def _handle_msfs_livery_validate_package(self, params: dict) -> dict:
        """Validate a livery package structure."""
        from .msfs.livery import validate_livery_package
        return validate_livery_package(
            package_dir=require_param(params, "package_dir", str),
        )

    # ========== Script Execution Handler ==========

    def _handle_execute_script(self, params: dict) -> dict:
        """Execute arbitrary Python script in Blender's context.

        Enables real mesh modeling via bmesh, mathutils, and full Blender API access.
        """
        script = require_param(params, "script", str)

        # Push undo so user can Ctrl+Z
        bpy.ops.ed.undo_push(message="MCP Execute Script")

        # Capture stdout/stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Pre-loaded namespace for script execution
        exec_namespace = {"bpy": bpy, "__builtins__": __builtins__}

        try:
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                exec(script, exec_namespace)  # noqa: S102

            stdout_str = stdout_capture.getvalue()
            stderr_str = stderr_capture.getvalue()

            # Cap output at 64KB
            max_output = 65536
            if len(stdout_str) > max_output:
                stdout_str = stdout_str[:max_output] + "\n... (truncated)"
            if len(stderr_str) > max_output:
                stderr_str = stderr_str[:max_output] + "\n... (truncated)"

            # Check for a 'result' variable set by the script
            script_result = exec_namespace.get("result")
            result_data = None
            if script_result is not None:
                try:
                    import json
                    json.dumps(script_result)
                    result_data = script_result
                except (TypeError, ValueError):
                    result_data = str(script_result)

            return {
                "success": True,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "error": None,
                "result": result_data,
            }

        except Exception as e:
            stdout_str = stdout_capture.getvalue()
            stderr_str = stderr_capture.getvalue()
            return {
                "success": False,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "error": f"{type(e).__name__}: {e}",
                "result": None,
            }

    # ========== Multi-Angle Rendering Handler ==========

    def _handle_render_multi_angle(self, params: dict) -> dict:
        """Render an object from multiple angles for visual feedback."""
        import mathutils

        object_name = params.get("object_name")
        angles = params.get("angles", ["front", "right", "top", "perspective"])
        resolution = params.get("resolution", [512, 512])
        output_dir = params.get("output_dir")

        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="mcp_render_")

        os.makedirs(output_dir, exist_ok=True)

        # Find target object
        if object_name:
            obj = get_object_or_error(object_name)
        else:
            # Use all mesh objects
            obj = None

        # Compute bounding box center and size
        if obj:
            bbox_corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
        else:
            bbox_corners = []
            for o in bpy.context.scene.objects:
                if o.type == "MESH":
                    bbox_corners.extend(
                        o.matrix_world @ mathutils.Vector(c) for c in o.bound_box
                    )

        if not bbox_corners:
            return {"success": False, "error": "No mesh objects found to render"}

        min_co = mathutils.Vector((
            min(c.x for c in bbox_corners),
            min(c.y for c in bbox_corners),
            min(c.z for c in bbox_corners),
        ))
        max_co = mathutils.Vector((
            max(c.x for c in bbox_corners),
            max(c.y for c in bbox_corners),
            max(c.z for c in bbox_corners),
        ))
        center = (min_co + max_co) / 2
        bbox_size = max_co - min_co
        distance = bbox_size.length * 1.5

        if distance < 0.01:
            distance = 5.0

        # Camera angle definitions (position relative to center)
        angle_configs = {
            "front": {
                "location": mathutils.Vector((0, -distance, 0)) + center,
                "rotation": (math.radians(90), 0, 0),
                "ortho": True,
            },
            "right": {
                "location": mathutils.Vector((distance, 0, 0)) + center,
                "rotation": (math.radians(90), 0, math.radians(90)),
                "ortho": True,
            },
            "top": {
                "location": mathutils.Vector((0, 0, distance)) + center,
                "rotation": (0, 0, 0),
                "ortho": True,
            },
            "perspective": {
                "location": mathutils.Vector((
                    distance * 0.7,
                    -distance * 0.7,
                    distance * 0.5,
                )) + center,
                "rotation": None,  # Use track_to
                "ortho": False,
            },
        }

        # Store original render settings
        scene = bpy.context.scene
        orig_engine = scene.render.engine
        orig_res_x = scene.render.resolution_x
        orig_res_y = scene.render.resolution_y
        orig_percentage = scene.render.resolution_percentage
        orig_camera = scene.camera

        # Use Workbench for speed
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x = resolution[0]
        scene.render.resolution_y = resolution[1]
        scene.render.resolution_percentage = 100
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"

        renders = {}
        temp_objects = []

        try:
            for angle_name in angles:
                config = angle_configs.get(angle_name)
                if not config:
                    continue

                # Create temporary camera
                cam_data = bpy.data.cameras.new(f"_mcp_temp_cam_{angle_name}")
                cam_obj = bpy.data.objects.new(f"_mcp_temp_cam_{angle_name}", cam_data)
                bpy.context.collection.objects.link(cam_obj)
                temp_objects.append(cam_obj)

                cam_obj.location = config["location"]

                if config["ortho"]:
                    cam_data.type = "ORTHO"
                    cam_data.ortho_scale = max(bbox_size.x, bbox_size.y, bbox_size.z) * 1.3
                    cam_obj.rotation_euler = config["rotation"]
                else:
                    cam_data.type = "PERSP"
                    cam_data.lens = 50
                    # Point camera at center
                    direction = center - cam_obj.location
                    rot_quat = direction.to_track_quat("-Z", "Y")
                    cam_obj.rotation_euler = rot_quat.to_euler()

                scene.camera = cam_obj

                # Render
                filepath = os.path.join(output_dir, f"{angle_name}.png")
                scene.render.filepath = filepath
                scene.render.image_settings.file_format = "PNG"
                bpy.ops.render.render(write_still=True)

                renders[angle_name] = filepath

        finally:
            # Clean up temp cameras
            for temp_obj in temp_objects:
                cam_data = temp_obj.data
                bpy.data.objects.remove(temp_obj, do_unlink=True)
                bpy.data.cameras.remove(cam_data)

            # Restore original settings
            scene.render.engine = orig_engine
            scene.render.resolution_x = orig_res_x
            scene.render.resolution_y = orig_res_y
            scene.render.resolution_percentage = orig_percentage
            scene.camera = orig_camera

        return {
            "success": True,
            "renders": renders,
            "output_dir": output_dir,
            "resolution": resolution,
        }

    # ========== Vision Analysis Handler ==========

    def _handle_analyze_viewport(self, params: dict) -> dict:
        """Render multi-angle views and analyze with Ollama vision model."""
        object_name = params.get("object_name")
        reference_image = params.get("reference_image")
        prompt = params.get("prompt", "Analyze this 3D model render for quality and accuracy.")
        resolution = params.get("resolution", [512, 512])

        # Render multi-angle views
        render_result = self._handle_render_multi_angle({
            "object_name": object_name,
            "resolution": resolution,
        })

        if not render_result.get("success"):
            return render_result

        render_paths = render_result["renders"]

        # Send to Ollama vision for analysis
        try:
            from .external.ai_backends.base import BackendConfig
            from .external.ai_backends.ollama_vision import OllamaVisionBackend

            config = BackendConfig(
                enabled=True,
                extra={
                    "host": params.get("ollama_host", "http://10.27.27.10:11434"),
                    "model": params.get("ollama_model", "llama3.2-vision:11b"),
                },
            )
            backend = OllamaVisionBackend(config)

            analysis = backend.analyze_for_refinement(
                image_paths=list(render_paths.values()),
                reference_image=reference_image,
                prompt=prompt,
            )
        except Exception as e:
            analysis = {
                "success": False,
                "error": f"Vision analysis failed: {e}",
            }

        return {
            "success": True,
            "renders": render_paths,
            "analysis": analysis,
            "output_dir": render_result["output_dir"],
        }

    # ========== Refinement Iteration Handler ==========

    def _handle_refine_iteration(self, params: dict) -> dict:
        """Run one iteration of the refinement feedback loop."""
        object_name = params.get("object_name")
        reference_image = params.get("reference_image")
        prompt = params.get("prompt", "Evaluate this 3D model for geometric accuracy and quality.")
        iteration = params.get("iteration", 0)
        previous_score = params.get("previous_score", 0.0)
        max_iterations = params.get("max_iterations", 10)

        # Analyze current state
        analysis_result = self._handle_analyze_viewport({
            "object_name": object_name,
            "reference_image": reference_image,
            "prompt": prompt,
        })

        if not analysis_result.get("success"):
            return analysis_result

        analysis = analysis_result.get("analysis", {})
        score = analysis.get("overall_quality", 0.0)
        score_delta = score - previous_score

        # Check convergence
        converged = False
        convergence_reason = None

        if score >= 0.85:
            converged = True
            convergence_reason = f"Quality threshold reached: {score:.2f} >= 0.85"
        elif iteration >= 2 and abs(score_delta) < 0.02:
            converged = True
            convergence_reason = f"Score plateau: delta {score_delta:.3f} < 0.02"
        elif iteration >= max_iterations:
            converged = True
            convergence_reason = f"Max iterations reached: {iteration} >= {max_iterations}"

        return {
            "success": True,
            "iteration": iteration,
            "converged": converged,
            "convergence_reason": convergence_reason,
            "score": score,
            "score_delta": score_delta,
            "analysis": analysis,
            "render_paths": analysis_result.get("renders", {}),
        }

    # ========== Refinement Session Management Handlers ==========

    def _handle_refine_create_session(self, params: dict) -> dict:
        """Create a new refinement session."""
        from .external.refinement import get_refinement_manager

        manager = get_refinement_manager()
        session = manager.create_session(
            object_name=require_param(params, "object_name", str),
            reference_image=params.get("reference_image"),
            prompt=params.get("prompt", ""),
        )
        return {
            "success": True,
            "session_id": session.session_id,
            "object_name": session.object_name,
            "status": session.status,
        }

    def _handle_refine_get_session(self, params: dict) -> dict:
        """Get refinement session details."""
        from .external.refinement import get_refinement_manager

        manager = get_refinement_manager()
        session = manager.get_session(
            require_param(params, "session_id", str),
        )

        if session is None:
            return {"success": False, "error": "Session not found"}

        return {
            "success": True,
            "session_id": session.session_id,
            "object_name": session.object_name,
            "reference_image": session.reference_image,
            "status": session.status,
            "iterations": [
                {
                    "iteration": it.iteration,
                    "score": it.score,
                    "render_paths": it.render_paths,
                }
                for it in session.iterations
            ],
            "iteration_count": len(session.iterations),
        }

    def _handle_refine_list_sessions(self, params: dict) -> dict:
        """List all refinement sessions."""
        from .external.refinement import get_refinement_manager

        manager = get_refinement_manager()
        sessions = manager.list_sessions()

        return {
            "success": True,
            "sessions": [
                {
                    "session_id": s.session_id,
                    "object_name": s.object_name,
                    "status": s.status,
                    "iteration_count": len(s.iterations),
                }
                for s in sessions
            ],
            "count": len(sessions),
        }
