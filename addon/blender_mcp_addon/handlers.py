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



# ---------------------------------------------------------------------------
# Module-level constants used by handlers
# ---------------------------------------------------------------------------

# Socket type mapping (material node groups + geometry nodes)
_SOCKET_TYPE_MAP = {
    "FLOAT": "NodeSocketFloat",
    "VALUE": "NodeSocketFloat",
    "INT": "NodeSocketInt",
    "RGBA": "NodeSocketColor",
    "VECTOR": "NodeSocketVector",
    "SHADER": "NodeSocketShader",
    "BOOLEAN": "NodeSocketBool",
    "OBJECT": "NodeSocketObject",
    "COLLECTION": "NodeSocketCollection",
    "MATERIAL": "NodeSocketMaterial",
    "IMAGE": "NodeSocketImage",
    "STRING": "NodeSocketString",
}

# Bake channel configuration
_CHANNEL_BAKE_CONFIG = {
    "DIFFUSE": {
        "type": "DIFFUSE",
        "pass_filter": {"COLOR"},
        "color_space": "sRGB",
    },
    "ROUGHNESS": {
        "type": "ROUGHNESS",
        "pass_filter": set(),
        "color_space": "Non-Color",
    },
    "METALLIC": {
        "type": "EMIT",
        "pass_filter": set(),
        "color_space": "Non-Color",
        "metallic_trick": True,
    },
    "NORMAL": {
        "type": "NORMAL",
        "pass_filter": set(),
        "color_space": "Non-Color",
    },
    "AO": {
        "type": "AO",
        "pass_filter": set(),
        "color_space": "Non-Color",
    },
    "EMISSION": {
        "type": "EMIT",
        "pass_filter": set(),
        "color_space": "sRGB",
    },
    "DISPLACEMENT": {
        "type": "EMIT",
        "pass_filter": set(),
        "color_space": "Non-Color",
        "displacement_trick": True,
    },
    "COMBINED": {
        "type": "COMBINED",
        "pass_filter": set(),
        "color_space": "sRGB",
    },
}

_ALL_CHANNELS = list(_CHANNEL_BAKE_CONFIG.keys())

_FORMAT_EXTENSIONS = {
    "PNG": ".png",
    "TARGA": ".tga",
    "OPEN_EXR": ".exr",
}


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
        self._handlers["mesh_from_data"] = self._handle_mesh_from_data
        self._handlers["object_set_origin"] = self._handle_object_set_origin
        self._handlers["object_apply_transforms"] = self._handle_object_apply_transforms

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

        # Synchronous model generation
        self._handlers["ai_generate_model_sync"] = self._handle_ai_generate_model_sync

        # Texture generation handlers
        self._handlers["ai_generate_texture"] = self._handle_ai_generate_texture
        self._handlers["ai_generate_texture_sync"] = self._handle_ai_generate_texture_sync
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

        # AI backend probing handlers
        self._handlers["ai_probe_backends"] = self._handle_ai_probe_backends

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

        # Boolean operations
        self._handlers["boolean_op"] = self._handle_boolean_op

        # Curve tools
        self._handlers["curve_create"] = self._handle_curve_create
        self._handlers["curve_to_mesh"] = self._handle_curve_to_mesh
        self._handlers["curve_from_mesh_edge"] = self._handle_curve_from_mesh_edge

        # Edit mode mesh operations
        self._handlers["mesh_extrude"] = self._handle_mesh_extrude
        self._handlers["mesh_inset"] = self._handle_mesh_inset
        self._handlers["mesh_bevel"] = self._handle_mesh_bevel
        self._handlers["mesh_loop_cut"] = self._handle_mesh_loop_cut

        # Selection & query tools
        self._handlers["mesh_select"] = self._handle_mesh_select
        self._handlers["mesh_select_trait"] = self._handle_mesh_select_trait
        self._handlers["mesh_select_linked_flat"] = self._handle_mesh_select_linked_flat
        self._handlers["mesh_select_shortest_path"] = self._handle_mesh_select_shortest_path
        self._handlers["mesh_get_selection"] = self._handle_mesh_get_selection
        self._handlers["mesh_select_edge_loops"] = self._handle_mesh_select_edge_loops

        # Shading & normal control
        self._handlers["shade_smooth"] = self._handle_shade_smooth
        self._handlers["mesh_crease"] = self._handle_mesh_crease
        self._handlers["mesh_mark_sharp"] = self._handle_mesh_mark_sharp
        self._handlers["mesh_mark_seam"] = self._handle_mesh_mark_seam

        # Topology editing tools
        self._handlers["mesh_dissolve"] = self._handle_mesh_dissolve
        self._handlers["mesh_merge"] = self._handle_mesh_merge
        self._handlers["mesh_bridge"] = self._handle_mesh_bridge
        self._handlers["mesh_fill"] = self._handle_mesh_fill
        self._handlers["mesh_subdivide"] = self._handle_mesh_subdivide
        self._handlers["mesh_edge_slide"] = self._handle_mesh_edge_slide
        self._handlers["mesh_tris_to_quads"] = self._handle_mesh_tris_to_quads

        # Cutting & separation tools
        self._handlers["mesh_knife_project"] = self._handle_mesh_knife_project
        self._handlers["mesh_bisect"] = self._handle_mesh_bisect
        self._handlers["mesh_separate_selected"] = self._handle_mesh_separate_selected
        self._handlers["mesh_split"] = self._handle_mesh_split

        # Reference & measurement
        self._handlers["silhouette_compare"] = self._handle_silhouette_compare
        self._handlers["measure"] = self._handle_measure
        self._handlers["reference_image_setup"] = self._handle_reference_image_setup

        # Detail placement & instancing
        self._handlers["array_along_curve"] = self._handle_array_along_curve
        self._handlers["scatter_on_surface"] = self._handle_scatter_on_surface
        self._handlers["collection_instance"] = self._handle_collection_instance

        # Transform & deform
        self._handlers["mesh_proportional_transform"] = self._handle_mesh_proportional_transform
        self._handlers["mesh_shrinkwrap"] = self._handle_mesh_shrinkwrap
        self._handlers["mesh_flatten"] = self._handle_mesh_flatten

        # AI evaluation & self-refinement handlers
        self._handlers["ai_evaluate"] = self._handle_ai_evaluate
        self._handlers["ai_refine"] = self._handle_ai_refine

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

        # AI pipeline orchestrator handlers
        self._handlers["ai_pipeline_generate"] = self._handle_ai_pipeline_generate
        self._handlers["ai_pipeline_status"] = self._handle_ai_pipeline_status

        # Sculpting handlers
        self._handlers["sculpt_setup"] = self._handle_sculpt_setup
        self._handlers["sculpt_mesh_filter"] = self._handle_sculpt_mesh_filter
        self._handlers["sculpt_mask_by_topology"] = self._handle_sculpt_mask_by_topology
        self._handlers["sculpt_face_set_create"] = self._handle_sculpt_face_set_create
        self._handlers["sculpt_multires_reshape"] = self._handle_sculpt_multires_reshape
        self._handlers["sculpt_to_retopo"] = self._handle_sculpt_to_retopo
        self._handlers["sculpt_extract_mask"] = self._handle_sculpt_extract_mask
        self._handlers["sculpt_remesh_voxel"] = self._handle_sculpt_remesh_voxel

        # Rigging & Armature handlers
        self._handlers["armature_create"] = self._handle_armature_create
        self._handlers["autorig_preset"] = self._handle_autorig_preset
        self._handlers["constraint_add"] = self._handle_constraint_add
        self._handlers["constraint_preset"] = self._handle_constraint_preset
        self._handlers["bone_shape_assign"] = self._handle_bone_shape_assign
        self._handlers["pose_library_save"] = self._handle_pose_library_save
        self._handlers["pose_library_apply"] = self._handle_pose_library_apply
        self._handlers["rig_validate"] = self._handle_rig_validate

        # Physics handlers
        self._handlers["physics_rigid_body_add"] = self._handle_physics_rigid_body_add
        self._handlers["physics_rigid_body_batch"] = self._handle_physics_rigid_body_batch
        self._handlers["physics_simulate"] = self._handle_physics_simulate
        self._handlers["physics_cloth_add"] = self._handle_physics_cloth_add
        self._handlers["physics_soft_body_add"] = self._handle_physics_soft_body_add
        self._handlers["physics_fluid_quick"] = self._handle_physics_fluid_quick

        # Annotation & Grease Pencil handlers
        self._handlers["annotation_add"] = self._handle_annotation_add
        self._handlers["annotation_text"] = self._handle_annotation_text
        self._handlers["annotation_dimension"] = self._handle_annotation_dimension
        self._handlers["annotation_clear"] = self._handle_annotation_clear
        self._handlers["grease_pencil_create"] = self._handle_grease_pencil_create
        self._handlers["grease_pencil_markup"] = self._handle_grease_pencil_markup


        # Material inspection & manipulation handlers
        self._handlers["material_inspect_graph"] = self._handle_material_inspect_graph
        self._handlers["material_node_add"] = self._handle_material_node_add
        self._handlers["material_node_connect"] = self._handle_material_node_connect
        self._handlers["material_node_group_create"] = self._handle_material_node_group_create
        self._handlers["material_procedural_preset"] = self._handle_material_procedural_preset
        self._handlers["material_convert_to_pbr"] = self._handle_material_convert_to_pbr
        self._handlers["material_preview_render"] = self._handle_material_preview_render

        # Measurement & validation handlers
        self._handlers["measure_surface_area"] = self._handle_measure_surface_area
        self._handlers["measure_volume"] = self._handle_measure_volume
        self._handlers["measure_clearance"] = self._handle_measure_clearance
        self._handlers["validate_dimensions"] = self._handle_validate_dimensions
        self._handlers["calibrate_from_reference"] = self._handle_calibrate_from_reference
        self._handlers["measure_edge_angle"] = self._handle_measure_edge_angle
        self._handlers["validate_mesh_quality"] = self._handle_validate_mesh_quality

        # Collection handlers
        self._handlers["collection_create"] = self._handle_collection_create
        self._handlers["collection_list"] = self._handle_collection_list
        self._handlers["collection_move"] = self._handle_collection_move
        self._handlers["collection_visibility"] = self._handle_collection_visibility

        # System handlers
        self._handlers["undo"] = self._handle_undo
        self._handlers["redo"] = self._handle_redo
        self._handlers["save"] = self._handle_save
        self._handlers["save_as"] = self._handle_save_as

        # Baking handlers
        self._handlers["bake_pbr_batch"] = self._handle_bake_pbr_batch
        self._handlers["bake_highpoly_to_lowpoly"] = self._handle_bake_highpoly_to_lowpoly
        self._handlers["bake_from_multires"] = self._handle_bake_from_multires
        self._handlers["bake_to_vertex_colors"] = self._handle_bake_to_vertex_colors
        self._handlers["bake_curvature"] = self._handle_bake_curvature
        self._handlers["bake_id_map"] = self._handle_bake_id_map

        # Geometry Nodes handlers
        self._handlers["geonode_create_group"] = self._handle_geonode_create_group
        self._handlers["geonode_apply"] = self._handle_geonode_apply
        self._handlers["geonode_scatter_instances"] = self._handle_geonode_scatter_instances
        self._handlers["geonode_array_grid"] = self._handle_geonode_array_grid
        self._handlers["geonode_deform_curve"] = self._handle_geonode_deform_curve
        self._handlers["geonode_extrude_profile"] = self._handle_geonode_extrude_profile
        self._handlers["geonode_inspect"] = self._handle_geonode_inspect

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

    def _handle_ai_generate_model_sync(self, params: dict) -> dict:
        """Generate 3D model and poll until complete (synchronous)."""
        from .external.ai_models import (
            generate_model,
            generate_model_from_image,
            poll_until_complete,
        )

        # Generate the model (text-to-3D or image-to-3D)
        image_path = params.get("image_path")
        if image_path:
            result = generate_model_from_image(
                image_path=image_path,
                prompt=params.get("prompt"),
                style=params.get("style"),
                quality=params.get("quality", "medium"),
                output_format=params.get("output_format", "glb"),
            )
        else:
            result = generate_model(
                prompt=params.get("prompt", ""),
                style=params.get("style"),
                quality=params.get("quality", "medium"),
                output_format=params.get("output_format", "glb"),
            )

        if not result.get("success") or not result.get("job_id"):
            return result

        # Poll until complete
        max_wait = params.get("max_wait", 300)
        auto_import = params.get("auto_import", True)
        return poll_until_complete(
            job_id=result["job_id"],
            max_wait=max_wait,
            auto_import=auto_import,
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

    def _handle_ai_generate_texture_sync(self, params: dict) -> dict:
        """Generate PBR texture and poll until complete (synchronous)."""
        from .external.ai_models import generate_texture, poll_until_complete

        result = generate_texture(
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

        if not result.get("success") or not result.get("job_id"):
            return result

        timeout = params.get("timeout", 300)
        return poll_until_complete(
            job_id=result["job_id"],
            max_wait=timeout,
            auto_import=False,
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

    # ========== AI Backend Probing Handlers ==========

    def _handle_ai_probe_backends(self, params: dict) -> dict:
        """Probe ComfyUI and report available 3D generation nodes, GPU info, and queue status."""
        import json
        import urllib.request
        import urllib.error

        # Default 3D generation node classes to check
        default_nodes = [
            "[Comfy3D] Load SF3D Model",
            "[Comfy3D] StableFast3D",
            "[Comfy3D] Load TripoSR Model",
            "[Comfy3D] TripoSG I23D Model",
            "[Comfy3D] Load InstantMesh Reconstruction Model",
            "[Comfy3D] Zero123Plus Diffusion Model",
            "[Comfy3D] Load Hunyuan3D V2 ShapeGen Pipeline",
            "[Comfy3D] Load Convolutional Reconstruction Model",
        ]

        check_nodes = params.get("check_nodes") or default_nodes

        # Get ComfyUI host from backend manager
        comfyui_host = "http://10.27.27.10:8188"
        try:
            from .external.ai_backends import get_backend_manager
            manager = get_backend_manager()
            if "comfyui" in manager._backends:
                comfyui_host = manager._backends["comfyui"]._get_host()
        except Exception:
            pass

        result = {
            "success": True,
            "comfyui_host": comfyui_host,
            "comfyui_reachable": False,
            "available_nodes": {},
            "gpu_info": None,
            "queue_status": None,
        }

        # Check ComfyUI connectivity and probe nodes
        try:
            # Fetch full object_info to check node availability
            req = urllib.request.Request(f"{comfyui_host}/object_info")
            with urllib.request.urlopen(req, timeout=10) as response:
                object_info = json.loads(response.read().decode())
            result["comfyui_reachable"] = True

            # Check each requested node
            for node_class in check_nodes:
                result["available_nodes"][node_class] = node_class in object_info
        except urllib.error.URLError as e:
            result["comfyui_reachable"] = False
            result["error"] = f"Cannot connect to ComfyUI at {comfyui_host}: {e}"
            return result
        except Exception as e:
            result["comfyui_reachable"] = False
            result["error"] = f"Error probing ComfyUI: {e}"
            return result

        # Get GPU / system stats
        try:
            req = urllib.request.Request(f"{comfyui_host}/system_stats")
            with urllib.request.urlopen(req, timeout=5) as response:
                system_stats = json.loads(response.read().decode())

            gpu_info = {}
            devices = system_stats.get("devices", [])
            if devices:
                for i, device in enumerate(devices):
                    gpu_info[f"gpu_{i}"] = {
                        "name": device.get("name", "unknown"),
                        "type": device.get("type", "unknown"),
                        "vram_total_mb": round(device.get("vram_total", 0) / (1024 * 1024), 1),
                        "vram_free_mb": round(device.get("vram_free", 0) / (1024 * 1024), 1),
                        "torch_vram_total_mb": round(device.get("torch_vram_total", 0) / (1024 * 1024), 1),
                        "torch_vram_free_mb": round(device.get("torch_vram_free", 0) / (1024 * 1024), 1),
                    }
            result["gpu_info"] = gpu_info
        except Exception as e:
            result["gpu_info"] = {"error": str(e)}

        # Get queue status
        try:
            req = urllib.request.Request(f"{comfyui_host}/queue")
            with urllib.request.urlopen(req, timeout=5) as response:
                queue_data = json.loads(response.read().decode())

            result["queue_status"] = {
                "queue_running": len(queue_data.get("queue_running", [])),
                "queue_pending": len(queue_data.get("queue_pending", [])),
            }
        except Exception as e:
            result["queue_status"] = {"error": str(e)}

        # Summarize available 3D generation capabilities
        available_models = [
            node for node, available in result["available_nodes"].items() if available
        ]
        result["summary"] = {
            "total_nodes_checked": len(check_nodes),
            "nodes_available": len(available_models),
            "available_model_names": available_models,
        }

        return result

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

    # ========== Boolean Operations Handler ==========

    def _handle_boolean_op(self, params: dict) -> dict:
        """Perform a boolean operation between two objects."""
        target_name = require_param(params, "target", str)
        tool_name = require_param(params, "tool", str)
        operation = validate_enum(
            require_param(params, "operation", str),
            ["UNION", "DIFFERENCE", "INTERSECT"],
            "operation",
        )
        solver = validate_enum(
            params.get("solver", "EXACT"),
            ["FAST", "EXACT"],
            "solver",
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
            ["BEZIER", "NURBS", "POLY"],
            "type",
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
            ["FULL", "BACK", "FRONT", "HALF", "NONE"],
            "fill_type",
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
        import bmesh

        object_name = require_param(params, "object_name", str)
        edge_indices = require_param(params, "edge_indices", list)
        curve_type = validate_enum(
            params.get("curve_type", "POLY"),
            ["BEZIER", "NURBS", "POLY"],
            "curve_type",
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
            ["FACES", "EDGES", "VERTICES", "REGION"],
            "mode",
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

        result = bmesh.ops.inset_region(
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
        mode = validate_enum(params.get("mode", "FACE"), ["VERT", "EDGE", "FACE"], "mode")
        action = validate_enum(
            params.get("action", "SET"),
            ["SET", "ADD", "SUBTRACT", "INVERT", "SELECT_ALL", "DESELECT_ALL"],
            "action",
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
        validate_enum(trait, ["NON_MANIFOLD", "BOUNDARY", "LOOSE", "INTERIOR_FACES", "FACE_SIDES", "UNGROUPED", "NON_PLANAR"], "trait")
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
        mode = validate_enum(params.get("mode", "EDGE"), ["VERT", "EDGE"], "mode")
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
        mode = validate_enum(params.get("mode", "FACE"), ["VERT", "EDGE", "FACE"], "mode")

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
        shade_type = validate_enum(params.get("shade_type", "AUTO"), ["SMOOTH", "FLAT", "AUTO"], "shade_type")
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
                        import os
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
        mode = validate_enum(require_param(params, "mode", str), ["VERTS", "EDGES", "FACES"], "mode")
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
        merge_type = validate_enum(params.get("merge_type", "CENTER"), ["CENTER", "FIRST", "LAST", "BY_DISTANCE"], "merge_type")
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
        fill_type = validate_enum(params.get("fill_type", "NGON"), ["NGON", "TRIANGLE_FAN", "GRID"], "fill_type")
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
            ["STRAIGHT_CUT", "INNERVERT", "PATH", "FAN"],
            "quad_corner_type",
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
        mode = validate_enum(params.get("mode", "EDGES"), ["EDGES", "FACES"], "mode")
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
            ["FRONT", "RIGHT", "TOP", "PERSPECTIVE"],
            "camera_angle",
        )
        resolution = int(params.get("resolution", 512))

        obj = get_object_or_error(object_name)

        if not os.path.exists(reference_image):
            raise ValidationError(f"Reference image not found: {reference_image}")

        output_path = os.path.join(tempfile.gettempdir(), f"silhouette_{object_name}.png")
        overlay_path = os.path.join(tempfile.gettempdir(), f"silhouette_overlay_{object_name}.png")

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
        mode = validate_enum(params.get("mode", "BBOX"), ["BBOX", "DISTANCE", "EDGE_LENGTH", "VERTEX_DISTANCE"], "mode")

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
        axis = validate_enum(params.get("axis", "FRONT"), ["FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"], "axis")
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
        fit_type = validate_enum(params.get("fit_type", "FIT_CURVE"), ["FIXED_COUNT", "FIT_LENGTH", "FIT_CURVE"], "fit_type")
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
        ps_mod = target.modifiers.new(name="Scatter", type="PARTICLE_SYSTEM")
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
        from mathutils import Vector, Matrix

        object_name = require_param(params, "object_name", str)
        vertex_indices = require_param(params, "vertex_indices", list)
        transform_type = validate_enum(
            params.get("transform_type", "TRANSLATE"),
            ["TRANSLATE", "ROTATE", "SCALE"],
            "transform_type",
        )
        value = require_param(params, "value", list)
        falloff = validate_enum(
            params.get("falloff", "SMOOTH"),
            ["SMOOTH", "SPHERE", "ROOT", "LINEAR", "SHARP", "CONSTANT"],
            "falloff",
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
        mode = validate_enum(params.get("mode", "NEAREST_SURFACE"), ["NEAREST_SURFACE", "PROJECT", "NEAREST_VERTEX"], "mode")
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
        plane = validate_enum(params.get("plane", "BEST_FIT"), ["XY", "XZ", "YZ", "NORMAL", "BEST_FIT"], "plane")

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
            cxy = sum((c.x - center.x) * (c.y - center.y) for c in coords)
            cxz = sum((c.x - center.x) * (c.z - center.z) for c in coords)
            cyz = sum((c.y - center.y) * (c.z - center.z) for c in coords)

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

    # ========== AI Evaluation & Self-Refinement Handlers ==========

    def _handle_ai_evaluate(self, params: dict) -> dict:
        """Evaluate any render/output using Ollama vision."""
        from .external.ai_models import evaluate_output

        render_path = require_param(params, "render_path", str)
        category = params.get("category", "model")
        reference_image = params.get("reference_image")
        prompt = params.get("prompt", "")

        if category not in ("model", "texture", "animation"):
            raise ValidationError(f"Invalid category: {category}. Must be model, texture, or animation")

        result = evaluate_output(
            render_path=render_path,
            category=category,
            reference_image=reference_image,
            prompt=prompt,
            ollama_host=params.get("ollama_host", "http://10.27.27.10:11434"),
            ollama_model=params.get("ollama_model", "llama3.2-vision:11b"),
        )

        return result

    def _handle_ai_refine(self, params: dict) -> dict:
        """Run one iteration of AI self-refinement loop."""
        from .external.ai_models import refine_with_feedback

        object_name = require_param(params, "object_name", str)
        prompt = require_param(params, "prompt", str)
        category = params.get("category", "model")
        max_iterations = params.get("max_iterations", 5)
        quality_threshold = params.get("quality_threshold", 0.85)
        materials = params.get("materials")

        if category not in ("model", "texture", "animation"):
            raise ValidationError(f"Invalid category: {category}. Must be model, texture, or animation")

        result = refine_with_feedback(
            object_name=object_name,
            prompt=prompt,
            category=category,
            max_iterations=max_iterations,
            quality_threshold=quality_threshold,
            materials=materials,
            ollama_host=params.get("ollama_host", "http://10.27.27.10:11434"),
            ollama_model=params.get("ollama_model", "llama3.2-vision:11b"),
        )

        return result

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

    # ========== AI Pipeline Handlers ==========

    def _handle_ai_pipeline_generate(self, params: dict) -> dict:
        """Run the full AI 3D generation pipeline."""
        from .external.pipeline import run_pipeline

        return run_pipeline(params, self)

    def _handle_ai_pipeline_status(self, params: dict) -> dict:
        """Get status of a pipeline run."""
        from .external.pipeline import get_pipeline_status

        return get_pipeline_status(params.get("pipeline_id", ""))

    # ========== Sculpting Handlers ==========

    def _handle_sculpt_setup(self, params: dict) -> dict:
        """Enter sculpt mode with configuration (multires, dyntopo, or simple)."""
        object_name = require_param(params, "object_name", str)
        mode = params.get("mode", "SIMPLE")
        mode = validate_enum(mode, "mode", ["MULTIRES", "DYNTOPO", "SIMPLE"])
        multires_levels = int(params.get("multires_levels", 3))
        dyntopo_detail = float(params.get("dyntopo_detail", 12.0))
        dyntopo_method = params.get("dyntopo_method", "RELATIVE")
        dyntopo_method = validate_enum(
            dyntopo_method, "dyntopo_method", ["RELATIVE", "CONSTANT", "BRUSH", "MANUAL"]
        )
        symmetry_axes = params.get("symmetry_axes", [])

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh, got {obj.type}")

        # Ensure object is selected and active
        ensure_object_selected(obj)

        # Switch to object mode first if needed
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        result_info = {
            "success": True,
            "object": object_name,
            "sculpt_mode": mode,
        }

        # Set up MULTIRES if requested
        if mode == "MULTIRES":
            # Check if multires modifier already exists
            multires_mod = None
            for mod in obj.modifiers:
                if mod.type == "MULTIRES":
                    multires_mod = mod
                    break

            if multires_mod is None:
                multires_mod = obj.modifiers.new(name="Multires", type="MULTIRES")

            # Subdivide to the requested number of levels
            current_levels = multires_mod.total_levels
            levels_to_add = max(0, multires_levels - current_levels)
            for _ in range(levels_to_add):
                bpy.ops.object.multires_subdivide(
                    modifier=multires_mod.name, mode="CATMULL_CLARK"
                )

            multires_mod.sculpt_levels = multires_mod.total_levels
            result_info["multires_levels"] = multires_mod.total_levels
            result_info["modifier_name"] = multires_mod.name

        # Enter sculpt mode
        bpy.ops.object.mode_set(mode="SCULPT")

        # Set up DYNTOPO if requested
        if mode == "DYNTOPO":
            # Enable dynamic topology
            if not bpy.context.sculpt_object.use_dynamic_topology_sculpting:
                bpy.ops.sculpt.dynamic_topology_toggle()

            sculpt = bpy.context.tool_settings.sculpt
            sculpt.detail_size = dyntopo_detail

            # Map method name to Blender's detail_type_method
            method_map = {
                "RELATIVE": "RELATIVE",
                "CONSTANT": "CONSTANT",
                "BRUSH": "BRUSH",
                "MANUAL": "MANUAL",
            }
            sculpt.detail_type_method = method_map.get(dyntopo_method, "RELATIVE")

            result_info["dyntopo_detail"] = dyntopo_detail
            result_info["dyntopo_method"] = dyntopo_method

        # Set symmetry axes
        sculpt = bpy.context.tool_settings.sculpt
        sculpt.use_symmetry_x = "X" in [a.upper() for a in symmetry_axes]
        sculpt.use_symmetry_y = "Y" in [a.upper() for a in symmetry_axes]
        sculpt.use_symmetry_z = "Z" in [a.upper() for a in symmetry_axes]

        result_info["symmetry"] = {
            "x": sculpt.use_symmetry_x,
            "y": sculpt.use_symmetry_y,
            "z": sculpt.use_symmetry_z,
        }

        return result_info

    def _handle_sculpt_mesh_filter(self, params: dict) -> dict:
        """Apply global mesh filter to entire sculpted mesh."""
        object_name = require_param(params, "object_name", str)
        filter_type = require_param(params, "filter_type", str)
        filter_type = validate_enum(
            filter_type,
            "filter_type",
            [
                "SMOOTH",
                "SHARPEN",
                "ENHANCE_DETAIL",
                "SURFACE_NOISE",
                "INFLATE",
                "SPHERE",
                "RELAX",
                "RELAX_FACE_SETS",
                "ERASE_DISPLACEMENT",
            ],
        )
        strength = float(params.get("strength", 1.0))
        iterations = int(params.get("iterations", 1))

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        # Ensure object is selected, active, and in sculpt mode
        ensure_object_selected(obj)
        if bpy.context.mode != "SCULPT":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="SCULPT")

        # Apply the mesh filter the requested number of iterations
        for i in range(iterations):
            try:
                bpy.ops.sculpt.mesh_filter(type=filter_type, strength=strength)
            except RuntimeError as e:
                return {
                    "error": f"Mesh filter failed on iteration {i + 1}: {str(e)}",
                    "filter_type": filter_type,
                    "completed_iterations": i,
                }

        return {
            "success": True,
            "object": object_name,
            "filter_type": filter_type,
            "strength": strength,
            "iterations": iterations,
            "vertex_count": len(obj.data.vertices),
        }

    def _handle_sculpt_mask_by_topology(self, params: dict) -> dict:
        """Create sculpt masks based on topology features."""
        object_name = require_param(params, "object_name", str)
        mask_type = require_param(params, "mask_type", str)
        mask_type = validate_enum(mask_type, "mask_type", ["CAVITY", "ALL", "NONE", "RANDOM"])
        invert = params.get("invert", False)
        blur_iterations = int(params.get("blur_iterations", 0))

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        # Ensure sculpt mode
        ensure_object_selected(obj)
        if bpy.context.mode != "SCULPT":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="SCULPT")

        # Apply mask based on type
        if mask_type == "ALL":
            bpy.ops.paint.mask_flood_fill(mode="VALUE", value=1.0)
        elif mask_type == "NONE":
            bpy.ops.paint.mask_flood_fill(mode="VALUE", value=0.0)
        elif mask_type == "CAVITY":
            # dirty_mask creates a mask based on cavity/concavity
            bpy.ops.sculpt.dirty_mask(dirty_only=False)
        elif mask_type == "RANDOM":
            # Create a random mask using bmesh vertex paint_mask
            import bmesh
            import random

            # Exit sculpt mode temporarily to edit mask data
            bpy.ops.object.mode_set(mode="OBJECT")

            # Access paint mask layer
            mesh = obj.data
            if not mesh.vertex_paint_masks:
                # Blender 4.x may use different API, try the sculpt approach
                bpy.ops.object.mode_set(mode="SCULPT")
                # Fill with value then we'll randomize via sculpt ops
                bpy.ops.paint.mask_flood_fill(mode="VALUE", value=0.5)
            else:
                mask_layer = mesh.vertex_paint_masks[0]
                for i in range(len(mask_layer.data)):
                    mask_layer.data[i].value = random.random()
                bpy.ops.object.mode_set(mode="SCULPT")

        # Invert mask if requested
        if invert:
            bpy.ops.paint.mask_flood_fill(mode="INVERT")

        # Blur/smooth the mask
        for _ in range(blur_iterations):
            try:
                bpy.ops.sculpt.mask_filter(filter_type="SMOOTH")
            except RuntimeError:
                # Some Blender versions use different API
                break

        return {
            "success": True,
            "object": object_name,
            "mask_type": mask_type,
            "inverted": invert,
            "blur_iterations": blur_iterations,
        }

    def _handle_sculpt_face_set_create(self, params: dict) -> dict:
        """Create face sets by grouping faces based on criteria."""
        object_name = require_param(params, "object_name", str)
        criteria = require_param(params, "criteria", str)
        criteria = validate_enum(
            criteria, "criteria",
            ["LINKED", "MATERIAL", "NORMAL", "SHARP_EDGES", "UV_ISLAND"],
        )

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        # Ensure sculpt mode
        ensure_object_selected(obj)
        if bpy.context.mode != "SCULPT":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="SCULPT")

        # Map criteria to Blender's face_sets_create mode values
        criteria_map = {
            "LINKED": "LOOSE",
            "MATERIAL": "MATERIALS",
            "NORMAL": "NORMALS",
            "SHARP_EDGES": "SHARP_EDGES",
            "UV_ISLAND": "UV_SEAMS",
        }

        blender_mode = criteria_map[criteria]

        try:
            bpy.ops.sculpt.face_sets_create(mode=blender_mode)
        except RuntimeError as e:
            return {"error": f"Face set creation failed: {str(e)}"}

        # Count distinct face sets
        face_set_count = 0
        if obj.data.attributes.get(".sculpt_face_set"):
            attr = obj.data.attributes[".sculpt_face_set"]
            face_set_ids = set()
            for i in range(len(attr.data)):
                face_set_ids.add(attr.data[i].value)
            face_set_count = len(face_set_ids)

        return {
            "success": True,
            "object": object_name,
            "criteria": criteria,
            "blender_mode": blender_mode,
            "face_set_count": face_set_count,
        }

    def _handle_sculpt_multires_reshape(self, params: dict) -> dict:
        """Manage multiresolution modifier levels."""
        object_name = require_param(params, "object_name", str)
        action = require_param(params, "action", str)
        action = validate_enum(
            action, "action",
            ["SUBDIVIDE", "UNSUBDIVIDE", "REBUILD", "APPLY_BASE", "DELETE_HIGHER", "DELETE_LOWER"],
        )

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        # Find multires modifier
        multires_mod = None
        for mod in obj.modifiers:
            if mod.type == "MULTIRES":
                multires_mod = mod
                break

        if multires_mod is None:
            raise ValidationError(
                f"Object '{object_name}' has no Multires modifier. "
                "Use sculpt_setup with mode=MULTIRES first."
            )

        # Ensure object is selected and in appropriate mode
        ensure_object_selected(obj)
        if bpy.context.mode == "SCULPT":
            bpy.ops.object.mode_set(mode="OBJECT")

        mod_name = multires_mod.name
        levels_before = multires_mod.total_levels

        try:
            if action == "SUBDIVIDE":
                bpy.ops.object.multires_subdivide(
                    modifier=mod_name, mode="CATMULL_CLARK"
                )
            elif action == "UNSUBDIVIDE":
                bpy.ops.object.multires_unsubdivide(modifier=mod_name)
            elif action == "REBUILD":
                bpy.ops.object.multires_rebuild_subdiv(modifier=mod_name)
            elif action == "APPLY_BASE":
                bpy.ops.object.multires_base_apply(modifier=mod_name)
            elif action == "DELETE_HIGHER":
                bpy.ops.object.multires_higher_levels_delete(modifier=mod_name)
            elif action == "DELETE_LOWER":
                bpy.ops.object.multires_lower_levels_delete(modifier=mod_name)
        except RuntimeError as e:
            return {"error": f"Multires {action} failed: {str(e)}"}

        levels_after = multires_mod.total_levels

        return {
            "success": True,
            "object": object_name,
            "action": action,
            "modifier": mod_name,
            "levels_before": levels_before,
            "levels_after": levels_after,
            "sculpt_level": multires_mod.sculpt_levels,
            "render_level": multires_mod.render_levels,
        }

    def _handle_sculpt_to_retopo(self, params: dict) -> dict:
        """Pipeline: sculpt to retopologized mesh with optional displacement bake."""
        object_name = require_param(params, "object_name", str)
        method = params.get("method", "VOXEL_REMESH")
        method = validate_enum(method, "method", ["VOXEL_REMESH", "QUADRIFLOW"])
        target_polycount = int(params.get("target_polycount", 5000))
        bake_displacement = params.get("bake_displacement", True)
        displacement_resolution = int(params.get("displacement_resolution", 2048))
        output_path = params.get("output_displacement_path", "")

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        # Exit sculpt mode if active
        ensure_object_selected(obj)
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        original_poly_count = len(obj.data.polygons)
        original_vert_count = len(obj.data.vertices)

        # Step 1: Duplicate the object for retopo
        bpy.ops.object.duplicate()
        retopo_obj = bpy.context.active_object
        retopo_name = f"{object_name}_retopo"
        retopo_obj.name = retopo_name

        # Step 2: Apply all modifiers on the retopo copy
        for mod in list(retopo_obj.modifiers):
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
            except RuntimeError:
                # Some modifiers can't be applied, remove them
                retopo_obj.modifiers.remove(mod)

        # Step 3: Remesh
        if method == "VOXEL_REMESH":
            # Estimate voxel size from target polycount and bounding box
            dims = retopo_obj.dimensions
            volume = dims.x * dims.y * dims.z
            if volume > 0 and target_polycount > 0:
                # Rough estimate: each voxel face ~ voxel_size^2, total surface ~ 6*volume^(2/3)
                surface_area = 6.0 * (volume ** (2.0 / 3.0))
                face_area = surface_area / target_polycount
                voxel_size = max(0.001, math.sqrt(face_area))
            else:
                voxel_size = 0.05

            retopo_obj.data.remesh_voxel_size = voxel_size
            retopo_obj.data.use_remesh_fix_poles = True
            retopo_obj.data.use_remesh_smooth_normals = True
            retopo_obj.data.use_remesh_preserve_volume = True

            ensure_object_selected(retopo_obj)
            bpy.ops.object.voxel_remesh()

        elif method == "QUADRIFLOW":
            ensure_object_selected(retopo_obj)
            try:
                bpy.ops.object.quadriflow_remesh(
                    target_faces=target_polycount,
                    use_preserve_sharp=True,
                    use_preserve_boundary=True,
                    use_mesh_symmetry=False,
                )
            except RuntimeError as e:
                # Quadriflow can fail on complex meshes, fall back to voxel
                retopo_obj.data.remesh_voxel_size = 0.05
                bpy.ops.object.voxel_remesh()

        retopo_poly_count = len(retopo_obj.data.polygons)
        retopo_vert_count = len(retopo_obj.data.vertices)

        # Step 4: Auto-UV unwrap the retopo mesh
        ensure_object_selected(retopo_obj)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")

        result = {
            "success": True,
            "original_object": object_name,
            "retopo_object": retopo_obj.name,
            "method": method,
            "original_polygons": original_poly_count,
            "original_vertices": original_vert_count,
            "retopo_polygons": retopo_poly_count,
            "retopo_vertices": retopo_vert_count,
            "reduction_ratio": round(retopo_poly_count / max(1, original_poly_count), 4),
            "uv_unwrapped": True,
        }

        # Step 5: Optionally bake displacement
        if bake_displacement:
            if not output_path:
                output_path = os.path.join(
                    tempfile.gettempdir(),
                    f"{object_name}_displacement.png",
                )

            try:
                # Create displacement image
                disp_image = bpy.data.images.new(
                    name=f"{object_name}_displacement",
                    width=displacement_resolution,
                    height=displacement_resolution,
                    float_buffer=True,
                )

                # Create a material with an image texture node for baking target
                bake_mat_name = f"_bake_disp_{object_name}"
                bake_mat = bpy.data.materials.new(name=bake_mat_name)
                bake_mat.use_nodes = True
                nodes = bake_mat.node_tree.nodes
                # Clear default nodes
                for node in nodes:
                    nodes.remove(node)

                # Add image texture node (active for baking)
                img_node = nodes.new(type="ShaderNodeTexImage")
                img_node.image = disp_image
                img_node.select = True
                nodes.active = img_node

                # Add principled BSDF and output for valid material
                bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
                output = nodes.new(type="ShaderNodeOutputMaterial")
                bake_mat.node_tree.links.new(bsdf.outputs[0], output.inputs[0])

                # Assign bake material to retopo object
                if len(retopo_obj.data.materials) == 0:
                    retopo_obj.data.materials.append(bake_mat)
                else:
                    retopo_obj.data.materials[0] = bake_mat

                # Set up bake settings
                scene = bpy.context.scene
                prev_engine = scene.render.engine
                scene.render.engine = "CYCLES"

                # Select original as active (source), retopo as selected (target)
                bpy.ops.object.select_all(action="DESELECT")
                retopo_obj.select_set(True)
                obj.select_set(True)
                bpy.context.view_layer.objects.active = retopo_obj

                # Configure bake
                scene.render.bake.use_selected_to_active = True
                scene.render.bake.cage_extrusion = max(obj.dimensions) * 0.1
                scene.render.bake.use_cage = False

                # Bake displacement
                bpy.ops.object.bake(type="DISPLACEMENT")

                # Save the image
                disp_image.filepath_raw = output_path
                disp_image.file_format = "PNG"
                disp_image.save()

                # Restore engine
                scene.render.engine = prev_engine

                # Clean up bake material
                retopo_obj.data.materials.clear()
                bpy.data.materials.remove(bake_mat)

                result["displacement_baked"] = True
                result["displacement_path"] = output_path
                result["displacement_resolution"] = displacement_resolution

            except Exception as e:
                result["displacement_baked"] = False
                result["displacement_error"] = str(e)

        return result

    def _handle_sculpt_extract_mask(self, params: dict) -> dict:
        """Extract masked region as a separate mesh object."""
        import bmesh

        object_name = require_param(params, "object_name", str)
        thickness = float(params.get("thickness", 0.05))
        smooth_iterations = int(params.get("smooth_iterations", 2))

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        # Ensure we're in sculpt mode to access mask data
        ensure_object_selected(obj)
        if bpy.context.mode != "SCULPT":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="SCULPT")

        # Try using the built-in mask extract if available (Blender 2.83+)
        try:
            bpy.ops.mesh.paint_mask_extract(
                mask_threshold=0.5,
                add_boundary_loop=True,
                smooth_iterations=smooth_iterations,
                apply_shrinkwrap=True,
                add_solidify=(thickness > 0),
            )

            # The extracted object becomes the active object
            extracted_obj = bpy.context.active_object

            # If solidify was added, set thickness
            if thickness > 0:
                for mod in extracted_obj.modifiers:
                    if mod.type == "SOLIDIFY":
                        mod.thickness = thickness
                        break

            return {
                "success": True,
                "source_object": object_name,
                "extracted_object": extracted_obj.name,
                "thickness": thickness,
                "smooth_iterations": smooth_iterations,
                "vertex_count": len(extracted_obj.data.vertices),
                "polygon_count": len(extracted_obj.data.polygons),
            }

        except (RuntimeError, AttributeError):
            # Fallback: manual bmesh extraction
            pass

        # Manual extraction fallback
        bpy.ops.object.mode_set(mode="OBJECT")

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        # Get mask values from paint_mask layer
        mask_layer = bm.verts.layers.paint_mask.verify()

        # Find faces where average mask > 0.5
        masked_faces = []
        for face in bm.faces:
            avg_mask = sum(v[mask_layer] for v in face.verts) / len(face.verts)
            if avg_mask > 0.5:
                masked_faces.append(face)

        if not masked_faces:
            bm.free()
            return {"error": "No masked faces found (mask threshold 0.5). Apply a mask first."}

        # Delete unmasked faces
        unmasked_faces = [f for f in bm.faces if f not in masked_faces]
        bmesh.ops.delete(bm, geom=unmasked_faces, context="FACES")

        # Create new mesh and object
        new_mesh = bpy.data.meshes.new(f"{object_name}_extract")
        bm.to_mesh(new_mesh)
        bm.free()

        new_obj = bpy.data.objects.new(f"{object_name}_extract", new_mesh)
        bpy.context.collection.objects.link(new_obj)

        # Copy transforms from original
        new_obj.matrix_world = obj.matrix_world.copy()

        # Smooth boundary
        if smooth_iterations > 0:
            ensure_object_selected(new_obj)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="DESELECT")
            bpy.ops.mesh.select_non_manifold()
            for _ in range(smooth_iterations):
                bpy.ops.mesh.vertices_smooth(factor=0.5)
            bpy.ops.object.mode_set(mode="OBJECT")

        # Add solidify for thickness
        if thickness > 0:
            solidify = new_obj.modifiers.new(name="Solidify", type="SOLIDIFY")
            solidify.thickness = thickness
            solidify.offset = -1.0  # Grow outward

        return {
            "success": True,
            "source_object": object_name,
            "extracted_object": new_obj.name,
            "thickness": thickness,
            "smooth_iterations": smooth_iterations,
            "vertex_count": len(new_obj.data.vertices),
            "polygon_count": len(new_obj.data.polygons),
        }

    def _handle_sculpt_remesh_voxel(self, params: dict) -> dict:
        """Apply voxel remesh to create uniform topology."""
        object_name = require_param(params, "object_name", str)
        voxel_size = float(params.get("voxel_size", 0.05))
        smooth = params.get("smooth", False)
        fix_poles = params.get("fix_poles", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh")

        # Must be in object mode for voxel remesh
        ensure_object_selected(obj)
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        verts_before = len(obj.data.vertices)
        polys_before = len(obj.data.polygons)

        # Configure remesh settings
        obj.data.remesh_voxel_size = voxel_size
        obj.data.use_remesh_fix_poles = fix_poles
        obj.data.use_remesh_smooth_normals = smooth
        obj.data.use_remesh_preserve_volume = True

        # Apply voxel remesh
        try:
            bpy.ops.object.voxel_remesh()
        except RuntimeError as e:
            return {"error": f"Voxel remesh failed: {str(e)}"}

        verts_after = len(obj.data.vertices)
        polys_after = len(obj.data.polygons)

        # Optional post-smooth
        if smooth:
            # Apply a smooth modifier
            smooth_mod = obj.modifiers.new(name="_remesh_smooth", type="SMOOTH")
            smooth_mod.factor = 0.5
            smooth_mod.iterations = 2
            bpy.ops.object.modifier_apply(modifier=smooth_mod.name)

        return {
            "success": True,
            "object": object_name,
            "voxel_size": voxel_size,
            "fix_poles": fix_poles,
            "smooth": smooth,
            "vertices_before": verts_before,
            "vertices_after": verts_after,
            "polygons_before": polys_before,
            "polygons_after": polys_after,
        }


    # ========== Rigging & Armature Handlers ==========

    def _handle_armature_create(self, params: dict) -> dict:
        """Create an armature from a list of bone definitions."""
        name = params.get("name", "Armature")
        bones_data = require_param(params, "bones")
        display_type = params.get("display_type", "OCTAHEDRAL")
        display_type = validate_enum(
            display_type, "display_type",
            ["OCTAHEDRAL", "STICK", "BBONE", "WIRE", "ENVELOPE"],
        )

        if not isinstance(bones_data, list) or len(bones_data) == 0:
            raise ValidationError("'bones' must be a non-empty array of bone definitions")

        # Validate bone data
        for i, bone_def in enumerate(bones_data):
            if not isinstance(bone_def, dict):
                raise ValidationError(f"Bone at index {i} must be an object")
            if "name" not in bone_def:
                raise ValidationError(f"Bone at index {i} missing 'name'")
            if "head" not in bone_def or "tail" not in bone_def:
                raise ValidationError(f"Bone '{bone_def.get('name', i)}' missing 'head' or 'tail'")
            head = bone_def["head"]
            tail = bone_def["tail"]
            if not isinstance(head, (list, tuple)) or len(head) != 3:
                raise ValidationError(f"Bone '{bone_def['name']}' head must be [x, y, z]")
            if not isinstance(tail, (list, tuple)) or len(tail) != 3:
                raise ValidationError(f"Bone '{bone_def['name']}' tail must be [x, y, z]")

        # Create armature data and object
        arm_data = bpy.data.armatures.new(name)
        arm_data.display_type = display_type
        arm_obj = bpy.data.objects.new(name, arm_data)
        bpy.context.collection.objects.link(arm_obj)

        # Select and make active
        ensure_object_selected(arm_obj)

        # Enter edit mode to add bones
        bpy.ops.object.mode_set(mode="EDIT")

        # Remove the default bone if one was created
        for bone in arm_data.edit_bones:
            arm_data.edit_bones.remove(bone)

        # Create bones in order
        bone_names_created = []
        for bone_def in bones_data:
            bone_name = bone_def["name"]
            head = bone_def["head"]
            tail = bone_def["tail"]
            roll = math.radians(bone_def.get("roll", 0))

            edit_bone = arm_data.edit_bones.new(bone_name)
            edit_bone.head = (float(head[0]), float(head[1]), float(head[2]))
            edit_bone.tail = (float(tail[0]), float(tail[1]), float(tail[2]))
            edit_bone.roll = roll

            bone_names_created.append(bone_name)

        # Second pass: set parents (all bones must exist first)
        for bone_def in bones_data:
            parent_name = bone_def.get("parent")
            connected = bone_def.get("connected", False)
            if parent_name:
                bone = arm_data.edit_bones.get(bone_def["name"])
                parent_bone = arm_data.edit_bones.get(parent_name)
                if parent_bone is None:
                    bpy.ops.object.mode_set(mode="OBJECT")
                    raise ValidationError(
                        f"Parent bone '{parent_name}' not found for bone '{bone_def['name']}'"
                    )
                bone.parent = parent_bone
                bone.use_connect = connected

        # Return to object mode
        bpy.ops.object.mode_set(mode="OBJECT")

        return {
            "success": True,
            "armature": arm_obj.name,
            "display_type": display_type,
            "bone_count": len(bone_names_created),
            "bones": bone_names_created,
        }

    def _handle_autorig_preset(self, params: dict) -> dict:
        """Generate a complete rig from a preset type."""
        object_name = require_param(params, "object_name", str)
        preset = require_param(params, "preset", str)
        preset = validate_enum(
            preset, "preset",
            [
                "BIPED", "QUADRUPED", "VEHICLE", "MECHANICAL_ARM",
                "TURRET", "WHEEL_ASSEMBLY", "DOOR_HINGE", "PISTON",
                "LANDING_GEAR",
            ],
        )
        auto_weight = params.get("auto_weight", True)
        msfs_compatible = params.get("msfs_compatible", False)

        obj = get_object_or_error(object_name)
        if obj.type != "MESH":
            raise ValidationError(f"Object '{object_name}' is not a mesh, got {obj.type}")

        # Get object dimensions for scaling the rig
        dims = obj.dimensions
        loc = obj.location
        sx, sy, sz = dims.x, dims.y, dims.z

        # Prefix for MSFS naming
        pfx = "bone_" if msfs_compatible else ""

        # Generate bone definitions based on preset
        bones = []
        constraints = []

        if preset == "BIPED":
            h = sz  # height
            bones = [
                {"name": f"{pfx}root", "head": [0, 0, 0], "tail": [0, 0, h * 0.1]},
                {"name": f"{pfx}spine", "head": [0, 0, h * 0.1], "tail": [0, 0, h * 0.3],
                 "parent": f"{pfx}root", "connected": True},
                {"name": f"{pfx}chest", "head": [0, 0, h * 0.3], "tail": [0, 0, h * 0.55],
                 "parent": f"{pfx}spine", "connected": True},
                {"name": f"{pfx}neck", "head": [0, 0, h * 0.55], "tail": [0, 0, h * 0.65],
                 "parent": f"{pfx}chest", "connected": True},
                {"name": f"{pfx}head", "head": [0, 0, h * 0.65], "tail": [0, 0, h * 0.85],
                 "parent": f"{pfx}neck", "connected": True},
                # Left arm
                {"name": f"{pfx}shoulder.L", "head": [0, 0, h * 0.55], "tail": [sx * 0.2, 0, h * 0.55],
                 "parent": f"{pfx}chest"},
                {"name": f"{pfx}upper_arm.L", "head": [sx * 0.2, 0, h * 0.55], "tail": [sx * 0.35, 0, h * 0.35],
                 "parent": f"{pfx}shoulder.L", "connected": True},
                {"name": f"{pfx}forearm.L", "head": [sx * 0.35, 0, h * 0.35], "tail": [sx * 0.5, 0, h * 0.15],
                 "parent": f"{pfx}upper_arm.L", "connected": True},
                {"name": f"{pfx}hand.L", "head": [sx * 0.5, 0, h * 0.15], "tail": [sx * 0.55, 0, h * 0.1],
                 "parent": f"{pfx}forearm.L", "connected": True},
                # Right arm
                {"name": f"{pfx}shoulder.R", "head": [0, 0, h * 0.55], "tail": [-sx * 0.2, 0, h * 0.55],
                 "parent": f"{pfx}chest"},
                {"name": f"{pfx}upper_arm.R", "head": [-sx * 0.2, 0, h * 0.55], "tail": [-sx * 0.35, 0, h * 0.35],
                 "parent": f"{pfx}shoulder.R", "connected": True},
                {"name": f"{pfx}forearm.R", "head": [-sx * 0.35, 0, h * 0.35], "tail": [-sx * 0.5, 0, h * 0.15],
                 "parent": f"{pfx}upper_arm.R", "connected": True},
                {"name": f"{pfx}hand.R", "head": [-sx * 0.5, 0, h * 0.15], "tail": [-sx * 0.55, 0, h * 0.1],
                 "parent": f"{pfx}forearm.R", "connected": True},
                # Left leg
                {"name": f"{pfx}thigh.L", "head": [sx * 0.1, 0, h * 0.1], "tail": [sx * 0.1, 0.02, -h * 0.15],
                 "parent": f"{pfx}root"},
                {"name": f"{pfx}shin.L", "head": [sx * 0.1, 0.02, -h * 0.15], "tail": [sx * 0.1, 0, -h * 0.45],
                 "parent": f"{pfx}thigh.L", "connected": True},
                {"name": f"{pfx}foot.L", "head": [sx * 0.1, 0, -h * 0.45], "tail": [sx * 0.1, -0.08 * h, -h * 0.48],
                 "parent": f"{pfx}shin.L", "connected": True},
                # Right leg
                {"name": f"{pfx}thigh.R", "head": [-sx * 0.1, 0, h * 0.1], "tail": [-sx * 0.1, 0.02, -h * 0.15],
                 "parent": f"{pfx}root"},
                {"name": f"{pfx}shin.R", "head": [-sx * 0.1, 0.02, -h * 0.15], "tail": [-sx * 0.1, 0, -h * 0.45],
                 "parent": f"{pfx}thigh.R", "connected": True},
                {"name": f"{pfx}foot.R", "head": [-sx * 0.1, 0, -h * 0.45], "tail": [-sx * 0.1, -0.08 * h, -h * 0.48],
                 "parent": f"{pfx}shin.R", "connected": True},
            ]

        elif preset == "QUADRUPED":
            bones = [
                {"name": f"{pfx}root", "head": [0, 0, sz * 0.5], "tail": [0, sy * 0.1, sz * 0.5]},
                {"name": f"{pfx}spine_front", "head": [0, sy * 0.3, sz * 0.5], "tail": [0, sy * 0.45, sz * 0.55],
                 "parent": f"{pfx}root"},
                {"name": f"{pfx}spine_back", "head": [0, -sy * 0.3, sz * 0.5], "tail": [0, -sy * 0.45, sz * 0.5],
                 "parent": f"{pfx}root"},
                {"name": f"{pfx}neck", "head": [0, sy * 0.45, sz * 0.55], "tail": [0, sy * 0.5, sz * 0.75],
                 "parent": f"{pfx}spine_front", "connected": True},
                {"name": f"{pfx}head", "head": [0, sy * 0.5, sz * 0.75], "tail": [0, sy * 0.6, sz * 0.8],
                 "parent": f"{pfx}neck", "connected": True},
                {"name": f"{pfx}tail", "head": [0, -sy * 0.45, sz * 0.5], "tail": [0, -sy * 0.6, sz * 0.55],
                 "parent": f"{pfx}spine_back", "connected": True},
                # Front legs
                {"name": f"{pfx}front_upper.L", "head": [sx * 0.15, sy * 0.35, sz * 0.4], "tail": [sx * 0.15, sy * 0.35, sz * 0.2],
                 "parent": f"{pfx}spine_front"},
                {"name": f"{pfx}front_lower.L", "head": [sx * 0.15, sy * 0.35, sz * 0.2], "tail": [sx * 0.15, sy * 0.35, 0],
                 "parent": f"{pfx}front_upper.L", "connected": True},
                {"name": f"{pfx}front_upper.R", "head": [-sx * 0.15, sy * 0.35, sz * 0.4], "tail": [-sx * 0.15, sy * 0.35, sz * 0.2],
                 "parent": f"{pfx}spine_front"},
                {"name": f"{pfx}front_lower.R", "head": [-sx * 0.15, sy * 0.35, sz * 0.2], "tail": [-sx * 0.15, sy * 0.35, 0],
                 "parent": f"{pfx}front_upper.R", "connected": True},
                # Rear legs
                {"name": f"{pfx}rear_upper.L", "head": [sx * 0.15, -sy * 0.35, sz * 0.4], "tail": [sx * 0.15, -sy * 0.35, sz * 0.2],
                 "parent": f"{pfx}spine_back"},
                {"name": f"{pfx}rear_lower.L", "head": [sx * 0.15, -sy * 0.35, sz * 0.2], "tail": [sx * 0.15, -sy * 0.35, 0],
                 "parent": f"{pfx}rear_upper.L", "connected": True},
                {"name": f"{pfx}rear_upper.R", "head": [-sx * 0.15, -sy * 0.35, sz * 0.4], "tail": [-sx * 0.15, -sy * 0.35, sz * 0.2],
                 "parent": f"{pfx}spine_back"},
                {"name": f"{pfx}rear_lower.R", "head": [-sx * 0.15, -sy * 0.35, sz * 0.2], "tail": [-sx * 0.15, -sy * 0.35, 0],
                 "parent": f"{pfx}rear_upper.R", "connected": True},
            ]

        elif preset == "VEHICLE":
            # Vehicle rig: body, 4 wheels with suspension, steering
            hw = sx * 0.4  # half wheel track width
            wb_f = sy * 0.35  # front axle offset
            wb_r = -sy * 0.35  # rear axle offset
            wh = sz * 0.15  # wheel center height
            susp_top = sz * 0.4
            bones = [
                {"name": f"{pfx}body", "head": [0, 0, sz * 0.3], "tail": [0, sy * 0.2, sz * 0.3]},
                {"name": f"{pfx}steering", "head": [0, wb_f, susp_top], "tail": [0, wb_f + 0.05, susp_top],
                 "parent": f"{pfx}body"},
                # Front left
                {"name": f"{pfx}suspension_fl", "head": [hw, wb_f, susp_top], "tail": [hw, wb_f, wh],
                 "parent": f"{pfx}steering"},
                {"name": f"{pfx}wheel_fl", "head": [hw, wb_f, wh], "tail": [hw + 0.05, wb_f, wh],
                 "parent": f"{pfx}suspension_fl", "connected": True},
                # Front right
                {"name": f"{pfx}suspension_fr", "head": [-hw, wb_f, susp_top], "tail": [-hw, wb_f, wh],
                 "parent": f"{pfx}steering"},
                {"name": f"{pfx}wheel_fr", "head": [-hw, wb_f, wh], "tail": [-hw - 0.05, wb_f, wh],
                 "parent": f"{pfx}suspension_fr", "connected": True},
                # Rear left
                {"name": f"{pfx}suspension_rl", "head": [hw, wb_r, susp_top], "tail": [hw, wb_r, wh],
                 "parent": f"{pfx}body"},
                {"name": f"{pfx}wheel_rl", "head": [hw, wb_r, wh], "tail": [hw + 0.05, wb_r, wh],
                 "parent": f"{pfx}suspension_rl", "connected": True},
                # Rear right
                {"name": f"{pfx}suspension_rr", "head": [-hw, wb_r, susp_top], "tail": [-hw, wb_r, wh],
                 "parent": f"{pfx}body"},
                {"name": f"{pfx}wheel_rr", "head": [-hw, wb_r, wh], "tail": [-hw - 0.05, wb_r, wh],
                 "parent": f"{pfx}suspension_rr", "connected": True},
            ]

        elif preset == "MECHANICAL_ARM":
            # Chain of arm segments with IK target
            seg_len = sz * 0.25
            bones = [
                {"name": f"{pfx}arm_base", "head": [0, 0, 0], "tail": [0, 0, seg_len]},
                {"name": f"{pfx}arm_seg1", "head": [0, 0, seg_len], "tail": [0, 0, seg_len * 2],
                 "parent": f"{pfx}arm_base", "connected": True},
                {"name": f"{pfx}arm_seg2", "head": [0, 0, seg_len * 2], "tail": [0, 0, seg_len * 3],
                 "parent": f"{pfx}arm_seg1", "connected": True},
                {"name": f"{pfx}arm_seg3", "head": [0, 0, seg_len * 3], "tail": [0, 0, seg_len * 4],
                 "parent": f"{pfx}arm_seg2", "connected": True},
                {"name": f"{pfx}arm_tip", "head": [0, 0, seg_len * 4], "tail": [0, 0, seg_len * 4.2],
                 "parent": f"{pfx}arm_seg3", "connected": True},
                {"name": f"{pfx}arm_ik_target", "head": [0, seg_len, seg_len * 3], "tail": [0, seg_len, seg_len * 3.2]},
            ]
            constraints.append({
                "bone": f"{pfx}arm_tip",
                "type": "IK",
                "target_bone": f"{pfx}arm_ik_target",
                "chain_count": 4,
            })

        elif preset == "TURRET":
            base_h = sz * 0.3
            barrel_len = sy * 0.4
            bones = [
                {"name": f"{pfx}turret_base", "head": [0, 0, 0], "tail": [0, 0, base_h]},
                {"name": f"{pfx}turret_rotation", "head": [0, 0, base_h], "tail": [0, 0.05, base_h],
                 "parent": f"{pfx}turret_base", "connected": True},
                {"name": f"{pfx}turret_elevation", "head": [0, 0, base_h], "tail": [0, barrel_len, base_h],
                 "parent": f"{pfx}turret_rotation"},
            ]

        elif preset == "WHEEL_ASSEMBLY":
            axle_len = sx * 0.3
            bones = [
                {"name": f"{pfx}axle", "head": [0, 0, 0], "tail": [axle_len, 0, 0]},
                {"name": f"{pfx}wheel", "head": [axle_len, 0, 0], "tail": [axle_len + 0.05, 0, 0],
                 "parent": f"{pfx}axle", "connected": True},
            ]

        elif preset == "DOOR_HINGE":
            door_h = sz * 0.8
            bones = [
                {"name": f"{pfx}hinge", "head": [0, 0, 0], "tail": [0, 0, door_h]},
                {"name": f"{pfx}door", "head": [0, 0, door_h * 0.5], "tail": [sx * 0.5, 0, door_h * 0.5],
                 "parent": f"{pfx}hinge"},
            ]
            constraints.append({
                "bone": f"{pfx}hinge",
                "type": "LIMIT_ROTATION",
                "settings": {
                    "use_limit_z": True,
                    "min_z": math.radians(-120),
                    "max_z": 0,
                    "owner_space": "LOCAL",
                },
            })

        elif preset == "PISTON":
            piston_len = sy * 0.4
            bones = [
                {"name": f"{pfx}piston_cylinder", "head": [0, 0, 0], "tail": [0, piston_len * 0.6, 0]},
                {"name": f"{pfx}piston_rod", "head": [0, piston_len * 0.4, 0], "tail": [0, piston_len, 0]},
            ]
            constraints.append({
                "bone": f"{pfx}piston_rod",
                "type": "STRETCH_TO",
                "target_bone": f"{pfx}piston_cylinder",
            })

        elif preset == "LANDING_GEAR":
            gear_h = sz * 0.6
            bones = [
                {"name": f"{pfx}gear_mount", "head": [0, 0, gear_h], "tail": [0, 0.02, gear_h]},
                {"name": f"{pfx}gear_strut_upper", "head": [0, 0, gear_h], "tail": [0, 0, gear_h * 0.6],
                 "parent": f"{pfx}gear_mount", "connected": True},
                {"name": f"{pfx}gear_strut_lower", "head": [0, 0, gear_h * 0.6], "tail": [0, 0, gear_h * 0.15],
                 "parent": f"{pfx}gear_strut_upper", "connected": True},
                {"name": f"{pfx}gear_wheel", "head": [0, 0, gear_h * 0.15], "tail": [0.05, 0, gear_h * 0.15],
                 "parent": f"{pfx}gear_strut_lower", "connected": True},
                {"name": f"{pfx}gear_retract_target", "head": [0, sy * 0.3, gear_h], "tail": [0, sy * 0.3 + 0.05, gear_h]},
            ]

        else:
            return {"error": f"Preset '{preset}' not implemented"}

        # Create the armature using armature_create logic
        arm_name = f"{object_name}_{preset.lower()}_rig"
        arm_data = bpy.data.armatures.new(arm_name)
        arm_data.display_type = "OCTAHEDRAL"
        arm_obj = bpy.data.objects.new(arm_name, arm_data)
        bpy.context.collection.objects.link(arm_obj)

        # Position armature at object location
        arm_obj.location = obj.location.copy()

        ensure_object_selected(arm_obj)
        bpy.ops.object.mode_set(mode="EDIT")

        # Create bones
        for bone_def in bones:
            head = bone_def["head"]
            tail = bone_def["tail"]
            roll = math.radians(bone_def.get("roll", 0))

            edit_bone = arm_data.edit_bones.new(bone_def["name"])
            edit_bone.head = (float(head[0]), float(head[1]), float(head[2]))
            edit_bone.tail = (float(tail[0]), float(tail[1]), float(tail[2]))
            edit_bone.roll = roll

        # Set parents
        for bone_def in bones:
            parent_name = bone_def.get("parent")
            if parent_name:
                bone = arm_data.edit_bones.get(bone_def["name"])
                parent = arm_data.edit_bones.get(parent_name)
                if bone and parent:
                    bone.parent = parent
                    bone.use_connect = bone_def.get("connected", False)

        bpy.ops.object.mode_set(mode="OBJECT")

        # Apply constraints if any
        if constraints:
            ensure_object_selected(arm_obj)
            bpy.ops.object.mode_set(mode="POSE")

            for c_def in constraints:
                pose_bone = arm_obj.pose.bones.get(c_def["bone"])
                if pose_bone is None:
                    continue

                c_type = c_def["type"]
                constraint = pose_bone.constraints.new(type=c_type)

                if "target_bone" in c_def:
                    constraint.target = arm_obj
                    constraint.subtarget = c_def["target_bone"]

                if "chain_count" in c_def and hasattr(constraint, "chain_count"):
                    constraint.chain_count = c_def["chain_count"]

                settings = c_def.get("settings", {})
                for key, value in settings.items():
                    if hasattr(constraint, key):
                        setattr(constraint, key, value)

            bpy.ops.object.mode_set(mode="OBJECT")

        # Auto-weight if requested
        weight_result = "skipped"
        if auto_weight:
            try:
                bpy.ops.object.select_all(action="DESELECT")
                obj.select_set(True)
                arm_obj.select_set(True)
                bpy.context.view_layer.objects.active = arm_obj
                bpy.ops.object.parent_set(type="ARMATURE_AUTO")
                weight_result = "success"
            except RuntimeError as e:
                weight_result = f"failed: {str(e)}"

        return {
            "success": True,
            "armature": arm_obj.name,
            "mesh_object": object_name,
            "preset": preset,
            "bone_count": len(bones),
            "bone_names": [b["name"] for b in bones],
            "constraint_count": len(constraints),
            "auto_weight": weight_result,
            "msfs_compatible": msfs_compatible,
        }

    def _handle_constraint_add(self, params: dict) -> dict:
        """Add a constraint to a bone or object."""
        armature_name = params.get("armature_name")
        bone_name = params.get("bone_name")
        object_name = params.get("object_name")
        constraint_type = require_param(params, "constraint_type", str)
        constraint_type = validate_enum(
            constraint_type, "constraint_type",
            [
                "IK", "COPY_ROTATION", "COPY_LOCATION", "COPY_SCALE",
                "TRACK_TO", "DAMPED_TRACK", "STRETCH_TO",
                "LIMIT_ROTATION", "LIMIT_LOCATION", "FLOOR", "CHILD_OF",
            ],
        )
        target_object_name = params.get("target_object")
        target_bone_name = params.get("target_bone")
        influence = float(params.get("influence", 1.0))
        settings = params.get("settings", {})

        # Determine what to add the constraint to
        constraint_owner = None
        owner_desc = ""

        if bone_name and armature_name:
            # Bone constraint
            arm_obj = get_object_or_error(armature_name)
            if arm_obj.type != "ARMATURE":
                raise ValidationError(f"Object '{armature_name}' is not an armature")

            ensure_object_selected(arm_obj)
            if bpy.context.mode != "POSE":
                if bpy.context.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")
                bpy.ops.object.mode_set(mode="POSE")

            pose_bone = arm_obj.pose.bones.get(bone_name)
            if pose_bone is None:
                available = [b.name for b in arm_obj.pose.bones]
                raise ValidationError(
                    f"Bone '{bone_name}' not found in armature '{armature_name}'. "
                    f"Available: {available}"
                )
            constraint_owner = pose_bone
            owner_desc = f"bone '{bone_name}' in '{armature_name}'"

        elif object_name:
            # Object constraint
            target_obj = get_object_or_error(object_name)
            constraint_owner = target_obj
            owner_desc = f"object '{object_name}'"
        else:
            raise ValidationError(
                "Must specify either (armature_name + bone_name) for bone constraint, "
                "or object_name for object constraint"
            )

        # Create the constraint
        constraint = constraint_owner.constraints.new(type=constraint_type)
        constraint.influence = influence

        # Set target
        if target_object_name:
            target_obj = bpy.data.objects.get(target_object_name)
            if target_obj is None:
                raise ValidationError(f"Target object '{target_object_name}' not found")
            constraint.target = target_obj

            if target_bone_name and hasattr(constraint, "subtarget"):
                constraint.subtarget = target_bone_name

        # Apply type-specific settings
        if isinstance(settings, dict):
            for key, value in settings.items():
                if hasattr(constraint, key):
                    try:
                        setattr(constraint, key, value)
                    except (TypeError, AttributeError) as e:
                        pass  # Skip incompatible settings

        # Return to object mode if we were working with bones
        if bone_name and armature_name:
            bpy.ops.object.mode_set(mode="OBJECT")

        return {
            "success": True,
            "owner": owner_desc,
            "constraint_type": constraint_type,
            "constraint_name": constraint.name,
            "target": target_object_name,
            "target_bone": target_bone_name,
            "influence": influence,
        }

    def _handle_constraint_preset(self, params: dict) -> dict:
        """Apply preset constraint setups requiring multiple coordinated constraints."""
        armature_name = require_param(params, "armature_name", str)
        preset = require_param(params, "preset", str)
        preset = validate_enum(
            preset, "preset",
            ["IK_ARM", "IK_LEG", "PISTON_PAIR", "WHEEL_SPIN", "DOOR_SWING", "TURRET_TRACK"],
        )
        bones = require_param(params, "bones")
        if not isinstance(bones, dict):
            raise ValidationError("'bones' must be an object with bone name mappings")

        arm_obj = get_object_or_error(armature_name)
        if arm_obj.type != "ARMATURE":
            raise ValidationError(f"Object '{armature_name}' is not an armature")

        ensure_object_selected(arm_obj)
        if bpy.context.mode != "POSE":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="POSE")

        constraints_added = []

        def get_pose_bone(name):
            pb = arm_obj.pose.bones.get(name)
            if pb is None:
                raise ValidationError(
                    f"Bone '{name}' not found in armature '{armature_name}'. "
                    f"Available: {[b.name for b in arm_obj.pose.bones]}"
                )
            return pb

        if preset == "IK_ARM":
            ik_bone_name = require_param(bones, "ik_bone", str)
            pole_target_name = bones.get("pole_target")
            chain_count = int(bones.get("chain_count", 3))

            ik_bone = get_pose_bone(ik_bone_name)
            c = ik_bone.constraints.new(type="IK")
            c.chain_count = chain_count

            if pole_target_name:
                pole_bone = get_pose_bone(pole_target_name)
                c.pole_target = arm_obj
                c.pole_subtarget = pole_target_name
                c.pole_angle = math.radians(90)

            constraints_added.append({"bone": ik_bone_name, "type": "IK", "chain_count": chain_count})

        elif preset == "IK_LEG":
            ik_bone_name = require_param(bones, "ik_bone", str)
            pole_target_name = bones.get("pole_target")
            foot_bone_name = bones.get("foot_bone")
            chain_count = int(bones.get("chain_count", 2))

            ik_bone = get_pose_bone(ik_bone_name)
            c = ik_bone.constraints.new(type="IK")
            c.chain_count = chain_count

            if pole_target_name:
                c.pole_target = arm_obj
                c.pole_subtarget = pole_target_name
                c.pole_angle = math.radians(-90)

            constraints_added.append({"bone": ik_bone_name, "type": "IK", "chain_count": chain_count})

            # Add copy rotation to foot bone for foot roll
            if foot_bone_name:
                foot_bone = get_pose_bone(foot_bone_name)
                cr = foot_bone.constraints.new(type="COPY_ROTATION")
                cr.target = arm_obj
                cr.subtarget = ik_bone_name
                cr.use_x = True
                cr.use_y = False
                cr.use_z = False
                cr.mix_mode = "ADD"
                cr.target_space = "LOCAL"
                cr.owner_space = "LOCAL"
                constraints_added.append({"bone": foot_bone_name, "type": "COPY_ROTATION"})

        elif preset == "PISTON_PAIR":
            bone_a_name = require_param(bones, "bone_a", str)
            bone_b_name = require_param(bones, "bone_b", str)

            bone_a = get_pose_bone(bone_a_name)
            bone_b = get_pose_bone(bone_b_name)

            # bone_a stretches to bone_b tail
            sa = bone_a.constraints.new(type="STRETCH_TO")
            sa.target = arm_obj
            sa.subtarget = bone_b_name
            sa.rest_length = 0
            sa.bulge = 1.0
            constraints_added.append({"bone": bone_a_name, "type": "STRETCH_TO", "target": bone_b_name})

            # bone_b tracks bone_a
            tb = bone_b.constraints.new(type="DAMPED_TRACK")
            tb.target = arm_obj
            tb.subtarget = bone_a_name
            constraints_added.append({"bone": bone_b_name, "type": "DAMPED_TRACK", "target": bone_a_name})

        elif preset == "WHEEL_SPIN":
            wheel_bone_name = require_param(bones, "wheel_bone", str)
            axis = bones.get("axis", "X").upper()
            if axis not in ("X", "Y", "Z"):
                axis = "X"

            wheel_bone = get_pose_bone(wheel_bone_name)

            # Add a limit rotation to prevent unwanted rotation on other axes
            lr = wheel_bone.constraints.new(type="LIMIT_ROTATION")
            lr.owner_space = "LOCAL"
            lr.use_limit_x = (axis != "X")
            lr.use_limit_y = (axis != "Y")
            lr.use_limit_z = (axis != "Z")
            if axis != "X":
                lr.min_x = 0
                lr.max_x = 0
            if axis != "Y":
                lr.min_y = 0
                lr.max_y = 0
            if axis != "Z":
                lr.min_z = 0
                lr.max_z = 0

            constraints_added.append({
                "bone": wheel_bone_name,
                "type": "LIMIT_ROTATION",
                "free_axis": axis,
            })

        elif preset == "DOOR_SWING":
            hinge_bone_name = require_param(bones, "hinge_bone", str)
            min_angle = float(bones.get("min_angle", -120))
            max_angle = float(bones.get("max_angle", 0))
            axis = bones.get("axis", "Z").upper()
            if axis not in ("X", "Y", "Z"):
                axis = "Z"

            hinge_bone = get_pose_bone(hinge_bone_name)

            lr = hinge_bone.constraints.new(type="LIMIT_ROTATION")
            lr.owner_space = "LOCAL"
            lr.use_limit_x = True
            lr.use_limit_y = True
            lr.use_limit_z = True

            # Allow rotation only on the specified axis
            if axis == "X":
                lr.min_x = math.radians(min_angle)
                lr.max_x = math.radians(max_angle)
            else:
                lr.min_x = 0
                lr.max_x = 0

            if axis == "Y":
                lr.min_y = math.radians(min_angle)
                lr.max_y = math.radians(max_angle)
            else:
                lr.min_y = 0
                lr.max_y = 0

            if axis == "Z":
                lr.min_z = math.radians(min_angle)
                lr.max_z = math.radians(max_angle)
            else:
                lr.min_z = 0
                lr.max_z = 0

            constraints_added.append({
                "bone": hinge_bone_name,
                "type": "LIMIT_ROTATION",
                "axis": axis,
                "min_angle": min_angle,
                "max_angle": max_angle,
            })

        elif preset == "TURRET_TRACK":
            base_bone_name = require_param(bones, "base_bone", str)
            elev_bone_name = require_param(bones, "elevation_bone", str)
            target_bone_name = bones.get("target_bone")

            base_bone = get_pose_bone(base_bone_name)
            elev_bone = get_pose_bone(elev_bone_name)

            # Base bone: track target on Z axis only (horizontal rotation)
            if target_bone_name:
                dt_base = base_bone.constraints.new(type="DAMPED_TRACK")
                dt_base.target = arm_obj
                dt_base.subtarget = target_bone_name
                dt_base.track_axis = "TRACK_Y"

                # Lock to Z-axis rotation only
                lr_base = base_bone.constraints.new(type="LIMIT_ROTATION")
                lr_base.owner_space = "LOCAL"
                lr_base.use_limit_x = True
                lr_base.use_limit_y = True
                lr_base.min_x = 0
                lr_base.max_x = 0
                lr_base.min_y = 0
                lr_base.max_y = 0

                constraints_added.append({"bone": base_bone_name, "type": "DAMPED_TRACK"})
                constraints_added.append({"bone": base_bone_name, "type": "LIMIT_ROTATION"})

                # Elevation bone: track target on local X axis (vertical rotation)
                dt_elev = elev_bone.constraints.new(type="DAMPED_TRACK")
                dt_elev.target = arm_obj
                dt_elev.subtarget = target_bone_name
                dt_elev.track_axis = "TRACK_Y"

                # Limit elevation
                lr_elev = elev_bone.constraints.new(type="LIMIT_ROTATION")
                lr_elev.owner_space = "LOCAL"
                lr_elev.use_limit_x = True
                lr_elev.use_limit_y = True
                lr_elev.use_limit_z = True
                lr_elev.min_x = math.radians(-45)
                lr_elev.max_x = math.radians(30)
                lr_elev.min_y = 0
                lr_elev.max_y = 0
                lr_elev.min_z = 0
                lr_elev.max_z = 0

                constraints_added.append({"bone": elev_bone_name, "type": "DAMPED_TRACK"})
                constraints_added.append({"bone": elev_bone_name, "type": "LIMIT_ROTATION"})

        bpy.ops.object.mode_set(mode="OBJECT")

        return {
            "success": True,
            "armature": armature_name,
            "preset": preset,
            "constraints_added": constraints_added,
            "total_constraints": len(constraints_added),
        }

    def _handle_bone_shape_assign(self, params: dict) -> dict:
        """Assign a custom wireframe control shape to a bone."""
        armature_name = require_param(params, "armature_name", str)
        bone_name = require_param(params, "bone_name", str)
        shape = require_param(params, "shape", str)
        shape = validate_enum(
            shape, "shape",
            ["CIRCLE", "SQUARE", "CUBE", "SPHERE", "ARROW", "DIAMOND", "CROSS"],
        )
        scale = float(params.get("scale", 1.0))

        arm_obj = get_object_or_error(armature_name)
        if arm_obj.type != "ARMATURE":
            raise ValidationError(f"Object '{armature_name}' is not an armature")

        # Check bone exists
        if bone_name not in arm_obj.data.bones:
            available = [b.name for b in arm_obj.data.bones]
            raise ValidationError(
                f"Bone '{bone_name}' not found. Available: {available}"
            )

        # Create or find the shape widget object
        widget_name = f"WGT_{shape.lower()}"
        widget_obj = bpy.data.objects.get(widget_name)

        if widget_obj is None:
            import bmesh

            bm = bmesh.new()

            if shape == "CIRCLE":
                segments = 16
                for i in range(segments):
                    angle = 2 * math.pi * i / segments
                    bm.verts.new((math.cos(angle), math.sin(angle), 0))
                bm.verts.ensure_lookup_table()
                for i in range(segments):
                    bm.edges.new((bm.verts[i], bm.verts[(i + 1) % segments]))

            elif shape == "SQUARE":
                verts = [
                    bm.verts.new((-1, -1, 0)),
                    bm.verts.new((1, -1, 0)),
                    bm.verts.new((1, 1, 0)),
                    bm.verts.new((-1, 1, 0)),
                ]
                for i in range(4):
                    bm.edges.new((verts[i], verts[(i + 1) % 4]))

            elif shape == "CUBE":
                # Wireframe cube
                coords = [
                    (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                    (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
                ]
                for c in coords:
                    bm.verts.new(c)
                bm.verts.ensure_lookup_table()
                edges_idx = [
                    (0, 1), (1, 2), (2, 3), (3, 0),
                    (4, 5), (5, 6), (6, 7), (7, 4),
                    (0, 4), (1, 5), (2, 6), (3, 7),
                ]
                for a, b in edges_idx:
                    bm.edges.new((bm.verts[a], bm.verts[b]))

            elif shape == "SPHERE":
                # Simple wireframe sphere (3 circles)
                segments = 16
                for axis in range(3):
                    offset = len(bm.verts)
                    for i in range(segments):
                        angle = 2 * math.pi * i / segments
                        if axis == 0:
                            bm.verts.new((0, math.cos(angle), math.sin(angle)))
                        elif axis == 1:
                            bm.verts.new((math.cos(angle), 0, math.sin(angle)))
                        else:
                            bm.verts.new((math.cos(angle), math.sin(angle), 0))
                    bm.verts.ensure_lookup_table()
                    for i in range(segments):
                        bm.edges.new((bm.verts[offset + i], bm.verts[offset + (i + 1) % segments]))

            elif shape == "ARROW":
                verts = [
                    bm.verts.new((0, 0, 0)),
                    bm.verts.new((0, 2, 0)),
                    bm.verts.new((-0.5, 1.5, 0)),
                    bm.verts.new((0.5, 1.5, 0)),
                ]
                bm.edges.new((verts[0], verts[1]))
                bm.edges.new((verts[1], verts[2]))
                bm.edges.new((verts[1], verts[3]))

            elif shape == "DIAMOND":
                verts = [
                    bm.verts.new((0, -1, 0)),
                    bm.verts.new((1, 0, 0)),
                    bm.verts.new((0, 1, 0)),
                    bm.verts.new((-1, 0, 0)),
                    bm.verts.new((0, 0, 1)),
                    bm.verts.new((0, 0, -1)),
                ]
                edges_idx = [
                    (0, 1), (1, 2), (2, 3), (3, 0),
                    (0, 4), (1, 4), (2, 4), (3, 4),
                    (0, 5), (1, 5), (2, 5), (3, 5),
                ]
                for a, b in edges_idx:
                    bm.edges.new((verts[a], verts[b]))

            elif shape == "CROSS":
                verts = [
                    bm.verts.new((-1, 0, 0)),
                    bm.verts.new((1, 0, 0)),
                    bm.verts.new((0, -1, 0)),
                    bm.verts.new((0, 1, 0)),
                    bm.verts.new((0, 0, -1)),
                    bm.verts.new((0, 0, 1)),
                ]
                bm.edges.new((verts[0], verts[1]))
                bm.edges.new((verts[2], verts[3]))
                bm.edges.new((verts[4], verts[5]))

            # Create mesh and object
            mesh = bpy.data.meshes.new(widget_name)
            bm.to_mesh(mesh)
            bm.free()

            widget_obj = bpy.data.objects.new(widget_name, mesh)
            # Put in a hidden collection for widgets
            wgt_collection = bpy.data.collections.get("Widgets")
            if wgt_collection is None:
                wgt_collection = bpy.data.collections.new("Widgets")
                bpy.context.scene.collection.children.link(wgt_collection)
                # Hide the widgets collection
                layer_collection = bpy.context.view_layer.layer_collection
                for child in layer_collection.children:
                    if child.collection == wgt_collection:
                        child.hide_viewport = True
                        break
            wgt_collection.objects.link(widget_obj)
            widget_obj.display_type = "WIRE"
            widget_obj.hide_render = True

        # Assign shape to bone
        ensure_object_selected(arm_obj)
        if bpy.context.mode != "POSE":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="POSE")

        pose_bone = arm_obj.pose.bones.get(bone_name)
        if pose_bone is None:
            bpy.ops.object.mode_set(mode="OBJECT")
            raise ValidationError(f"Pose bone '{bone_name}' not found")

        pose_bone.custom_shape = widget_obj
        pose_bone.custom_shape_scale_xyz = (scale, scale, scale)
        pose_bone.use_custom_shape_bone_size = True

        bpy.ops.object.mode_set(mode="OBJECT")

        return {
            "success": True,
            "armature": armature_name,
            "bone": bone_name,
            "shape": shape,
            "widget_object": widget_obj.name,
            "scale": scale,
        }

    def _handle_pose_library_save(self, params: dict) -> dict:
        """Save the current pose as a named pose in custom properties."""
        armature_name = require_param(params, "armature_name", str)
        pose_name = require_param(params, "pose_name", str)
        bone_filter = params.get("bone_filter")

        arm_obj = get_object_or_error(armature_name)
        if arm_obj.type != "ARMATURE":
            raise ValidationError(f"Object '{armature_name}' is not an armature")

        # Enter pose mode to read pose bone transforms
        ensure_object_selected(arm_obj)
        if bpy.context.mode != "POSE":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="POSE")

        pose_data = {}
        bones_saved = []

        for pose_bone in arm_obj.pose.bones:
            if bone_filter and pose_bone.name not in bone_filter:
                continue

            # Store location, rotation (quaternion), and scale
            pose_data[pose_bone.name] = {
                "location": list(pose_bone.location),
                "rotation_quaternion": list(pose_bone.rotation_quaternion),
                "rotation_euler": list(pose_bone.rotation_euler),
                "rotation_mode": pose_bone.rotation_mode,
                "scale": list(pose_bone.scale),
            }
            bones_saved.append(pose_bone.name)

        bpy.ops.object.mode_set(mode="OBJECT")

        # Store in custom property as JSON
        prop_key = f"_pose_lib_{pose_name}"
        arm_obj[prop_key] = json.dumps(pose_data)

        # Also maintain an index of saved poses
        index_key = "_pose_lib_index"
        existing_index = json.loads(arm_obj.get(index_key, "[]"))
        if pose_name not in existing_index:
            existing_index.append(pose_name)
        arm_obj[index_key] = json.dumps(existing_index)

        return {
            "success": True,
            "armature": armature_name,
            "pose_name": pose_name,
            "bones_saved": bones_saved,
            "bone_count": len(bones_saved),
            "all_saved_poses": existing_index,
        }

    def _handle_pose_library_apply(self, params: dict) -> dict:
        """Apply a previously saved pose to an armature."""
        from mathutils import Quaternion, Euler, Vector

        armature_name = require_param(params, "armature_name", str)
        pose_name = require_param(params, "pose_name", str)
        blend_factor = float(params.get("blend_factor", 1.0))
        blend_factor = max(0.0, min(1.0, blend_factor))

        arm_obj = get_object_or_error(armature_name)
        if arm_obj.type != "ARMATURE":
            raise ValidationError(f"Object '{armature_name}' is not an armature")

        # Load pose data from custom property
        prop_key = f"_pose_lib_{pose_name}"
        pose_json = arm_obj.get(prop_key)
        if pose_json is None:
            # List available poses
            index_key = "_pose_lib_index"
            available = json.loads(arm_obj.get(index_key, "[]"))
            raise ValidationError(
                f"Pose '{pose_name}' not found. Available poses: {available}"
            )

        pose_data = json.loads(pose_json)

        # Enter pose mode
        ensure_object_selected(arm_obj)
        if bpy.context.mode != "POSE":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="POSE")

        bones_applied = []
        bones_skipped = []

        for bone_name, transforms in pose_data.items():
            pose_bone = arm_obj.pose.bones.get(bone_name)
            if pose_bone is None:
                bones_skipped.append(bone_name)
                continue

            saved_loc = Vector(transforms["location"])
            saved_scale = Vector(transforms["scale"])
            saved_rot_mode = transforms["rotation_mode"]

            if blend_factor >= 1.0:
                # Full application
                pose_bone.location = saved_loc
                pose_bone.scale = saved_scale
                if saved_rot_mode == "QUATERNION":
                    pose_bone.rotation_mode = "QUATERNION"
                    pose_bone.rotation_quaternion = Quaternion(transforms["rotation_quaternion"])
                else:
                    pose_bone.rotation_mode = saved_rot_mode
                    pose_bone.rotation_euler = Euler(transforms["rotation_euler"])
            else:
                # Blend with current pose
                current_loc = pose_bone.location.copy()
                current_scale = pose_bone.scale.copy()

                pose_bone.location = current_loc.lerp(saved_loc, blend_factor)
                pose_bone.scale = current_scale.lerp(saved_scale, blend_factor)

                if saved_rot_mode == "QUATERNION":
                    current_quat = pose_bone.rotation_quaternion.copy()
                    saved_quat = Quaternion(transforms["rotation_quaternion"])
                    pose_bone.rotation_mode = "QUATERNION"
                    pose_bone.rotation_quaternion = current_quat.slerp(saved_quat, blend_factor)
                else:
                    current_euler = pose_bone.rotation_euler.copy()
                    saved_euler = Euler(transforms["rotation_euler"])
                    # Linear interpolation for Euler angles
                    pose_bone.rotation_mode = saved_rot_mode
                    pose_bone.rotation_euler = Euler((
                        current_euler.x + (saved_euler.x - current_euler.x) * blend_factor,
                        current_euler.y + (saved_euler.y - current_euler.y) * blend_factor,
                        current_euler.z + (saved_euler.z - current_euler.z) * blend_factor,
                    ))

            bones_applied.append(bone_name)

        bpy.ops.object.mode_set(mode="OBJECT")

        return {
            "success": True,
            "armature": armature_name,
            "pose_name": pose_name,
            "blend_factor": blend_factor,
            "bones_applied": bones_applied,
            "bones_skipped": bones_skipped,
        }

    def _handle_rig_validate(self, params: dict) -> dict:
        """Validate an armature rig for export compatibility."""
        armature_name = require_param(params, "armature_name", str)
        target_format = params.get("target_format", "GENERIC")
        target_format = validate_enum(
            target_format, "target_format", ["MIXAMO", "UE5", "MSFS", "GENERIC"]
        )

        arm_obj = get_object_or_error(armature_name)
        if arm_obj.type != "ARMATURE":
            raise ValidationError(f"Object '{armature_name}' is not an armature")

        arm_data = arm_obj.data
        issues = []
        warnings = []
        info = []

        bone_count = len(arm_data.bones)

        # Basic checks (all formats)
        # Check for zero-length bones
        for bone in arm_data.bones:
            length = (bone.tail_local - bone.head_local).length
            if length < 0.0001:
                issues.append(f"Zero-length bone: '{bone.name}' (will cause export issues)")

        # Check for non-uniform armature scale
        scale = arm_obj.scale
        if abs(scale.x - 1.0) > 0.01 or abs(scale.y - 1.0) > 0.01 or abs(scale.z - 1.0) > 0.01:
            warnings.append(
                f"Armature has non-unit scale ({scale.x:.3f}, {scale.y:.3f}, {scale.z:.3f}). "
                "Apply scale before export."
            )

        # Check rotation
        rot = arm_obj.rotation_euler
        if abs(rot.x) > 0.01 or abs(rot.y) > 0.01 or abs(rot.z) > 0.01:
            warnings.append(
                f"Armature has non-zero rotation. Apply rotation before export."
            )

        # Check for bones without deform flag
        deform_bones = [b for b in arm_data.bones if b.use_deform]
        non_deform_bones = [b for b in arm_data.bones if not b.use_deform]
        info.append(f"Deform bones: {len(deform_bones)}, Non-deform: {len(non_deform_bones)}")

        # Check for disconnected bone hierarchy (orphan bones)
        root_bones = [b for b in arm_data.bones if b.parent is None]
        if len(root_bones) > 1:
            root_names = [b.name for b in root_bones]
            warnings.append(f"Multiple root bones found: {root_names}. Most formats expect a single root.")

        # Check constraints
        constraint_count = 0
        constraint_issues = []
        ensure_object_selected(arm_obj)
        if bpy.context.mode != "POSE":
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="POSE")

        for pose_bone in arm_obj.pose.bones:
            for c in pose_bone.constraints:
                constraint_count += 1
                if c.mute:
                    continue
                # Check for missing targets
                if hasattr(c, "target") and c.target is None:
                    constraint_issues.append(
                        f"Bone '{pose_bone.name}' constraint '{c.name}' ({c.type}) has no target"
                    )

        bpy.ops.object.mode_set(mode="OBJECT")

        if constraint_issues:
            issues.extend(constraint_issues)

        # Format-specific checks
        if target_format == "MIXAMO":
            # Mixamo expects specific bone naming
            mixamo_required = ["Hips", "Spine", "Head"]
            mixamo_found = []
            for req in mixamo_required:
                found = any(req.lower() in b.name.lower() for b in arm_data.bones)
                if found:
                    mixamo_found.append(req)
                else:
                    warnings.append(f"Mixamo: missing expected bone containing '{req}'")
            info.append(f"Mixamo bones found: {mixamo_found}")

        elif target_format == "UE5":
            # UE5 expects root bone at origin
            if root_bones:
                root = root_bones[0]
                if root.head_local.length > 0.01:
                    warnings.append(
                        f"UE5: root bone '{root.name}' head is not at origin "
                        f"({list(root.head_local)})"
                    )
            # Check max bone count
            if bone_count > 256:
                issues.append(f"UE5: bone count ({bone_count}) exceeds recommended max of 256")

        elif target_format == "MSFS":
            # MSFS checks
            if bone_count > 128:
                warnings.append(f"MSFS: bone count ({bone_count}) is high; consider simplifying")
            # Check for special naming
            msfs_bones = [b for b in arm_data.bones if b.name.startswith("bone_")]
            if msfs_bones:
                info.append(f"MSFS-prefixed bones: {len(msfs_bones)}")

        # Check attached meshes
        child_meshes = [
            child for child in arm_obj.children
            if child.type == "MESH"
        ]
        mesh_info = []
        for mesh_obj in child_meshes:
            # Check for armature modifier
            has_armature_mod = any(
                mod.type == "ARMATURE" and mod.object == arm_obj
                for mod in mesh_obj.modifiers
            )
            # Check vertex groups match bones
            vg_names = [vg.name for vg in mesh_obj.vertex_groups]
            matching_bones = [name for name in vg_names if name in arm_data.bones]
            unmatched_groups = [name for name in vg_names if name not in arm_data.bones]

            mesh_info.append({
                "mesh": mesh_obj.name,
                "has_armature_modifier": has_armature_mod,
                "vertex_groups": len(vg_names),
                "matching_bone_groups": len(matching_bones),
                "unmatched_groups": len(unmatched_groups),
            })

            if not has_armature_mod:
                warnings.append(f"Mesh '{mesh_obj.name}' is child but has no Armature modifier")
            if unmatched_groups:
                warnings.append(
                    f"Mesh '{mesh_obj.name}' has {len(unmatched_groups)} vertex groups "
                    f"not matching any bone"
                )

        # Calculate compatibility score
        max_score = 100
        score = max_score
        score -= len(issues) * 15  # Critical issues
        score -= len(warnings) * 5  # Warnings
        score = max(0, min(100, score))

        return {
            "success": True,
            "armature": armature_name,
            "target_format": target_format,
            "compatibility_score": score,
            "bone_count": bone_count,
            "root_bones": [b.name for b in root_bones],
            "deform_bone_count": len(deform_bones),
            "constraint_count": constraint_count,
            "child_meshes": mesh_info,
            "issues": issues,
            "warnings": warnings,
            "info": info,
        }


    # ========== Physics Simulation Handlers ==========

    def _handle_physics_rigid_body_add(self, params: dict) -> dict:
        """Add a rigid body physics simulation to an object."""
        object_name = require_param(params, "object_name", str)
        body_type = params.get("body_type", "ACTIVE")
        mass = float(params.get("mass", 1.0))
        friction = float(params.get("friction", 0.5))
        bounciness = float(params.get("bounciness", 0.0))
        collision_shape = params.get("collision_shape", "CONVEX_HULL")

        # Validate enums
        body_type = validate_enum(
            body_type, "body_type", ["ACTIVE", "PASSIVE"]
        )
        collision_shape = validate_enum(
            collision_shape,
            "collision_shape",
            ["BOX", "SPHERE", "CAPSULE", "CYLINDER", "CONE", "CONVEX_HULL", "MESH"],
        )

        obj = get_object_or_error(object_name)

        # Ensure rigid body world exists
        scene = bpy.context.scene
        if scene.rigidbody_world is None:
            bpy.ops.rigidbody.world_add()

        # Select and activate the object
        ensure_object_selected(obj)

        # Add rigid body
        bpy.ops.rigidbody.object_add(type=body_type)

        # Configure rigid body properties
        rb = obj.rigid_body
        rb.mass = mass
        rb.friction = friction
        rb.restitution = bounciness
        rb.collision_shape = collision_shape

        return {
            "success": True,
            "object": obj.name,
            "body_type": body_type,
            "mass": mass,
            "friction": friction,
            "bounciness": bounciness,
            "collision_shape": collision_shape,
        }

    def _handle_physics_rigid_body_batch(self, params: dict) -> dict:
        """Add rigid bodies to multiple objects at once."""
        object_names = require_param(params, "object_names", list)
        body_type = params.get("body_type", "ACTIVE")
        mass = float(params.get("mass", 1.0))
        ground_object = params.get("ground_object")

        body_type = validate_enum(
            body_type, "body_type", ["ACTIVE", "PASSIVE"]
        )

        # Ensure rigid body world exists
        scene = bpy.context.scene
        if scene.rigidbody_world is None:
            bpy.ops.rigidbody.world_add()

        results = []
        errors = []

        # Process each object
        for name in object_names:
            obj = bpy.data.objects.get(name)
            if obj is None:
                errors.append(f"Object not found: {name}")
                continue

            ensure_object_selected(obj)

            try:
                bpy.ops.rigidbody.object_add(type=body_type)
                obj.rigid_body.mass = mass
                results.append({
                    "object": obj.name,
                    "body_type": body_type,
                    "mass": mass,
                })
            except Exception as e:
                errors.append(f"Failed to add rigid body to '{name}': {str(e)}")

        # Handle ground object separately
        ground_result = None
        if ground_object:
            g_obj = bpy.data.objects.get(ground_object)
            if g_obj is None:
                errors.append(f"Ground object not found: {ground_object}")
            else:
                ensure_object_selected(g_obj)
                try:
                    # Remove existing rigid body if any, then add as PASSIVE
                    if g_obj.rigid_body is not None:
                        bpy.ops.rigidbody.object_remove()
                    bpy.ops.rigidbody.object_add(type="PASSIVE")
                    g_obj.rigid_body.friction = 0.5
                    g_obj.rigid_body.collision_shape = "MESH"
                    ground_result = {
                        "object": g_obj.name,
                        "body_type": "PASSIVE",
                        "collision_shape": "MESH",
                    }
                except Exception as e:
                    errors.append(
                        f"Failed to set ground object '{ground_object}': {str(e)}"
                    )

        response = {
            "success": True,
            "objects_processed": len(results),
            "results": results,
        }
        if ground_result:
            response["ground_object"] = ground_result
        if errors:
            response["errors"] = errors
            # Still mark success if at least some objects were processed
            response["success"] = len(results) > 0 or ground_result is not None

        return response

    def _handle_physics_simulate(self, params: dict) -> dict:
        """Run physics simulation and optionally apply results."""
        frame_start = int(params.get("frame_start", 1))
        frame_end = int(params.get("frame_end", 250))
        apply_results = params.get("apply_results", False)

        scene = bpy.context.scene

        # Ensure rigid body world exists
        if scene.rigidbody_world is None:
            return {"error": "No rigid body world found. Add rigid bodies first."}

        # Set frame range
        scene.frame_start = frame_start
        scene.frame_end = frame_end
        scene.rigidbody_world.point_cache.frame_start = frame_start
        scene.rigidbody_world.point_cache.frame_end = frame_end

        # Bake the simulation
        try:
            # Free existing bake first
            bpy.ops.ptcache.free_bake_all()
            bpy.ops.ptcache.bake_all(bake=True)
        except Exception as e:
            return {"error": f"Failed to bake simulation: {str(e)}"}

        # Move to the last frame to capture final positions
        scene.frame_set(frame_end)

        # Collect final positions of rigid body objects
        final_positions = {}
        rb_group = scene.rigidbody_world.group
        if rb_group:
            for obj in rb_group.objects:
                final_positions[obj.name] = {
                    "location": serialize_vector(obj.location),
                    "rotation_euler": serialize_vector(obj.rotation_euler),
                }

        # Apply results if requested
        applied_objects = []
        if apply_results:
            if rb_group:
                # Iterate over a copy of the list since we modify it
                for obj in list(rb_group.objects):
                    ensure_object_selected(obj)
                    try:
                        # Apply visual transform to mesh
                        bpy.ops.object.visual_transform_apply()
                        # Remove rigid body
                        bpy.ops.rigidbody.object_remove()
                        applied_objects.append(obj.name)
                    except Exception as e:
                        # Skip objects that fail
                        pass

        response = {
            "success": True,
            "frame_range": [frame_start, frame_end],
            "final_positions": final_positions,
            "rigid_body_count": len(final_positions),
        }
        if apply_results:
            response["applied_objects"] = applied_objects
            response["results_applied"] = True

        return response


    # Cloth simulation presets: {quality_steps, mass, air_damping, tension_stiffness,
    #   compression_stiffness, bending_stiffness, tension_damping, compression_damping,
    #   bending_damping}

    def _handle_physics_cloth_add(self, params: dict) -> dict:
        """Add cloth simulation to a mesh object."""
        object_name = require_param(params, "object_name", str)
        preset_name = params.get("preset", "COTTON")
        pin_vertex_group = params.get("pin_vertex_group")
        collision_objects = params.get("collision_objects", [])
        wind_strength = float(params.get("wind_strength", 0.0))
        wind_direction = params.get("wind_direction", [1, 0, 0])

        preset_name = validate_enum(
            preset_name,
            "preset",
            ["SILK", "COTTON", "DENIM", "LEATHER", "RUBBER", "CANVAS", "TARP"],
        )

        obj = get_object_or_error(object_name)

        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is type {obj.type}, not MESH. Cloth requires a mesh object."}

        # Select and activate the object
        ensure_object_selected(obj)

        # Add cloth modifier
        bpy.ops.object.modifier_add(type='CLOTH')
        cloth_mod = obj.modifiers.get("Cloth")
        if cloth_mod is None:
            return {"error": "Failed to add cloth modifier"}

        cloth_settings = cloth_mod.settings

        # Apply preset
        preset = _CLOTH_PRESETS[preset_name]
        cloth_settings.quality = preset["quality"]
        cloth_settings.mass = preset["mass"]
        cloth_settings.air_damping = preset["air_damping"]
        cloth_settings.tension_stiffness = preset["tension_stiffness"]
        cloth_settings.compression_stiffness = preset["compression_stiffness"]
        cloth_settings.bending_stiffness = preset["bending_stiffness"]
        cloth_settings.tension_damping = preset["tension_damping"]
        cloth_settings.compression_damping = preset["compression_damping"]
        cloth_settings.bending_damping = preset["bending_damping"]

        # Set up pin group if specified
        if pin_vertex_group:
            vg = obj.vertex_groups.get(pin_vertex_group)
            if vg is None:
                return {
                    "error": f"Vertex group '{pin_vertex_group}' not found on '{object_name}'. "
                    f"Available: {[vg.name for vg in obj.vertex_groups]}"
                }
            cloth_settings.vertex_group_mass = pin_vertex_group

        # Add collision modifiers to collision objects
        collision_results = []
        collision_errors = []
        for col_name in collision_objects:
            col_obj = bpy.data.objects.get(col_name)
            if col_obj is None:
                collision_errors.append(f"Collision object not found: {col_name}")
                continue

            # Check if it already has a collision modifier
            has_collision = any(m.type == 'COLLISION' for m in col_obj.modifiers)
            if not has_collision:
                ensure_object_selected(col_obj)
                try:
                    bpy.ops.object.modifier_add(type='COLLISION')
                    collision_results.append(col_name)
                except Exception as e:
                    collision_errors.append(
                        f"Failed to add collision to '{col_name}': {str(e)}"
                    )
            else:
                collision_results.append(f"{col_name} (already had collision)")

        # Set up wind force field if wind_strength > 0
        wind_obj_name = None
        if wind_strength > 0:
            # Validate wind direction
            if not isinstance(wind_direction, (list, tuple)) or len(wind_direction) != 3:
                wind_direction = [1, 0, 0]

            # Calculate rotation from direction vector
            dx, dy, dz = [float(v) for v in wind_direction]
            length = math.sqrt(dx * dx + dy * dy + dz * dz)
            if length > 0:
                dx, dy, dz = dx / length, dy / length, dz / length

            # Create a wind force field
            bpy.ops.object.effector_add(type='WIND', location=(0, 0, 0))
            wind_obj = bpy.context.active_object
            wind_obj.name = f"Wind_{object_name}"
            wind_obj.field.strength = wind_strength

            # Set rotation to match direction
            # Wind default direction is -Z, so we compute rotation to align
            # Using atan2 for azimuth and elevation
            wind_obj.rotation_euler[0] = math.asin(dy) if abs(dy) <= 1 else 0
            wind_obj.rotation_euler[1] = 0
            wind_obj.rotation_euler[2] = math.atan2(dx, -dz)

            wind_obj_name = wind_obj.name

        response = {
            "success": True,
            "object": obj.name,
            "preset": preset_name,
            "preset_settings": preset,
        }
        if pin_vertex_group:
            response["pin_group"] = pin_vertex_group
        if collision_results:
            response["collision_objects"] = collision_results
        if collision_errors:
            response["collision_errors"] = collision_errors
        if wind_obj_name:
            response["wind_object"] = wind_obj_name
            response["wind_strength"] = wind_strength
            response["wind_direction"] = [float(v) for v in wind_direction]

        return response

    def _handle_physics_soft_body_add(self, params: dict) -> dict:
        """Add soft body simulation to a mesh object."""
        object_name = require_param(params, "object_name", str)
        goal_strength = float(params.get("goal_strength", 0.7))
        mass = float(params.get("mass", 1.0))
        friction = float(params.get("friction", 0.5))

        obj = get_object_or_error(object_name)

        if obj.type != "MESH":
            return {"error": f"Object '{object_name}' is type {obj.type}, not MESH. Soft body requires a mesh object."}

        # Select and activate the object
        ensure_object_selected(obj)

        # Add soft body modifier
        bpy.ops.object.modifier_add(type='SOFT_BODY')
        sb_mod = obj.modifiers.get("Softbody")
        if sb_mod is None:
            # Blender may name it differently
            for mod in obj.modifiers:
                if mod.type == 'SOFT_BODY':
                    sb_mod = mod
                    break
        if sb_mod is None:
            return {"error": "Failed to add soft body modifier"}

        # Configure soft body settings
        sb = obj.modifiers[sb_mod.name].settings

        # Goal settings (how strongly vertices stick to original position)
        sb.goal_spring = goal_strength
        sb.goal_friction = 0.5

        # Mass
        sb.mass = mass

        # Friction (edge spring friction in Blender soft body)
        sb.friction = friction

        # Enable self-collision for better results
        sb.use_self_collision = True

        return {
            "success": True,
            "object": obj.name,
            "goal_strength": goal_strength,
            "mass": mass,
            "friction": friction,
            "modifier": sb_mod.name,
        }

    def _handle_physics_fluid_quick(self, params: dict) -> dict:
        """Quick fluid simulation setup with domain and flow objects."""
        domain_name = require_param(params, "domain_object", str)
        flow_name = require_param(params, "flow_object", str)
        fluid_type = params.get("fluid_type", "LIQUID")
        resolution = int(params.get("resolution", 64))
        viscosity = float(params.get("viscosity", 0.0))

        fluid_type = validate_enum(
            fluid_type, "fluid_type", ["LIQUID", "GAS"]
        )

        domain_obj = get_object_or_error(domain_name)
        flow_obj = get_object_or_error(flow_name)

        if domain_obj.type != "MESH":
            return {"error": f"Domain object '{domain_name}' is type {domain_obj.type}, not MESH."}
        if flow_obj.type != "MESH":
            return {"error": f"Flow object '{flow_name}' is type {flow_obj.type}, not MESH."}

        # --- Set up domain object ---
        ensure_object_selected(domain_obj)

        # Add fluid modifier as domain
        bpy.ops.object.modifier_add(type='FLUID')
        fluid_mod = None
        for mod in domain_obj.modifiers:
            if mod.type == 'FLUID':
                fluid_mod = mod
                break
        if fluid_mod is None:
            return {"error": "Failed to add fluid modifier to domain object"}

        # Set as domain
        fluid_mod.fluid_type = 'DOMAIN'
        domain_settings = fluid_mod.domain_settings

        # Configure domain type
        domain_settings.domain_type = fluid_type

        # Set resolution
        domain_settings.resolution_max = resolution

        # Set viscosity for liquid
        if fluid_type == "LIQUID" and viscosity > 0:
            domain_settings.use_viscosity = True
            domain_settings.viscosity_value = viscosity

        # Set cache type to modular for better control
        domain_settings.cache_type = 'MODULAR'

        # --- Set up flow object ---
        ensure_object_selected(flow_obj)

        bpy.ops.object.modifier_add(type='FLUID')
        flow_mod = None
        for mod in flow_obj.modifiers:
            if mod.type == 'FLUID':
                flow_mod = mod
                break
        if flow_mod is None:
            return {"error": "Failed to add fluid modifier to flow object"}

        # Set as flow (inflow)
        flow_mod.fluid_type = 'FLOW'
        flow_settings = flow_mod.flow_settings
        flow_settings.flow_type = fluid_type
        flow_settings.flow_behavior = 'INFLOW'

        return {
            "success": True,
            "domain": {
                "object": domain_obj.name,
                "type": "DOMAIN",
                "domain_type": fluid_type,
                "resolution": resolution,
                "viscosity": viscosity,
            },
            "flow": {
                "object": flow_obj.name,
                "type": "FLOW",
                "flow_type": fluid_type,
                "behavior": "INFLOW",
            },
            "note": "Use bpy.ops.fluid.bake_all() or the Physics tab to bake the simulation before rendering.",
        }


    # ========== Annotation & Grease Pencil Handlers ==========

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
                available = [l.info for l in gpd.layers]
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


    def _handle_material_inspect_graph(self, params: dict) -> dict:
        """Return the full shader node graph as structured JSON."""
        material_name = require_param(params, "material_name", str)
        mat = get_material_or_error(material_name)

        if not mat.use_nodes or mat.node_tree is None:
            return {
                "material": mat.name,
                "use_nodes": False,
                "nodes": [],
                "links": [],
            }

        tree = mat.node_tree

        # --- Serialise nodes ---
        nodes_out = []
        for node in tree.nodes:
            node_data = {
                "name": node.name,
                "type": node.type,
                "bl_idname": node.bl_idname,
                "label": node.label,
                "location": [node.location.x, node.location.y],
                "inputs": [],
                "outputs": [],
            }

            # Inputs
            for inp in node.inputs:
                inp_data: dict[str, Any] = {
                    "name": inp.name,
                    "type": inp.type,
                    "is_linked": inp.is_linked,
                }
                if hasattr(inp, "default_value"):
                    try:
                        val = inp.default_value
                        if hasattr(val, "__iter__") and not isinstance(val, str):
                            inp_data["default_value"] = [float(v) for v in val]
                        else:
                            inp_data["default_value"] = float(val)
                    except (TypeError, ValueError):
                        inp_data["default_value"] = str(val)
                node_data["inputs"].append(inp_data)

            # Outputs
            for out in node.outputs:
                out_data: dict[str, Any] = {
                    "name": out.name,
                    "type": out.type,
                    "is_linked": out.is_linked,
                }
                node_data["outputs"].append(out_data)

            nodes_out.append(node_data)

        # --- Serialise links ---
        links_out = []
        for link in tree.links:
            links_out.append({
                "from_node": link.from_node.name,
                "from_output": link.from_socket.name,
                "to_node": link.to_node.name,
                "to_input": link.to_socket.name,
            })

        return {
            "material": mat.name,
            "use_nodes": True,
            "node_count": len(nodes_out),
            "link_count": len(links_out),
            "nodes": nodes_out,
            "links": links_out,
        }


    # =====================================================================
    # 2. material_node_add

    # =====================================================================

    def _handle_material_node_add(self, params: dict) -> dict:
        """Add a shader node to a material."""
        material_name = require_param(params, "material_name", str)
        node_type = require_param(params, "node_type", str)
        mat = get_material_or_error(material_name)

        if not mat.use_nodes:
            mat.use_nodes = True

        tree = mat.node_tree

        try:
            node = tree.nodes.new(node_type)
        except RuntimeError as exc:
            return {"error": f"Failed to create node of type '{node_type}': {exc}"}

        # Optional name
        name = params.get("name")
        if name:
            node.name = name
            node.label = name

        # Optional location
        location = params.get("location")
        if location and isinstance(location, (list, tuple)) and len(location) >= 2:
            node.location = (float(location[0]), float(location[1]))

        # Optional input default values
        inputs = params.get("inputs")
        if inputs and isinstance(inputs, dict):
            for input_name, value in inputs.items():
                if input_name in node.inputs:
                    inp = node.inputs[input_name]
                    if hasattr(inp, "default_value"):
                        try:
                            if isinstance(value, (list, tuple)):
                                inp.default_value = value
                            else:
                                inp.default_value = float(value)
                        except (TypeError, ValueError):
                            pass  # skip incompatible types silently

        return {
            "material": mat.name,
            "node_name": node.name,
            "node_type": node.bl_idname,
            "location": [node.location.x, node.location.y],
        }


    # =====================================================================
    # 3. material_node_connect

    # =====================================================================

    def _handle_material_node_connect(self, params: dict) -> dict:
        """Connect two nodes in a material's node graph."""
        material_name = require_param(params, "material_name", str)
        from_node_name = require_param(params, "from_node", str)
        from_output_name = require_param(params, "from_output", str)
        to_node_name = require_param(params, "to_node", str)
        to_input_name = require_param(params, "to_input", str)

        mat = get_material_or_error(material_name)

        if not mat.use_nodes or mat.node_tree is None:
            return {"error": f"Material '{material_name}' has no node tree"}

        tree = mat.node_tree

        # Look up nodes
        from_node = tree.nodes.get(from_node_name)
        if from_node is None:
            return {"error": f"Node not found: '{from_node_name}'"}

        to_node = tree.nodes.get(to_node_name)
        if to_node is None:
            return {"error": f"Node not found: '{to_node_name}'"}

        # Look up sockets
        from_socket = from_node.outputs.get(from_output_name)
        if from_socket is None:
            available = [o.name for o in from_node.outputs]
            return {"error": f"Output '{from_output_name}' not found on '{from_node_name}'. Available: {available}"}

        to_socket = to_node.inputs.get(to_input_name)
        if to_socket is None:
            available = [i.name for i in to_node.inputs]
            return {"error": f"Input '{to_input_name}' not found on '{to_node_name}'. Available: {available}"}

        link = tree.links.new(from_socket, to_socket)

        return {
            "material": mat.name,
            "link": {
                "from_node": from_node.name,
                "from_output": from_socket.name,
                "to_node": to_node.name,
                "to_input": to_socket.name,
            },
        }


    # =====================================================================
    # 4. material_node_group_create

    # =====================================================================


    def _handle_material_node_group_create(self, params: dict) -> dict:
        """Create a reusable shader node group."""
        name = require_param(params, "name", str)

        group = bpy.data.node_groups.new(name, "ShaderNodeTree")

        # The group always has a Group Input and Group Output node
        input_node = group.nodes.new("NodeGroupInput")
        input_node.location = (-400, 0)
        output_node = group.nodes.new("NodeGroupOutput")
        output_node.location = (400, 0)

        inputs_spec = params.get("inputs", [])
        outputs_spec = params.get("outputs", [])

        created_inputs = []
        created_outputs = []

        # Add input sockets
        for inp_def in inputs_spec:
            inp_name = inp_def.get("name", "Input")
            inp_type = inp_def.get("type", "FLOAT").upper()
            socket_type = _SOCKET_TYPE_MAP.get(inp_type, "NodeSocketFloat")

            group.interface.new_socket(name=inp_name, in_out="INPUT", socket_type=socket_type)
            created_inputs.append({"name": inp_name, "type": inp_type})

            # Set default value if provided
            default = inp_def.get("default")
            if default is not None:
                # Defaults are set on the Group Input node's outputs
                idx = len(created_inputs) - 1
                if idx < len(input_node.outputs) - 1:  # -1 for the virtual socket
                    sock = input_node.outputs[idx]
                    if hasattr(sock, "default_value"):
                        try:
                            if isinstance(default, (list, tuple)):
                                sock.default_value = default
                            else:
                                sock.default_value = float(default)
                        except (TypeError, ValueError):
                            pass

        # Add output sockets
        for out_def in outputs_spec:
            out_name = out_def.get("name", "Output")
            out_type = out_def.get("type", "FLOAT").upper()
            socket_type = _SOCKET_TYPE_MAP.get(out_type, "NodeSocketFloat")

            group.interface.new_socket(name=out_name, in_out="OUTPUT", socket_type=socket_type)
            created_outputs.append({"name": out_name, "type": out_type})

        return {
            "name": group.name,
            "inputs": created_inputs,
            "outputs": created_outputs,
        }


    # =====================================================================
    # 5. material_procedural_preset

    # =====================================================================

    def _handle_material_procedural_preset(self, params: dict) -> dict:
        """Create a complex procedural material from a preset."""
        name = require_param(params, "name", str)
        preset = require_param(params, "preset", str).upper()

        valid_presets = [
            "VEHICLE_PAINT", "BRUSHED_METAL", "CHROME", "RUBBER",
            "CARBON_FIBER", "ASPHALT", "TARMAC", "WORN_METAL",
            "GLASS", "PLASTIC_GLOSSY", "PLASTIC_MATTE", "CONCRETE",
            "FABRIC", "REFLECTIVE_TAPE", "LED_DISPLAY", "RUST",
            "GOLD", "COPPER", "SCRATCHED_PAINT", "SNOW", "WATER",
            "WOOD", "BRICK",
        ]
        if preset not in valid_presets:
            return {"error": f"Unknown preset '{preset}'. Valid: {valid_presets}"}

        color = params.get("color")
        wear_amount = float(params.get("wear_amount", 0.5))
        scale = float(params.get("scale", 1.0))

        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        tree = mat.node_tree

        # Clear default nodes
        for n in list(tree.nodes):
            tree.nodes.remove(n)

        # Dispatch to per-preset builder
        builder = _PRESET_BUILDERS.get(preset)
        if builder is None:
            return {"error": f"Preset builder not implemented for '{preset}'"}

        try:
            builder(tree, color, wear_amount, scale)
        except Exception as exc:
            return {"error": f"Failed to build preset '{preset}': {exc}"}

        return {
            "material": mat.name,
            "preset": preset,
            "node_count": len(tree.nodes),
            "link_count": len(tree.links),
        }


    # =====================================================================
    # 6. material_convert_to_pbr

    # =====================================================================

    def _handle_material_convert_to_pbr(self, params: dict) -> dict:
        """Convert a material to a clean Principled BSDF setup."""
        material_name = require_param(params, "material_name", str)
        target_format = require_param(params, "target_format", str).upper()

        valid_formats = ["GLTF", "MSFS", "UE5", "GENERIC"]
        if target_format not in valid_formats:
            return {"error": f"Unknown target_format '{target_format}'. Valid: {valid_formats}"}

        mat = get_material_or_error(material_name)

        if not mat.use_nodes or mat.node_tree is None:
            mat.use_nodes = True

        tree = mat.node_tree

        # ── Phase 1: extract values from existing graph ──────────────
        extracted = _extract_pbr_values(tree)

        # ── Phase 2: clear and rebuild ───────────────────────────────
        for node in list(tree.nodes):
            tree.nodes.remove(node)

        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (0, 0)
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        output.location = (300, 0)
        tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

        # Apply extracted values
        bsdf.inputs["Base Color"].default_value = extracted["base_color"]
        bsdf.inputs["Metallic"].default_value = extracted["metallic"]
        bsdf.inputs["Roughness"].default_value = extracted["roughness"]
        bsdf.inputs["Alpha"].default_value = extracted["alpha"]

        if extracted.get("emission_color"):
            bsdf.inputs["Emission Color"].default_value = extracted["emission_color"]
            bsdf.inputs["Emission Strength"].default_value = extracted.get("emission_strength", 1.0)

        if extracted.get("transmission"):
            bsdf.inputs["Transmission Weight"].default_value = extracted["transmission"]

        # ── Phase 3: format-specific adjustments ────────────────────
        texture_nodes_info = []

        if extracted.get("base_color_image"):
            tex = tree.nodes.new("ShaderNodeTexImage")
            tex.location = (-400, 300)
            tex.image = extracted["base_color_image"]
            tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            texture_nodes_info.append({"type": "base_color", "image": tex.image.name})

        if target_format == "GLTF":
            # glTF expects ORM packed texture; we just ensure clean Principled
            bsdf.inputs["Specular IOR Level"].default_value = 0.5
        elif target_format == "MSFS":
            # MSFS uses standard Principled but needs specific naming
            bsdf.inputs["Specular IOR Level"].default_value = 0.5
        elif target_format == "UE5":
            # UE5 uses a similar PBR model but spec = 0.5 default
            bsdf.inputs["Specular IOR Level"].default_value = 0.5

        return {
            "material": mat.name,
            "target_format": target_format,
            "extracted": {
                "base_color": list(extracted["base_color"]),
                "metallic": extracted["metallic"],
                "roughness": extracted["roughness"],
                "alpha": extracted["alpha"],
                "has_emission": bool(extracted.get("emission_color")),
                "has_transmission": bool(extracted.get("transmission")),
                "has_textures": len(texture_nodes_info) > 0,
            },
            "textures": texture_nodes_info,
            "node_count": len(tree.nodes),
        }


    # =====================================================================
    # 7. material_preview_render

    # =====================================================================

    def _handle_material_preview_render(self, params: dict) -> dict:
        """Render a material preview on a standard shape."""
        material_name = require_param(params, "material_name", str)
        mat = get_material_or_error(material_name)

        preview_shape = params.get("preview_shape", "SPHERE").upper()
        if preview_shape not in ("SPHERE", "CUBE", "PLANE", "CYLINDER"):
            return {"error": f"Invalid preview_shape '{preview_shape}'. Must be SPHERE, CUBE, PLANE, or CYLINDER."}

        resolution = int(params.get("resolution", 512))
        engine = params.get("engine", "EEVEE").upper()
        if engine not in ("EEVEE", "CYCLES"):
            return {"error": f"Invalid engine '{engine}'. Must be EEVEE or CYCLES."}

        safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in material_name)
        output_path = params.get("output_path", os.path.join(tempfile.gettempdir(), f"material_preview_{safe_name}.png"))

        # Remember current state
        original_scene = bpy.context.window.scene

        try:
            # ── Create temporary scene ──────────────────────────────
            preview_scene = bpy.data.scenes.new("__mat_preview_tmp__")
            bpy.context.window.scene = preview_scene

            # Set render settings
            preview_scene.render.resolution_x = resolution
            preview_scene.render.resolution_y = resolution
            preview_scene.render.resolution_percentage = 100
            preview_scene.render.image_settings.file_format = "PNG"
            preview_scene.render.filepath = output_path

            if engine == "EEVEE":
                preview_scene.render.engine = compat.get_eevee_engine_name()
            else:
                preview_scene.render.engine = "CYCLES"
                preview_scene.cycles.samples = 64
                preview_scene.cycles.use_denoising = True

            # World background
            if preview_scene.world is None:
                preview_scene.world = bpy.data.worlds.new("__preview_world__")
            preview_scene.world.use_nodes = True
            bg_node = preview_scene.world.node_tree.nodes.get("Background")
            if bg_node:
                bg_node.inputs["Color"].default_value = (0.15, 0.15, 0.15, 1.0)
                bg_node.inputs["Strength"].default_value = 0.5

            # ── Create preview object ───────────────────────────────
            if preview_shape == "SPHERE":
                bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=1.0, location=(0, 0, 0))
                bpy.ops.object.shade_smooth()
            elif preview_shape == "CUBE":
                bpy.ops.mesh.primitive_cube_add(size=1.6, location=(0, 0, 0))
            elif preview_shape == "PLANE":
                bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, 0))
            elif preview_shape == "CYLINDER":
                bpy.ops.mesh.primitive_cylinder_add(radius=0.8, depth=1.6, vertices=64, location=(0, 0, 0))
                bpy.ops.object.shade_smooth()

            preview_obj = bpy.context.active_object
            preview_obj.name = "__mat_preview_obj__"

            # Assign material
            preview_obj.data.materials.append(mat)

            # ── Create camera ───────────────────────────────────────
            cam_data = bpy.data.cameras.new("__preview_cam__")
            cam_obj = bpy.data.objects.new("__preview_cam__", cam_data)
            preview_scene.collection.objects.link(cam_obj)
            preview_scene.camera = cam_obj

            # Position camera at a nice angle
            cam_obj.location = (2.5, -2.5, 2.0)
            # Point at origin
            direction = cam_obj.location.copy()
            direction.negate()
            from mathutils import Vector
            rot_quat = direction.to_track_quat('-Z', 'Y')
            cam_obj.rotation_euler = rot_quat.to_euler()

            # ── Create lighting ─────────────────────────────────────
            # Key light
            key_data = bpy.data.lights.new("__preview_key__", "AREA")
            key_data.energy = 100
            key_data.size = 3.0
            key_obj = bpy.data.objects.new("__preview_key__", key_data)
            key_obj.location = (3.0, -2.0, 4.0)
            preview_scene.collection.objects.link(key_obj)

            # Fill light
            fill_data = bpy.data.lights.new("__preview_fill__", "AREA")
            fill_data.energy = 30
            fill_data.size = 2.0
            fill_obj = bpy.data.objects.new("__preview_fill__", fill_data)
            fill_obj.location = (-3.0, -1.0, 2.0)
            preview_scene.collection.objects.link(fill_obj)

            # ── Render ──────────────────────────────────────────────
            bpy.ops.render.render(write_still=True, scene=preview_scene.name)

            return {
                "material": mat.name,
                "preview_shape": preview_shape,
                "engine": engine,
                "resolution": resolution,
                "output_path": output_path,
            }

        except Exception as exc:
            return {"error": f"Preview render failed: {exc}"}

        finally:
            # ── Cleanup temporary scene ─────────────────────────────
            bpy.context.window.scene = original_scene

            # Remove temp scene and its objects
            if "__mat_preview_tmp__" in bpy.data.scenes:
                tmp_scene = bpy.data.scenes["__mat_preview_tmp__"]
                # Remove objects created in the temp scene
                for obj in list(tmp_scene.collection.objects):
                    data = obj.data
                    bpy.data.objects.remove(obj, do_unlink=True)
                    # Clean up associated data blocks
                    if data is not None:
                        if isinstance(data, bpy.types.Mesh):
                            bpy.data.meshes.remove(data)
                        elif isinstance(data, bpy.types.Camera):
                            bpy.data.cameras.remove(data)
                        elif isinstance(data, bpy.types.Light):
                            bpy.data.lights.remove(data)
                bpy.data.scenes.remove(tmp_scene)

            # Clean up temp world
            if "__preview_world__" in bpy.data.worlds:
                bpy.data.worlds.remove(bpy.data.worlds["__preview_world__"])


    # ========== Measurement & Validation Handlers ==========


    def _handle_measure_surface_area(self, params: dict) -> dict:
        """Calculate total surface area with optional per-material breakdown."""
        import bpy
        import bmesh
        from mathutils import Matrix

        from .utils import get_object_or_error
        from .validation import ValidationError, require_param

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
        import bpy
        import bmesh
        from mathutils import Vector

        from .utils import get_object_or_error
        from .validation import ValidationError, require_param

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
        import bpy
        import bmesh
        from mathutils import Vector
        from mathutils.bvhtree import BVHTree

        from .utils import get_object_or_error
        from .validation import ValidationError, require_param

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
        import bpy
        from mathutils import Vector

        from .utils import get_object_or_error
        from .validation import ValidationError, require_param

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
        import bpy
        from mathutils import Vector

        from .utils import get_object_or_error, ensure_object_selected
        from .validation import ValidationError, require_param, validate_enum

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
        import bpy
        import bmesh

        from .utils import get_object_or_error
        from .validation import ValidationError, require_param

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
        import bpy
        import bmesh
        from mathutils import Vector

        from .utils import get_object_or_error
        from .validation import ValidationError, require_param

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

                uv_island_count = 0
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


    # ========== Collection & System Handlers ==========


    def _handle_collection_create(self, params: dict) -> dict:
        """Create a new collection and link it to a parent collection."""
        name = require_param(params, "name", str)
        parent_name = params.get("parent")
        color_tag = params.get("color_tag", "NONE")

        # Validate color_tag if provided
        valid_tags = [
            "NONE",
            "COLOR_01", "COLOR_02", "COLOR_03", "COLOR_04",
            "COLOR_05", "COLOR_06", "COLOR_07", "COLOR_08",
        ]
        color_tag = validate_enum(color_tag, "color_tag", valid_tags)

        # Create the collection
        new_collection = bpy.data.collections.new(name)
        new_collection.color_tag = color_tag

        # Determine parent collection
        if parent_name:
            parent_collection = bpy.data.collections.get(parent_name)
            if parent_collection is None:
                # Check if it's the scene collection by name
                scene_col = bpy.context.scene.collection
                if scene_col.name == parent_name:
                    parent_collection = scene_col
                else:
                    # Clean up the orphan collection we just created
                    bpy.data.collections.remove(new_collection)
                    raise ValidationError(
                        f"Parent collection '{parent_name}' not found. "
                        f"Available: {[c.name for c in bpy.data.collections]} "
                        f"+ scene collection '{scene_col.name}'"
                    )
            parent_collection.children.link(new_collection)
            parent_path = parent_name
        else:
            # Link to the scene's root collection
            bpy.context.scene.collection.children.link(new_collection)
            parent_path = bpy.context.scene.collection.name

        # Build the full path
        full_path = f"{parent_path}/{new_collection.name}"

        return {
            "success": True,
            "name": new_collection.name,
            "parent": parent_path,
            "path": full_path,
            "color_tag": new_collection.color_tag,
        }

    def _handle_collection_list(self, params: dict) -> dict:
        """List all collections with hierarchy as a nested tree."""

        def _find_layer_collection(layer_col, name):
            """Recursively find a LayerCollection by collection name."""
            if layer_col.collection.name == name:
                return layer_col
            for child in layer_col.children:
                result = _find_layer_collection(child, name)
                if result is not None:
                    return result
            return None

        def _build_tree(collection, layer_collection_root):
            """Recursively build collection tree structure."""
            # Get layer collection for visibility info
            lc = _find_layer_collection(layer_collection_root, collection.name)

            objects = [obj.name for obj in collection.objects]
            children = []
            for child in collection.children:
                children.append(_build_tree(child, layer_collection_root))

            result = {
                "name": collection.name,
                "objects": objects,
                "children": children,
                "color_tag": getattr(collection, "color_tag", "NONE"),
            }

            if lc is not None:
                result["visible"] = not lc.hide_viewport
                result["excluded"] = lc.exclude
                result["render_visible"] = not collection.hide_render
                result["selectable"] = not collection.hide_select
            else:
                result["visible"] = True
                result["excluded"] = False
                result["render_visible"] = not collection.hide_render
                result["selectable"] = not collection.hide_select

            return result

        scene = bpy.context.scene
        root = scene.collection
        layer_root = bpy.context.view_layer.layer_collection

        # Build tree from root scene collection
        tree = {
            "name": root.name,
            "objects": [obj.name for obj in root.objects],
            "children": [
                _build_tree(child, layer_root)
                for child in root.children
            ],
            "visible": True,
            "excluded": False,
            "render_visible": True,
            "selectable": True,
        }

        # Count totals
        total_collections = len(bpy.data.collections)

        return {
            "success": True,
            "hierarchy": tree,
            "total_collections": total_collections,
        }

    def _handle_collection_move(self, params: dict) -> dict:
        """Move objects between collections."""
        object_names = require_param(params, "object_names", list)
        target_name = require_param(params, "target_collection", str)
        remove_from_current = params.get("remove_from_current", True)

        # Find the target collection
        target_collection = bpy.data.collections.get(target_name)
        if target_collection is None:
            # Check if it's the scene collection
            scene_col = bpy.context.scene.collection
            if scene_col.name == target_name:
                target_collection = scene_col
            else:
                raise ValidationError(
                    f"Target collection '{target_name}' not found. "
                    f"Available: {[c.name for c in bpy.data.collections]} "
                    f"+ scene collection '{scene_col.name}'"
                )

        moved = []
        errors = []

        for obj_name in object_names:
            obj = bpy.data.objects.get(obj_name)
            if obj is None:
                errors.append(f"Object '{obj_name}' not found")
                continue

            # Remove from current collections if requested
            if remove_from_current:
                # Collect all collections this object is in
                current_collections = [
                    c for c in bpy.data.collections if obj.name in c.objects
                ]
                # Also check scene collection
                scene_col = bpy.context.scene.collection
                if obj.name in scene_col.objects:
                    current_collections.append(scene_col)

                for col in current_collections:
                    col.objects.unlink(obj)

            # Link to target collection (skip if already linked)
            if obj.name not in target_collection.objects:
                target_collection.objects.link(obj)

            moved.append(obj_name)

        result = {
            "success": len(errors) == 0,
            "moved_count": len(moved),
            "objects": moved,
            "target_collection": target_name,
        }
        if errors:
            result["errors"] = errors

        return result

    def _handle_collection_visibility(self, params: dict) -> dict:
        """Toggle collection visibility, renderability, and selectability."""
        collection_name = require_param(params, "collection_name", str)

        # Find the bpy.data collection
        collection = bpy.data.collections.get(collection_name)
        if collection is None:
            raise ValidationError(
                f"Collection '{collection_name}' not found. "
                f"Available: {[c.name for c in bpy.data.collections]}"
            )

        # Find the corresponding LayerCollection by walking the tree
        def _find_layer_collection(layer_col, name):
            """Recursively find a LayerCollection by collection name."""
            if layer_col.collection.name == name:
                return layer_col
            for child in layer_col.children:
                result = _find_layer_collection(child, name)
                if result is not None:
                    return result
            return None

        layer_root = bpy.context.view_layer.layer_collection
        layer_col = _find_layer_collection(layer_root, collection_name)

        if layer_col is None:
            raise ValidationError(
                f"Collection '{collection_name}' not found in the current view layer. "
                f"It may not be linked to the active scene."
            )

        # Apply requested changes
        changes = {}

        if "visible" in params:
            visible = bool(params["visible"])
            layer_col.hide_viewport = not visible
            changes["visible"] = visible

        if "renderable" in params:
            renderable = bool(params["renderable"])
            collection.hide_render = not renderable
            changes["renderable"] = renderable

        if "selectable" in params:
            selectable = bool(params["selectable"])
            collection.hide_select = not selectable
            changes["selectable"] = selectable

        # Return current state after changes
        return {
            "success": True,
            "collection": collection_name,
            "changes_applied": changes,
            "current_state": {
                "visible": not layer_col.hide_viewport,
                "excluded": layer_col.exclude,
                "renderable": not collection.hide_render,
                "selectable": not collection.hide_select,
            },
        }


    # ========== System Handlers ==========

    def _handle_undo(self, params: dict) -> dict:
        """Undo the last operation."""
        try:
            bpy.ops.ed.undo()
            # Try to get the current undo step name
            undo_name = None
            try:
                undo_name = bpy.context.window_manager.undo_steps_data[-1].name
            except (AttributeError, IndexError):
                pass

            result = {"success": True}
            if undo_name:
                result["operation"] = undo_name
            return result
        except RuntimeError as e:
            return {"success": False, "error": f"Undo failed: {e}"}

    def _handle_redo(self, params: dict) -> dict:
        """Redo the last undone operation."""
        try:
            bpy.ops.ed.redo()
            return {"success": True}
        except RuntimeError as e:
            return {"success": False, "error": f"Redo failed: {e}"}

    def _handle_save(self, params: dict) -> dict:
        """Save the current file."""
        compress = params.get("compress", False)

        # Check if the file has ever been saved
        filepath = bpy.data.filepath
        if not filepath:
            return {
                "success": False,
                "error": "File has never been saved. Use save_as with a filepath instead.",
            }

        bpy.ops.wm.save_mainfile(compress=bool(compress))

        # Get file size
        try:
            filesize = os.path.getsize(filepath)
        except OSError:
            filesize = None

        result = {
            "success": True,
            "filepath": filepath,
        }
        if filesize is not None:
            result["filesize"] = filesize
            result["filesize_mb"] = round(filesize / (1024 * 1024), 2)

        return result

    def _handle_save_as(self, params: dict) -> dict:
        """Save to a new file path."""
        filepath = require_param(params, "filepath", str)
        compress = params.get("compress", False)
        copy = params.get("copy", False)

        # Ensure filepath ends with .blend
        if not filepath.lower().endswith(".blend"):
            filepath += ".blend"

        # Create parent directories if they don't exist
        parent_dir = os.path.dirname(filepath)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        bpy.ops.wm.save_as_mainfile(
            filepath=filepath,
            compress=bool(compress),
            copy=bool(copy),
        )

        # Get file size
        try:
            filesize = os.path.getsize(filepath)
        except OSError:
            filesize = None

        result = {
            "success": True,
            "filepath": filepath,
            "copy": copy,
        }
        if filesize is not None:
            result["filesize"] = filesize
            result["filesize_mb"] = round(filesize / (1024 * 1024), 2)

        return result


    # ========== Baking Handlers ==========


    def _handle_bake_pbr_batch(self, params: dict) -> dict:
        """Bake all requested PBR channels in one call."""
        import bpy
        from .validation import require_param

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
        self._bake_ensure_cycles()
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
        import bpy
        from .validation import require_param

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
        self._bake_ensure_cycles()
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
        import bpy
        from .validation import require_param

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
        self._bake_ensure_cycles()

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
        import bpy
        import bmesh
        import numpy as np
        from .validation import require_param

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
        self._bake_ensure_cycles()
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
        import bpy
        import bmesh
        import numpy as np
        from mathutils import Vector
        from .validation import require_param

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
        import bpy
        import random
        from .validation import require_param

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
        self._bake_ensure_cycles()
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


    def _handle_geonode_create_group(self, params: dict) -> dict:
        """Create a new GeometryNodeTree with typed sockets."""
        import bpy

        from .validation import require_param

        name = require_param(params, "name", str)
        extra_inputs = params.get("inputs", [])
        extra_outputs = params.get("outputs", [])

        # Create the node group
        group = bpy.data.node_groups.new(name, 'GeometryNodeTree')

        # Blender 4.x: default Geometry in/out are created automatically
        # when we create a GeometryNodeTree.  Verify they exist, or add them.
        existing_input_names = set()
        existing_output_names = set()
        for item in group.interface.items_tree:
            if item.item_type != 'SOCKET':
                continue
            if item.in_out == 'INPUT':
                existing_input_names.add(item.name)
            else:
                existing_output_names.add(item.name)

        if "Geometry" not in existing_input_names:
            group.interface.new_socket(
                name="Geometry", in_out='INPUT',
                socket_type='NodeSocketGeometry',
            )
        if "Geometry" not in existing_output_names:
            group.interface.new_socket(
                name="Geometry", in_out='OUTPUT',
                socket_type='NodeSocketGeometry',
            )

        # Add Group Input and Group Output nodes if not present
        has_input_node = any(n.type == 'GROUP_INPUT' for n in group.nodes)
        has_output_node = any(n.type == 'GROUP_OUTPUT' for n in group.nodes)
        if not has_input_node:
            _new_node(group, 'NodeGroupInput', location=(-300, 0))
        if not has_output_node:
            _new_node(group, 'NodeGroupOutput', location=(300, 0))

        # Wire default Geometry through
        input_node = next(n for n in group.nodes if n.type == 'GROUP_INPUT')
        output_node = next(n for n in group.nodes if n.type == 'GROUP_OUTPUT')
        # Connect Geometry pass-through if no links yet
        if not group.links:
            geo_out = None
            geo_in = None
            for out in input_node.outputs:
                if out.bl_idname == 'NodeSocketGeometry' or out.name == 'Geometry':
                    geo_out = out
                    break
            for inp in output_node.inputs:
                if inp.bl_idname == 'NodeSocketGeometry' or inp.name == 'Geometry':
                    geo_in = inp
                    break
            if geo_out and geo_in:
                _link(group, geo_out, geo_in)

        # Add extra input sockets
        for spec in extra_inputs:
            sock_name = spec.get("name", "Value")
            sock_type = spec.get("type", "FLOAT").upper()
            bl_type = _SOCKET_TYPE_MAP.get(sock_type)
            if bl_type is None:
                continue
            sock = group.interface.new_socket(
                name=sock_name, in_out='INPUT', socket_type=bl_type,
            )
            # Set default value if provided
            default = spec.get("default")
            if default is not None and hasattr(sock, "default_value"):
                try:
                    if sock_type == "VECTOR" and isinstance(default, (list, tuple)):
                        sock.default_value = tuple(float(v) for v in default[:3])
                    elif sock_type == "BOOLEAN":
                        sock.default_value = bool(default)
                    elif sock_type == "INT":
                        sock.default_value = int(default)
                    elif sock_type == "FLOAT":
                        sock.default_value = float(default)
                    elif sock_type == "STRING":
                        sock.default_value = str(default)
                except (TypeError, ValueError):
                    pass  # skip bad defaults silently

        # Add extra output sockets
        for spec in extra_outputs:
            sock_name = spec.get("name", "Value")
            sock_type = spec.get("type", "FLOAT").upper()
            bl_type = _SOCKET_TYPE_MAP.get(sock_type)
            if bl_type is None:
                continue
            group.interface.new_socket(
                name=sock_name, in_out='OUTPUT', socket_type=bl_type,
            )

        inputs_info, outputs_info = _build_socket_info(group)
        return {
            "success": True,
            "node_group": group.name,
            "inputs": inputs_info,
            "outputs": outputs_info,
        }

    # ── 2. Apply ─────────────────────────────────────────────────────

    def _handle_geonode_apply(self, params: dict) -> dict:
        """Apply a GN group as a modifier and set input values."""
        import bpy

        from .utils import get_object_or_error
        from .validation import require_param

        object_name = require_param(params, "object_name", str)
        group_name = require_param(params, "node_group", str)
        input_values = params.get("inputs", {})

        obj = get_object_or_error(object_name)
        group = bpy.data.node_groups.get(group_name)
        if group is None:
            return {"error": f"Node group not found: {group_name}"}
        if group.bl_idname != 'GeometryNodeTree':
            return {"error": f"'{group_name}' is not a GeometryNodeTree"}

        # Add modifier
        mod_name = group_name
        modifier = obj.modifiers.new(name=mod_name, type='NODES')
        modifier.node_group = group

        # Set input values
        if input_values and isinstance(input_values, dict):
            # Build a name→(identifier, bl_socket_idname) map from the interface
            socket_map: dict[str, tuple[str, str]] = {}
            for item in group.interface.items_tree:
                if item.item_type == 'SOCKET' and item.in_out == 'INPUT':
                    socket_map[item.name] = (item.identifier, item.bl_socket_idname)

            for inp_name, inp_value in input_values.items():
                if inp_name not in socket_map:
                    continue
                identifier, bl_type = socket_map[inp_name]
                _set_modifier_input(modifier, identifier, inp_value, bl_type)

        # Read back current state
        result_inputs = {}
        for item in group.interface.items_tree:
            if item.item_type == 'SOCKET' and item.in_out == 'INPUT':
                result_inputs[item.name] = _read_modifier_input(modifier, item.identifier)

        return {
            "success": True,
            "object": object_name,
            "modifier": modifier.name,
            "node_group": group.name,
            "inputs": result_inputs,
        }

    # ── 3. Scatter Instances ─────────────────────────────────────────

    def _handle_geonode_scatter_instances(self, params: dict) -> dict:
        """Build a full scatter-instances GN setup in one call."""
        import bpy

        from .utils import get_object_or_error
        from .validation import require_param

        target_name = require_param(params, "target_object", str)
        instance_name = require_param(params, "instance_object", str)
        density = float(params.get("density", 10.0))
        seed = int(params.get("seed", 0))
        min_distance = float(params.get("min_distance", 0.0))
        scale_min = float(params.get("scale_min", 1.0))
        scale_max = float(params.get("scale_max", 1.0))
        rotation_random = params.get("rotation_random", [0, 0, 0])
        align_to_normal = params.get("align_to_normal", True)

        target_obj = get_object_or_error(target_name)
        instance_obj = get_object_or_error(instance_name)

        # -- Build node tree --
        tree_name = f"Scatter_{instance_name}_on_{target_name}"
        tree = bpy.data.node_groups.new(tree_name, 'GeometryNodeTree')

        # Ensure Geometry in/out sockets exist
        has_geo_in = False
        has_geo_out = False
        for item in tree.interface.items_tree:
            if item.item_type == 'SOCKET':
                if item.in_out == 'INPUT' and item.name == 'Geometry':
                    has_geo_in = True
                if item.in_out == 'OUTPUT' and item.name == 'Geometry':
                    has_geo_out = True
        if not has_geo_in:
            tree.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        if not has_geo_out:
            tree.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

        # Nodes
        n_input = _new_node(tree, 'NodeGroupInput', location=(-800, 0))
        n_output = _new_node(tree, 'NodeGroupOutput', location=(600, 0))

        # Distribute Points on Faces
        n_dist = _new_node(tree, 'GeometryNodeDistributePointsOnFaces',
                           label='Distribute', location=(-400, 0))
        if min_distance > 0:
            # Poisson Disk
            n_dist.distribute_method = 'POISSON'
            # Poisson uses "Distance Min" input (index 2) and "Density Max" (index 4)
            n_dist.inputs['Distance Min'].default_value = min_distance
            n_dist.inputs['Density Max'].default_value = density
        else:
            n_dist.distribute_method = 'RANDOM'
            n_dist.inputs['Density'].default_value = density
        n_dist.inputs['Seed'].default_value = seed

        # Instance on Points
        n_iop = _new_node(tree, 'GeometryNodeInstanceOnPoints',
                          label='Instance on Points', location=(0, 0))

        # Object Info (to get instance geometry)
        n_obj = _new_node(tree, 'GeometryNodeObjectInfo',
                          label='Instance Object', location=(-400, -300))
        n_obj.inputs['Object'].default_value = instance_obj
        n_obj.transform_space = 'RELATIVE'

        # -- Random scale --
        if scale_min != scale_max:
            n_rand_scale = _new_node(tree, 'FunctionNodeRandomValue',
                                     label='Random Scale', location=(-200, -200))
            # Set data type to FLOAT_VECTOR for uniform xyz
            n_rand_scale.data_type = 'FLOAT'
            n_rand_scale.inputs[2].default_value = scale_min  # Min
            n_rand_scale.inputs[3].default_value = scale_max  # Max

            # Combine XYZ to turn single float into vector scale
            n_combine = _new_node(tree, 'ShaderNodeCombineXYZ',
                                  label='Scale Vec', location=(-50, -200))
            _link(tree, n_rand_scale.outputs['Value'], n_combine.inputs['X'])
            _link(tree, n_rand_scale.outputs['Value'], n_combine.inputs['Y'])
            _link(tree, n_rand_scale.outputs['Value'], n_combine.inputs['Z'])
            _link(tree, n_combine.outputs['Vector'], n_iop.inputs['Scale'])
        else:
            # Uniform fixed scale — no node needed, just set default
            n_iop.inputs['Scale'].default_value = (scale_min, scale_min, scale_min)

        # -- Rotation --
        rot_degs = [float(r) for r in rotation_random[:3]] if rotation_random else [0, 0, 0]
        has_random_rot = any(abs(r) > 0.001 for r in rot_degs)

        if align_to_normal:
            # Connect Rotation from Distribute → Instance on Points
            _link(tree, n_dist.outputs['Rotation'], n_iop.inputs['Rotation'])

            if has_random_rot:
                # Add random rotation on top via Rotate Euler node
                n_rand_rot = _new_node(tree, 'FunctionNodeRandomValue',
                                       label='Random Rot', location=(-200, -400))
                n_rand_rot.data_type = 'FLOAT_VECTOR'
                rot_rads = [math.radians(r) for r in rot_degs]
                n_rand_rot.inputs[0].default_value = tuple(-r for r in rot_rads)  # Min
                n_rand_rot.inputs[1].default_value = tuple(rot_rads)  # Max

                n_rotate = _new_node(tree, 'FunctionNodeRotateEuler',
                                     label='Add Random Rot', location=(-50, -400))
                n_rotate.type = 'EULER'
                _link(tree, n_dist.outputs['Rotation'], n_rotate.inputs['Rotation'])
                _link(tree, n_rand_rot.outputs['Value'], n_rotate.inputs['Rotate By'])

                # Re-link rotation
                # Remove old link from dist rotation to IOP
                for lnk in list(tree.links):
                    if lnk.to_socket == n_iop.inputs['Rotation'] and lnk.from_node == n_dist:
                        tree.links.remove(lnk)
                _link(tree, n_rotate.outputs['Rotation'], n_iop.inputs['Rotation'])

        elif has_random_rot:
            n_rand_rot = _new_node(tree, 'FunctionNodeRandomValue',
                                   label='Random Rot', location=(-200, -400))
            n_rand_rot.data_type = 'FLOAT_VECTOR'
            rot_rads = [math.radians(r) for r in rot_degs]
            n_rand_rot.inputs[0].default_value = tuple(-r for r in rot_rads)
            n_rand_rot.inputs[1].default_value = tuple(rot_rads)

            # Euler to Rotation
            n_euler = _new_node(tree, 'FunctionNodeEulerToRotation',
                                label='To Rotation', location=(-50, -400))
            _link(tree, n_rand_rot.outputs['Value'], n_euler.inputs['Euler'])
            _link(tree, n_euler.outputs['Rotation'], n_iop.inputs['Rotation'])

        # -- Core wiring --
        _link(tree, n_input.outputs['Geometry'], n_dist.inputs['Mesh'])
        _link(tree, n_dist.outputs['Points'], n_iop.inputs['Points'])
        _link(tree, n_obj.outputs['Geometry'], n_iop.inputs['Instance'])
        _link(tree, n_iop.outputs['Instances'], n_output.inputs['Geometry'])

        # -- Apply modifier --
        modifier = target_obj.modifiers.new(name=tree_name, type='NODES')
        modifier.node_group = tree

        return {
            "success": True,
            "node_group": tree.name,
            "modifier": modifier.name,
            "target": target_name,
            "instance": instance_name,
            "density": density,
            "distribute_method": "POISSON" if min_distance > 0 else "RANDOM",
        }

    # ── 4. Array / Grid ──────────────────────────────────────────────

    def _handle_geonode_array_grid(self, params: dict) -> dict:
        """Build a parametric array pattern via Geometry Nodes."""
        import bpy

        from .utils import get_object_or_error
        from .validation import require_param, validate_enum

        object_name = require_param(params, "object_name", str)
        instance_name = require_param(params, "instance_object", str)
        grid_type = validate_enum(
            require_param(params, "grid_type", str),
            "grid_type",
            ["LINEAR", "GRID_2D", "RADIAL", "HEXAGONAL"],
        )

        count_x = int(params.get("count_x", 5))
        count_y = int(params.get("count_y", 5))
        spacing_x = float(params.get("spacing_x", 1.0))
        spacing_y = float(params.get("spacing_y", 1.0))
        radial_count = int(params.get("radial_count", 8))
        radial_radius = float(params.get("radial_radius", 1.0))

        obj = get_object_or_error(object_name)
        instance_obj = get_object_or_error(instance_name)

        tree_name = f"Array_{grid_type}_{instance_name}"
        tree = bpy.data.node_groups.new(tree_name, 'GeometryNodeTree')

        # Ensure Geometry output socket
        has_geo_out = False
        for item in tree.interface.items_tree:
            if item.item_type == 'SOCKET' and item.in_out == 'OUTPUT' and item.name == 'Geometry':
                has_geo_out = True
        if not has_geo_out:
            tree.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        # Remove default Geometry input if present (we generate our own points)
        for item in list(tree.interface.items_tree):
            if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == 'Geometry':
                tree.interface.remove(item)

        n_output = _new_node(tree, 'NodeGroupOutput', location=(600, 0))

        # Object Info for instance
        n_obj = _new_node(tree, 'GeometryNodeObjectInfo',
                          label='Instance', location=(-200, -300))
        n_obj.inputs['Object'].default_value = instance_obj
        n_obj.transform_space = 'RELATIVE'

        # Instance on Points
        n_iop = _new_node(tree, 'GeometryNodeInstanceOnPoints',
                          label='Instance on Points', location=(300, 0))

        if grid_type == "LINEAR":
            # Mesh Line node
            n_line = _new_node(tree, 'GeometryNodeMeshLine',
                               label='Line', location=(-200, 0))
            n_line.mode = 'OFFSET'
            n_line.inputs['Count'].default_value = count_x
            n_line.inputs['Offset'].default_value = (spacing_x, 0.0, 0.0)
            _link(tree, n_line.outputs['Mesh'], n_iop.inputs['Points'])

        elif grid_type == "GRID_2D":
            # Grid node (Mesh Grid)
            n_grid = _new_node(tree, 'GeometryNodeMeshGrid',
                               label='Grid', location=(-200, 0))
            n_grid.inputs['Vertices X'].default_value = count_x
            n_grid.inputs['Vertices Y'].default_value = count_y
            n_grid.inputs['Size X'].default_value = spacing_x * (count_x - 1)
            n_grid.inputs['Size Y'].default_value = spacing_y * (count_y - 1)
            _link(tree, n_grid.outputs['Mesh'], n_iop.inputs['Points'])

        elif grid_type == "RADIAL":
            # Mesh Circle (vertices only, no fill)
            n_circle = _new_node(tree, 'GeometryNodeMeshCircle',
                                 label='Circle', location=(-200, 0))
            n_circle.fill_type = 'NONE'
            n_circle.inputs['Vertices'].default_value = radial_count
            n_circle.inputs['Radius'].default_value = radial_radius
            _link(tree, n_circle.outputs['Mesh'], n_iop.inputs['Points'])

        elif grid_type == "HEXAGONAL":
            # Build hex grid via a regular grid + Set Position offset on odd rows
            n_grid = _new_node(tree, 'GeometryNodeMeshGrid',
                               label='Hex Grid', location=(-600, 0))
            n_grid.inputs['Vertices X'].default_value = count_x
            n_grid.inputs['Vertices Y'].default_value = count_y
            n_grid.inputs['Size X'].default_value = spacing_x * (count_x - 1)
            n_grid.inputs['Size Y'].default_value = spacing_y * (count_y - 1)

            # Index node
            n_index = _new_node(tree, 'GeometryNodeInputIndex',
                                label='Index', location=(-600, -200))

            # Math: row = index / count_x (integer division via floor)
            n_div = _new_node(tree, 'ShaderNodeMath',
                              label='Div', location=(-400, -200))
            n_div.operation = 'DIVIDE'
            _link(tree, n_index.outputs['Index'], n_div.inputs[0])
            n_div.inputs[1].default_value = float(count_x)

            n_floor = _new_node(tree, 'ShaderNodeMath',
                                label='Floor', location=(-250, -200))
            n_floor.operation = 'FLOOR'
            _link(tree, n_div.outputs['Value'], n_floor.inputs[0])

            # Modulo 2 to detect odd rows
            n_mod = _new_node(tree, 'ShaderNodeMath',
                              label='Mod2', location=(-100, -200))
            n_mod.operation = 'MODULO'
            _link(tree, n_floor.outputs['Value'], n_mod.inputs[0])
            n_mod.inputs[1].default_value = 2.0

            # Multiply by half spacing for offset
            n_mul = _new_node(tree, 'ShaderNodeMath',
                              label='HalfOffset', location=(50, -200))
            n_mul.operation = 'MULTIPLY'
            _link(tree, n_mod.outputs['Value'], n_mul.inputs[0])
            n_mul.inputs[1].default_value = spacing_x * 0.5

            # Combine XYZ (only X gets offset)
            n_combine = _new_node(tree, 'ShaderNodeCombineXYZ',
                                  label='Offset Vec', location=(200, -200))
            _link(tree, n_mul.outputs['Value'], n_combine.inputs['X'])

            # Set Position (offset)
            n_setpos = _new_node(tree, 'GeometryNodeSetPosition',
                                 label='Hex Offset', location=(-200, 0))
            _link(tree, n_grid.outputs['Mesh'], n_setpos.inputs['Geometry'])
            _link(tree, n_combine.outputs['Vector'], n_setpos.inputs['Offset'])

            _link(tree, n_setpos.outputs['Geometry'], n_iop.inputs['Points'])

        # Wire instance and output
        _link(tree, n_obj.outputs['Geometry'], n_iop.inputs['Instance'])
        _link(tree, n_iop.outputs['Instances'], n_output.inputs['Geometry'])

        # Apply modifier
        modifier = obj.modifiers.new(name=tree_name, type='NODES')
        modifier.node_group = tree

        return {
            "success": True,
            "node_group": tree.name,
            "modifier": modifier.name,
            "object": object_name,
            "grid_type": grid_type,
        }

    # ── 5. Deform Along Curve ────────────────────────────────────────

    def _handle_geonode_deform_curve(self, params: dict) -> dict:
        """Deform a mesh along a curve using Geometry Nodes."""
        import bpy

        from .utils import get_object_or_error
        from .validation import require_param

        object_name = require_param(params, "object_name", str)
        curve_name = require_param(params, "curve_name", str)
        stretch = params.get("stretch", True)

        mesh_obj = get_object_or_error(object_name)
        curve_obj = get_object_or_error(curve_name)
        if curve_obj.type != 'CURVE':
            return {"error": f"'{curve_name}' is not a curve object (type: {curve_obj.type})"}

        tree_name = f"DeformCurve_{object_name}"
        tree = bpy.data.node_groups.new(tree_name, 'GeometryNodeTree')

        # Sockets
        has_geo_in = False
        has_geo_out = False
        for item in tree.interface.items_tree:
            if item.item_type == 'SOCKET':
                if item.in_out == 'INPUT' and item.name == 'Geometry':
                    has_geo_in = True
                if item.in_out == 'OUTPUT' and item.name == 'Geometry':
                    has_geo_out = True
        if not has_geo_in:
            tree.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        if not has_geo_out:
            tree.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

        n_input = _new_node(tree, 'NodeGroupInput', location=(-600, 0))
        n_output = _new_node(tree, 'NodeGroupOutput', location=(600, 0))

        # Object Info to get curve geometry
        n_curve_info = _new_node(tree, 'GeometryNodeObjectInfo',
                                 label='Curve Object', location=(-400, -200))
        n_curve_info.inputs['Object'].default_value = curve_obj
        n_curve_info.transform_space = 'RELATIVE'

        # Deform Curves on Surface is for curves-on-mesh; for mesh-along-curve
        # we use the Curve Deform approach via Set Position + Sample Curve.
        #
        # Strategy: Use "Deform on Curve" approach:
        # 1. Get mesh bounding box to find extent along deform axis (X)
        # 2. Normalize vertex X to 0..1 (factor along curve)
        # 3. Sample Curve at that factor to get position + tangent
        # 4. Set position from sampled curve point

        # Bounding Box
        n_bbox = _new_node(tree, 'GeometryNodeBoundBox',
                           label='BBox', location=(-400, 200))
        _link(tree, n_input.outputs['Geometry'], n_bbox.inputs['Geometry'])

        # Separate XYZ of Min and Max
        n_sep_min = _new_node(tree, 'ShaderNodeSeparateXYZ',
                              label='Sep Min', location=(-200, 300))
        _link(tree, n_bbox.outputs['Min'], n_sep_min.inputs['Vector'])

        n_sep_max = _new_node(tree, 'ShaderNodeSeparateXYZ',
                              label='Sep Max', location=(-200, 200))
        _link(tree, n_bbox.outputs['Max'], n_sep_max.inputs['Vector'])

        # Extent = max_x - min_x
        n_extent = _new_node(tree, 'ShaderNodeMath',
                             label='Extent', location=(0, 250))
        n_extent.operation = 'SUBTRACT'
        _link(tree, n_sep_max.outputs['X'], n_extent.inputs[0])
        _link(tree, n_sep_min.outputs['X'], n_extent.inputs[1])

        # Position node (vertex position)
        n_pos = _new_node(tree, 'GeometryNodeInputPosition',
                          label='Position', location=(-400, 0))

        # Separate XYZ of position
        n_sep_pos = _new_node(tree, 'ShaderNodeSeparateXYZ',
                              label='Sep Pos', location=(-200, 0))
        _link(tree, n_pos.outputs['Position'], n_sep_pos.inputs['Vector'])

        # Factor = (pos_x - min_x) / extent
        n_sub = _new_node(tree, 'ShaderNodeMath',
                          label='Sub Min', location=(0, 50))
        n_sub.operation = 'SUBTRACT'
        _link(tree, n_sep_pos.outputs['X'], n_sub.inputs[0])
        _link(tree, n_sep_min.outputs['X'], n_sub.inputs[1])

        n_factor = _new_node(tree, 'ShaderNodeMath',
                             label='Factor', location=(0, -50))
        n_factor.operation = 'DIVIDE'
        n_factor.use_clamp = not stretch
        _link(tree, n_sub.outputs['Value'], n_factor.inputs[0])
        _link(tree, n_extent.outputs['Value'], n_factor.inputs[1])

        # Sample Curve
        n_sample = _new_node(tree, 'GeometryNodeSampleCurve',
                             label='Sample Curve', location=(200, -100))
        n_sample.mode = 'FACTOR'
        n_sample.data_type = 'FLOAT'
        _link(tree, n_curve_info.outputs['Geometry'], n_sample.inputs['Curves'])
        _link(tree, n_factor.outputs['Value'], n_sample.inputs['Factor'])

        # Use Y/Z from original position for profile offset:
        # final_pos = sampled_position + tangent_y_offset + tangent_z_offset
        # Simplified: offset the sampled position by the local Y and Z of the vertex

        # Get the Normal and Tangent from Sample Curve to build local frame
        # For simplicity, use Set Position with sampled position directly,
        # adding Y/Z offsets perpendicular to curve tangent.
        # Blender's Sample Curve gives Position, Tangent, Normal.

        # Cross product of tangent and (0,0,1) → right vector; or use Normal output
        # The Sample Curve node outputs: Position, Tangent, Normal

        # Combine local Y/Z offset with curve frame:
        # offset = normal * local_y + cross(tangent, normal) * local_z
        n_scale_y = _new_node(tree, 'ShaderNodeVectorMath',
                              label='Scale Normal', location=(200, -300))
        n_scale_y.operation = 'SCALE'
        _link(tree, n_sample.outputs['Normal'], n_scale_y.inputs[0])
        _link(tree, n_sep_pos.outputs['Y'], n_scale_y.inputs['Scale'])

        # Bitangent: cross(tangent, normal)
        n_cross = _new_node(tree, 'ShaderNodeVectorMath',
                            label='Bitangent', location=(200, -500))
        n_cross.operation = 'CROSS_PRODUCT'
        _link(tree, n_sample.outputs['Tangent'], n_cross.inputs[0])
        _link(tree, n_sample.outputs['Normal'], n_cross.inputs[1])

        n_scale_z = _new_node(tree, 'ShaderNodeVectorMath',
                              label='Scale Bitangent', location=(350, -500))
        n_scale_z.operation = 'SCALE'
        _link(tree, n_cross.outputs['Vector'], n_scale_z.inputs[0])
        _link(tree, n_sep_pos.outputs['Z'], n_scale_z.inputs['Scale'])

        # Add sampled pos + y_offset + z_offset
        n_add1 = _new_node(tree, 'ShaderNodeVectorMath',
                           label='Add Y', location=(400, -100))
        n_add1.operation = 'ADD'
        _link(tree, n_sample.outputs['Position'], n_add1.inputs[0])
        _link(tree, n_scale_y.outputs['Vector'], n_add1.inputs[1])

        n_add2 = _new_node(tree, 'ShaderNodeVectorMath',
                           label='Add Z', location=(400, -250))
        n_add2.operation = 'ADD'
        _link(tree, n_add1.outputs['Vector'], n_add2.inputs[0])
        _link(tree, n_scale_z.outputs['Vector'], n_add2.inputs[1])

        # Set Position
        n_setpos = _new_node(tree, 'GeometryNodeSetPosition',
                             label='Set Position', location=(500, 0))
        _link(tree, n_input.outputs['Geometry'], n_setpos.inputs['Geometry'])
        _link(tree, n_add2.outputs['Vector'], n_setpos.inputs['Position'])

        _link(tree, n_setpos.outputs['Geometry'], n_output.inputs['Geometry'])

        # Apply modifier
        modifier = mesh_obj.modifiers.new(name=tree_name, type='NODES')
        modifier.node_group = tree

        return {
            "success": True,
            "node_group": tree.name,
            "modifier": modifier.name,
            "object": object_name,
            "curve": curve_name,
            "stretch": stretch,
        }

    # ── 6. Extrude Profile Along Curve ───────────────────────────────

    def _handle_geonode_extrude_profile(self, params: dict) -> dict:
        """Extrude a profile along a curve via Curve to Mesh."""
        import bpy

        from .utils import get_object_or_error
        from .validation import require_param

        profile_name = require_param(params, "profile_object", str)
        curve_name = require_param(params, "curve_name", str)
        result_name = params.get("name", "ExtrudedProfile")
        fill_caps = params.get("fill_caps", True)
        resolution = int(params.get("resolution", 12))

        profile_obj = get_object_or_error(profile_name)
        curve_obj = get_object_or_error(curve_name)

        if curve_obj.type != 'CURVE':
            return {"error": f"'{curve_name}' is not a curve object (type: {curve_obj.type})"}

        # Set curve resolution
        for spline in curve_obj.data.splines:
            spline.resolution_u = resolution
        curve_obj.data.resolution_u = resolution

        # Build GN tree
        tree_name = f"Extrude_{result_name}"
        tree = bpy.data.node_groups.new(tree_name, 'GeometryNodeTree')

        # Only need Geometry output
        has_geo_out = False
        for item in tree.interface.items_tree:
            if item.item_type == 'SOCKET' and item.in_out == 'OUTPUT' and item.name == 'Geometry':
                has_geo_out = True
        if not has_geo_out:
            tree.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        # Remove default input Geometry — we source from Object Info nodes
        for item in list(tree.interface.items_tree):
            if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == 'Geometry':
                tree.interface.remove(item)

        n_output = _new_node(tree, 'NodeGroupOutput', location=(600, 0))

        # Curve Object Info
        n_curve = _new_node(tree, 'GeometryNodeObjectInfo',
                            label='Curve', location=(-400, 100))
        n_curve.inputs['Object'].default_value = curve_obj
        n_curve.transform_space = 'RELATIVE'

        # Profile Object Info
        n_profile = _new_node(tree, 'GeometryNodeObjectInfo',
                              label='Profile', location=(-400, -100))
        n_profile.inputs['Object'].default_value = profile_obj
        n_profile.transform_space = 'RELATIVE'

        # If profile is a mesh, convert to curve first
        if profile_obj.type == 'MESH':
            n_mesh_to_curve = _new_node(tree, 'GeometryNodeMeshToCurve',
                                        label='Mesh to Curve', location=(-200, -100))
            _link(tree, n_profile.outputs['Geometry'], n_mesh_to_curve.inputs['Mesh'])
            profile_geo_output = n_mesh_to_curve.outputs['Curve']
        else:
            profile_geo_output = n_profile.outputs['Geometry']

        # Curve to Mesh
        n_c2m = _new_node(tree, 'GeometryNodeCurveToMesh',
                          label='Curve to Mesh', location=(200, 0))
        n_c2m.inputs['Fill Caps'].default_value = fill_caps
        _link(tree, n_curve.outputs['Geometry'], n_c2m.inputs['Curve'])
        _link(tree, profile_geo_output, n_c2m.inputs['Profile Curve'])

        _link(tree, n_c2m.outputs['Mesh'], n_output.inputs['Geometry'])

        # Create a new empty/mesh object to host the modifier
        mesh_data = bpy.data.meshes.new(result_name)
        result_obj = bpy.data.objects.new(result_name, mesh_data)
        bpy.context.collection.objects.link(result_obj)

        modifier = result_obj.modifiers.new(name=tree_name, type='NODES')
        modifier.node_group = tree

        return {
            "success": True,
            "node_group": tree.name,
            "modifier": modifier.name,
            "object": result_obj.name,
            "curve": curve_name,
            "profile": profile_name,
            "fill_caps": fill_caps,
            "resolution": resolution,
        }

    # ── 7. Inspect ───────────────────────────────────────────────────

    def _handle_geonode_inspect(self, params: dict) -> dict:
        """Read the GN setup on an object: group name, inputs, outputs, values."""
        import bpy

        from .utils import get_object_or_error
        from .validation import require_param

        object_name = require_param(params, "object_name", str)
        modifier_name = params.get("modifier_name")

        obj = get_object_or_error(object_name)
        modifier = _get_gn_modifier(obj, modifier_name)
        if modifier is None:
            if modifier_name:
                return {"error": f"No Geometry Nodes modifier '{modifier_name}' on '{object_name}'"}
            return {"error": f"No Geometry Nodes modifier found on '{object_name}'"}

        group = modifier.node_group
        if group is None:
            return {"error": f"Modifier '{modifier.name}' has no node group assigned"}

        inputs_info, outputs_info = _build_socket_info(group)

        # Read current modifier input values
        input_values = {}
        for inp in inputs_info:
            val = _read_modifier_input(modifier, inp["identifier"])
            input_values[inp["name"]] = {
                "type": inp["type"],
                "identifier": inp["identifier"],
                "value": val,
            }

        # Count nodes
        node_count = len(group.nodes)
        link_count = len(group.links)

        # Node type summary
        node_types = {}
        for node in group.nodes:
            t = node.bl_idname
            node_types[t] = node_types.get(t, 0) + 1

        return {
            "success": True,
            "object": object_name,
            "modifier": modifier.name,
            "node_group": group.name,
            "inputs": input_values,
            "outputs": [{"name": o["name"], "type": o["type"]} for o in outputs_info],
            "node_count": node_count,
            "link_count": link_count,
            "node_types": node_types,
        }



_CLOTH_PRESETS = {
    "SILK": {
        "quality": 8,
        "mass": 0.15,
        "air_damping": 1.0,
        "tension_stiffness": 5.0,
        "compression_stiffness": 5.0,
        "bending_stiffness": 0.05,
        "tension_damping": 0.0,
        "compression_damping": 0.0,
        "bending_damping": 0.5,
    },
    "COTTON": {
        "quality": 7,
        "mass": 0.3,
        "air_damping": 1.0,
        "tension_stiffness": 15.0,
        "compression_stiffness": 15.0,
        "bending_stiffness": 0.5,
        "tension_damping": 5.0,
        "compression_damping": 5.0,
        "bending_damping": 0.5,
    },
    "DENIM": {
        "quality": 12,
        "mass": 0.4,
        "air_damping": 1.0,
        "tension_stiffness": 40.0,
        "compression_stiffness": 40.0,
        "bending_stiffness": 10.0,
        "tension_damping": 25.0,
        "compression_damping": 25.0,
        "bending_damping": 0.5,
    },
    "LEATHER": {
        "quality": 15,
        "mass": 0.4,
        "air_damping": 1.0,
        "tension_stiffness": 80.0,
        "compression_stiffness": 80.0,
        "bending_stiffness": 15.0,
        "tension_damping": 25.0,
        "compression_damping": 25.0,
        "bending_damping": 0.5,
    },
    "RUBBER": {
        "quality": 7,
        "mass": 3.0,
        "air_damping": 1.0,
        "tension_stiffness": 15.0,
        "compression_stiffness": 15.0,
        "bending_stiffness": 25.0,
        "tension_damping": 25.0,
        "compression_damping": 25.0,
        "bending_damping": 0.5,
    },
    "CANVAS": {
        "quality": 10,
        "mass": 0.35,
        "air_damping": 1.0,
        "tension_stiffness": 30.0,
        "compression_stiffness": 30.0,
        "bending_stiffness": 5.0,
        "tension_damping": 15.0,
        "compression_damping": 15.0,
        "bending_damping": 0.5,
    },
    "TARP": {
        "quality": 12,
        "mass": 0.5,
        "air_damping": 1.0,
        "tension_stiffness": 60.0,
        "compression_stiffness": 60.0,
        "bending_stiffness": 20.0,
        "tension_damping": 25.0,
        "compression_damping": 25.0,
        "bending_damping": 0.5,
    },
}


def _markup_with_pillow(render_path, annotations, output_path, Image, ImageDraw, ImageFont):
    """Draw markup annotations using Pillow."""
    img = Image.open(render_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    annotation_count = 0

    for ann in annotations:
        ann_type = ann.get("type", "").lower()
        color_str = ann.get("color", "red")
        thickness = int(ann.get("thickness", 3))

        if ann_type == "arrow":
            start = ann.get("start")
            end = ann.get("end")
            if not start or not end:
                continue
            sx, sy = int(start[0]), int(start[1])
            ex, ey = int(end[0]), int(end[1])

            # Draw the line
            draw.line([(sx, sy), (ex, ey)], fill=color_str, width=thickness)

            # Draw arrowhead
            angle = math.atan2(ey - sy, ex - sx)
            arrow_len = max(10, thickness * 4)
            for da in [math.pi * 0.8, -math.pi * 0.8]:
                ax = ex + arrow_len * math.cos(angle + da)
                ay = ey + arrow_len * math.sin(angle + da)
                draw.line(
                    [(ex, ey), (int(ax), int(ay))],
                    fill=color_str,
                    width=thickness,
                )
            annotation_count += 1

        elif ann_type == "circle":
            center = ann.get("center")
            radius = ann.get("radius")
            if not center or radius is None:
                continue
            cx, cy = int(center[0]), int(center[1])
            r = int(radius)
            draw.ellipse(
                [(cx - r, cy - r), (cx + r, cy + r)],
                outline=color_str,
                width=thickness,
            )
            annotation_count += 1

        elif ann_type == "rectangle":
            start = ann.get("start")
            end = ann.get("end")
            if not start or not end:
                continue
            sx, sy = int(start[0]), int(start[1])
            ex, ey = int(end[0]), int(end[1])
            draw.rectangle(
                [(sx, sy), (ex, ey)],
                outline=color_str,
                width=thickness,
            )
            annotation_count += 1

        elif ann_type == "text":
            position = ann.get("position")
            text = ann.get("text", "")
            if not position or not text:
                continue
            px, py = int(position[0]), int(position[1])
            font_size = int(ann.get("font_size", 24))

            # Try to load a font, fall back to default
            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    font_size,
                )
            except (OSError, IOError):
                try:
                    font = ImageFont.truetype(
                        "/usr/share/fonts/TTF/DejaVuSans.ttf",
                        font_size,
                    )
                except (OSError, IOError):
                    font = ImageFont.load_default()

            draw.text((px, py), text, fill=color_str, font=font)
            annotation_count += 1

    # Composite overlay onto image
    result = Image.alpha_composite(img, overlay)
    result.save(output_path)

    return {
        "success": True,
        "output_path": output_path,
        "annotations_drawn": annotation_count,
        "image_size": list(img.size),
        "method": "pillow",
    }


def _markup_with_compositor(render_path, annotations, output_path):
    """Fallback: use Blender's compositor to overlay annotations.

    This is a simplified fallback that loads the image, creates a GP overlay
    annotation in 2D screen space, and re-renders the composite.
    """
    # Load the image into Blender
    img = bpy.data.images.load(render_path)
    width, height = img.size[0], img.size[1]

    # Set up compositor
    scene = bpy.context.scene
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()

    # Create nodes
    image_node = tree.nodes.new('CompositorNodeImage')
    image_node.image = img
    image_node.location = (0, 0)

    composite_node = tree.nodes.new('CompositorNodeComposite')
    composite_node.location = (400, 0)

    # Connect image to composite output
    tree.links.new(image_node.outputs[0], composite_node.inputs[0])

    # Set render resolution to match image
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.filepath = output_path

    # Set file format based on extension
    ext = os.path.splitext(output_path)[1].lower()
    if ext in ('.jpg', '.jpeg'):
        scene.render.image_settings.file_format = 'JPEG'
    else:
        scene.render.image_settings.file_format = 'PNG'

    # Render composite
    bpy.ops.render.render(write_still=True)

    # Clean up
    bpy.data.images.remove(img)

    return {
        "success": True,
        "output_path": output_path,
        "annotations_drawn": 0,
        "image_size": [width, height],
        "method": "compositor_fallback",
        "note": "Compositor fallback does not draw markup annotations directly. "
        "Install Pillow (pip install Pillow) in Blender's Python for full annotation support.",
    }


# ── Preset builder helpers ────────────────────────────────────────────

def _add_principled(tree, loc=(0, 0)):
    """Create a Principled BSDF and Material Output, connected."""
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = loc
    out = tree.nodes.new("ShaderNodeOutputMaterial")
    out.location = (loc[0] + 300, loc[1])
    tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return bsdf, out


def _set_color(bsdf, color, fallback):
    """Set Base Color on a Principled BSDF. *color* is an optional RGBA list."""
    c = color if color else fallback
    if len(c) == 3:
        c = list(c) + [1.0]
    bsdf.inputs["Base Color"].default_value = c


def _add_noise(tree, loc=(-600, 0), scale=5.0, detail=2.0, roughness=0.5):
    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.location = loc
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = detail
    noise.inputs["Roughness"].default_value = roughness
    return noise


def _add_bump(tree, loc=(-200, -300), strength=0.1, distance=0.02):
    bump = tree.nodes.new("ShaderNodeBump")
    bump.location = loc
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = distance
    return bump


def _add_color_ramp(tree, loc=(-300, 0)):
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.location = loc
    return ramp


def _add_mapping(tree, loc=(-900, 0), scale_val=None):
    coord = tree.nodes.new("ShaderNodeTexCoord")
    coord.location = (loc[0] - 200, loc[1])
    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.location = loc
    tree.links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    if scale_val:
        mapping.inputs["Scale"].default_value = (scale_val, scale_val, scale_val)
    return coord, mapping


# ── Individual preset builders ────────────────────────────────────────

def _build_vehicle_paint(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.0, 0.15, 0.6, 1.0])
    bsdf.inputs["Metallic"].default_value = 0.4
    bsdf.inputs["Roughness"].default_value = 0.15
    bsdf.inputs["Coat Weight"].default_value = 1.0
    bsdf.inputs["Coat Roughness"].default_value = 0.05

    # Metallic flake noise
    noise = _add_noise(tree, (-600, -100), scale=200.0 * scale, detail=4.0)
    ramp = _add_color_ramp(tree, (-400, -100))
    ramp.color_ramp.elements[0].position = 0.45
    ramp.color_ramp.elements[1].position = 0.55
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])

    bump = _add_bump(tree, (-200, -300), strength=0.02)
    tree.links.new(ramp.outputs["Color"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_brushed_metal(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.6, 0.6, 0.6, 1.0])
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.3
    bsdf.inputs["Anisotropic"].default_value = 0.8

    # Anisotropic brush direction via noise
    noise = _add_noise(tree, (-600, 0), scale=100.0 * scale, detail=0.0, roughness=1.0)
    noise.noise_dimensions = "2D"

    bump = _add_bump(tree, (-200, -300), strength=0.05)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_chrome(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.9, 0.9, 0.9, 1.0])
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.05


def _build_rubber(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.02, 0.02, 0.02, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.8

    noise = _add_noise(tree, (-600, -100), scale=30.0 * scale, detail=6.0)
    bump = _add_bump(tree, (-200, -300), strength=0.15)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_carbon_fiber(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.01, 0.01, 0.01, 1.0])
    bsdf.inputs["Metallic"].default_value = 0.3
    bsdf.inputs["Roughness"].default_value = 0.2
    bsdf.inputs["Coat Weight"].default_value = 1.0
    bsdf.inputs["Coat Roughness"].default_value = 0.05

    # Wave texture for weave pattern
    wave = tree.nodes.new("ShaderNodeTexWave")
    wave.location = (-600, 0)
    wave.inputs["Scale"].default_value = 20.0 * scale
    wave.wave_type = "RINGS"
    wave.rings_direction = "SPHERICAL"

    bump = _add_bump(tree, (-200, -300), strength=0.1)
    tree.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_asphalt(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.05, 0.05, 0.05, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.9

    noise = _add_noise(tree, (-600, 0), scale=15.0 * scale, detail=8.0)
    ramp = _add_color_ramp(tree, (-400, 0))
    ramp.color_ramp.elements[0].color = (0.03, 0.03, 0.03, 1.0)
    ramp.color_ramp.elements[1].color = (0.08, 0.08, 0.08, 1.0)
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bump = _add_bump(tree, (-200, -300), strength=0.3)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_tarmac(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.08, 0.08, 0.08, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.85

    noise = _add_noise(tree, (-600, 0), scale=8.0 * scale, detail=10.0)
    ramp = _add_color_ramp(tree, (-400, 0))
    ramp.color_ramp.elements[0].color = (0.05, 0.05, 0.05, 1.0)
    ramp.color_ramp.elements[1].color = (0.12, 0.11, 0.10, 1.0)
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bump = _add_bump(tree, (-200, -300), strength=0.25)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_worn_metal(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.5, 0.5, 0.5, 1.0])
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.4

    # Edge wear via noise + color ramp
    noise = _add_noise(tree, (-800, 0), scale=10.0 * scale, detail=6.0)
    ramp = _add_color_ramp(tree, (-600, 0))
    ramp.color_ramp.elements[0].position = 0.5 - wear * 0.3
    ramp.color_ramp.elements[1].position = 0.5 + wear * 0.2
    ramp.color_ramp.elements[0].color = (0.2, 0.15, 0.1, 1.0)  # worn / rust tint
    ramp.color_ramp.elements[1].color = (0.5, 0.5, 0.5, 1.0)
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    # Roughness variation
    ramp2 = _add_color_ramp(tree, (-600, -250))
    ramp2.color_ramp.elements[0].position = 0.4
    ramp2.color_ramp.elements[0].color = (0.7, 0.7, 0.7, 1.0)
    ramp2.color_ramp.elements[1].color = (0.3, 0.3, 0.3, 1.0)
    tree.links.new(noise.outputs["Fac"], ramp2.inputs["Fac"])
    tree.links.new(ramp2.outputs["Color"], bsdf.inputs["Roughness"])

    bump = _add_bump(tree, (-200, -400), strength=0.2 * wear)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_glass(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [1.0, 1.0, 1.0, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.0
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    bsdf.inputs["IOR"].default_value = 1.45


def _build_plastic_glossy(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.8, 0.1, 0.1, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.15
    bsdf.inputs["Specular IOR Level"].default_value = 0.5


def _build_plastic_matte(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.3, 0.3, 0.35, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.6
    bsdf.inputs["Specular IOR Level"].default_value = 0.3


def _build_concrete(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.45, 0.43, 0.40, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.85

    # Voronoi for aggregate
    voronoi = tree.nodes.new("ShaderNodeTexVoronoi")
    voronoi.location = (-800, 0)
    voronoi.inputs["Scale"].default_value = 10.0 * scale

    noise = _add_noise(tree, (-800, -250), scale=20.0 * scale, detail=8.0)

    # Mix voronoi and noise for surface variation
    mix = tree.nodes.new("ShaderNodeMix")
    mix.location = (-500, 0)
    mix.data_type = "RGBA"
    mix.inputs[0].default_value = 0.3  # Factor
    tree.links.new(voronoi.outputs["Distance"], mix.inputs[6])
    tree.links.new(noise.outputs["Fac"], mix.inputs[7])

    bump = _add_bump(tree, (-200, -300), strength=0.3)
    tree.links.new(mix.outputs[2], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_fabric(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.2, 0.1, 0.05, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.8
    bsdf.inputs["Sheen Weight"].default_value = 0.5

    wave = tree.nodes.new("ShaderNodeTexWave")
    wave.location = (-600, 0)
    wave.inputs["Scale"].default_value = 40.0 * scale
    wave.wave_type = "BANDS"
    wave.inputs["Distortion"].default_value = 2.0

    bump = _add_bump(tree, (-200, -300), strength=0.1)
    tree.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_reflective_tape(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.9, 0.9, 0.1, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.1
    bsdf.inputs["Specular IOR Level"].default_value = 1.0
    bsdf.inputs["Emission Color"].default_value = (0.9, 0.9, 0.1, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 0.5

    # Micro-bead pattern
    noise = _add_noise(tree, (-600, -100), scale=200.0 * scale, detail=2.0)
    bump = _add_bump(tree, (-200, -300), strength=0.03)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_led_display(tree, color, wear, scale):
    # Emission-based with grid pattern
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.location = (0, 0)
    c = color if color else [0.0, 1.0, 0.0, 1.0]
    if len(c) == 3:
        c = list(c) + [1.0]
    emission.inputs["Color"].default_value = c
    emission.inputs["Strength"].default_value = 5.0

    out = tree.nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    tree.links.new(emission.outputs["Emission"], out.inputs["Surface"])

    # Grid pattern via checker
    checker = tree.nodes.new("ShaderNodeTexChecker")
    checker.location = (-600, 0)
    checker.inputs["Scale"].default_value = 50.0 * scale
    checker.inputs["Color1"].default_value = (0.0, 0.0, 0.0, 1.0)
    checker.inputs["Color2"].default_value = (1.0, 1.0, 1.0, 1.0)

    # Multiply emission by grid
    mix = tree.nodes.new("ShaderNodeMix")
    mix.location = (-300, 0)
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs[0].default_value = 1.0
    mix.inputs[6].default_value = c
    tree.links.new(checker.outputs["Color"], mix.inputs[7])
    tree.links.new(mix.outputs[2], emission.inputs["Color"])


def _build_rust(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    bsdf.inputs["Metallic"].default_value = 0.6
    bsdf.inputs["Roughness"].default_value = 0.75

    noise = _add_noise(tree, (-800, 0), scale=6.0 * scale, detail=8.0)
    noise2 = _add_noise(tree, (-800, -250), scale=15.0 * scale, detail=4.0)

    ramp = _add_color_ramp(tree, (-600, 0))
    # Rust color gradient
    ramp.color_ramp.elements[0].position = 0.3
    ramp.color_ramp.elements[0].color = (0.1, 0.03, 0.01, 1.0)  # dark rust
    ramp.color_ramp.elements[1].position = 0.7
    ramp.color_ramp.elements[1].color = (0.5, 0.15, 0.02, 1.0)  # bright rust
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])

    if color:
        # Mix user color with rust based on wear
        mix = tree.nodes.new("ShaderNodeMix")
        mix.location = (-300, 0)
        mix.data_type = "RGBA"
        mix.inputs[0].default_value = wear
        c = list(color) if len(color) >= 4 else list(color) + [1.0]
        mix.inputs[6].default_value = c
        tree.links.new(ramp.outputs["Color"], mix.inputs[7])
        tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    else:
        tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bump = _add_bump(tree, (-200, -400), strength=0.4)
    tree.links.new(noise2.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_gold(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [1.0, 0.766, 0.336, 1.0])
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.2


def _build_copper(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.72, 0.45, 0.2, 1.0])
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.25

    # Patina noise
    noise = _add_noise(tree, (-600, 0), scale=5.0 * scale, detail=6.0)
    ramp = _add_color_ramp(tree, (-400, 0))
    ramp.color_ramp.elements[0].position = 0.5 - wear * 0.3
    ramp.color_ramp.elements[0].color = (0.72, 0.45, 0.2, 1.0)  # copper
    ramp.color_ramp.elements[1].position = 0.5 + wear * 0.3
    ramp.color_ramp.elements[1].color = (0.2, 0.5, 0.4, 1.0)  # green patina
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bump = _add_bump(tree, (-200, -300), strength=0.1)
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_scratched_paint(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.0, 0.15, 0.6, 1.0])
    bsdf.inputs["Metallic"].default_value = 0.4
    bsdf.inputs["Roughness"].default_value = 0.15
    bsdf.inputs["Coat Weight"].default_value = 1.0
    bsdf.inputs["Coat Roughness"].default_value = 0.05

    # Scratch overlay
    scratch_noise = _add_noise(tree, (-800, -200), scale=50.0 * scale, detail=10.0, roughness=1.0)
    scratch_ramp = _add_color_ramp(tree, (-600, -200))
    thresh = 0.85 - wear * 0.3  # more wear = more scratches
    scratch_ramp.color_ramp.elements[0].position = thresh
    scratch_ramp.color_ramp.elements[1].position = thresh + 0.05
    tree.links.new(scratch_noise.outputs["Fac"], scratch_ramp.inputs["Fac"])

    # Mix paint color with exposed metal at scratches
    mix = tree.nodes.new("ShaderNodeMix")
    mix.location = (-300, 0)
    mix.data_type = "RGBA"
    paint_c = color if color else [0.0, 0.15, 0.6, 1.0]
    if len(paint_c) == 3:
        paint_c = list(paint_c) + [1.0]
    mix.inputs[6].default_value = paint_c
    mix.inputs[7].default_value = (0.5, 0.5, 0.5, 1.0)  # bare metal
    tree.links.new(scratch_ramp.outputs["Color"], mix.inputs[0])
    tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])

    # Scratches affect roughness
    mix_r = tree.nodes.new("ShaderNodeMix")
    mix_r.location = (-300, -250)
    mix_r.data_type = "FLOAT"
    mix_r.inputs[2].default_value = 0.15  # paint roughness
    mix_r.inputs[3].default_value = 0.5   # scratch roughness
    tree.links.new(scratch_ramp.outputs["Color"], mix_r.inputs[0])
    tree.links.new(mix_r.outputs[0], bsdf.inputs["Roughness"])

    # Scratches affect metallic
    mix_m = tree.nodes.new("ShaderNodeMix")
    mix_m.location = (-300, -400)
    mix_m.data_type = "FLOAT"
    mix_m.inputs[2].default_value = 0.0  # paint metallic
    mix_m.inputs[3].default_value = 1.0  # scratch metallic
    tree.links.new(scratch_ramp.outputs["Color"], mix_m.inputs[0])
    tree.links.new(mix_m.outputs[0], bsdf.inputs["Metallic"])


def _build_snow(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.95, 0.95, 0.97, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.6
    bsdf.inputs["Subsurface Weight"].default_value = 0.1
    bsdf.inputs["Subsurface Radius"].default_value = (0.5, 0.5, 0.5)

    # Sparkle noise
    noise = _add_noise(tree, (-600, -100), scale=100.0 * scale, detail=2.0)
    ramp = _add_color_ramp(tree, (-400, -100))
    ramp.color_ramp.elements[0].position = 0.7
    ramp.color_ramp.elements[1].position = 0.75
    tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])

    # Sparkle slightly reduces roughness
    mix_r = tree.nodes.new("ShaderNodeMix")
    mix_r.location = (-200, -200)
    mix_r.data_type = "FLOAT"
    mix_r.inputs[2].default_value = 0.6
    mix_r.inputs[3].default_value = 0.1  # sparkle = very smooth
    tree.links.new(ramp.outputs["Color"], mix_r.inputs[0])
    tree.links.new(mix_r.outputs[0], bsdf.inputs["Roughness"])

    bump = _add_bump(tree, (-200, -400), strength=0.15)
    noise2 = _add_noise(tree, (-600, -400), scale=8.0 * scale, detail=5.0)
    tree.links.new(noise2.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_water(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    _set_color(bsdf, color, [0.01, 0.04, 0.08, 1.0])
    bsdf.inputs["Roughness"].default_value = 0.0
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    bsdf.inputs["IOR"].default_value = 1.33

    # Wave normal
    wave = tree.nodes.new("ShaderNodeTexWave")
    wave.location = (-600, -100)
    wave.inputs["Scale"].default_value = 5.0 * scale
    wave.inputs["Distortion"].default_value = 4.0
    wave.inputs["Detail"].default_value = 3.0
    wave.wave_type = "BANDS"

    bump = _add_bump(tree, (-200, -300), strength=0.05)
    tree.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_wood(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    bsdf.inputs["Roughness"].default_value = 0.5

    # Wave texture for grain
    wave = tree.nodes.new("ShaderNodeTexWave")
    wave.location = (-600, 0)
    wave.inputs["Scale"].default_value = 3.0 * scale
    wave.inputs["Distortion"].default_value = 8.0
    wave.inputs["Detail"].default_value = 3.0
    wave.wave_type = "BANDS"

    ramp = _add_color_ramp(tree, (-400, 0))
    ramp.color_ramp.elements[0].color = (0.15, 0.08, 0.03, 1.0)  # dark grain
    ramp.color_ramp.elements[1].color = (0.4, 0.22, 0.1, 1.0)   # light grain
    tree.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])

    if color:
        # Tint the wood grain towards user color
        mix = tree.nodes.new("ShaderNodeMix")
        mix.location = (-200, 0)
        mix.data_type = "RGBA"
        mix.inputs[0].default_value = 0.3
        c = list(color) if len(color) >= 4 else list(color) + [1.0]
        mix.inputs[7].default_value = c
        tree.links.new(ramp.outputs["Color"], mix.inputs[6])
        tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    else:
        tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bump = _add_bump(tree, (-200, -300), strength=0.1)
    tree.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_brick(tree, color, wear, scale):
    bsdf, out = _add_principled(tree)
    bsdf.inputs["Roughness"].default_value = 0.8

    brick = tree.nodes.new("ShaderNodeTexBrick")
    brick.location = (-600, 0)
    brick.inputs["Scale"].default_value = 5.0 * scale
    c = color if color else [0.55, 0.2, 0.1, 1.0]
    if len(c) == 3:
        c = list(c) + [1.0]
    brick.inputs["Color1"].default_value = c
    brick.inputs["Color2"].default_value = (
        c[0] * 0.7, c[1] * 0.7, c[2] * 0.7, 1.0
    )
    brick.inputs["Mortar"].default_value = (0.7, 0.7, 0.65, 1.0)
    brick.inputs["Mortar Size"].default_value = 0.02

    tree.links.new(brick.outputs["Color"], bsdf.inputs["Base Color"])

    bump = _add_bump(tree, (-200, -300), strength=0.3)
    tree.links.new(brick.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


# Registry of all preset builders

_PRESET_BUILDERS = {
    "VEHICLE_PAINT": _build_vehicle_paint,
    "BRUSHED_METAL": _build_brushed_metal,
    "CHROME": _build_chrome,
    "RUBBER": _build_rubber,
    "CARBON_FIBER": _build_carbon_fiber,
    "ASPHALT": _build_asphalt,
    "TARMAC": _build_tarmac,
    "WORN_METAL": _build_worn_metal,
    "GLASS": _build_glass,
    "PLASTIC_GLOSSY": _build_plastic_glossy,
    "PLASTIC_MATTE": _build_plastic_matte,
    "CONCRETE": _build_concrete,
    "FABRIC": _build_fabric,
    "REFLECTIVE_TAPE": _build_reflective_tape,
    "LED_DISPLAY": _build_led_display,
    "RUST": _build_rust,
    "GOLD": _build_gold,
    "COPPER": _build_copper,
    "SCRATCHED_PAINT": _build_scratched_paint,
    "SNOW": _build_snow,
    "WATER": _build_water,
    "WOOD": _build_wood,
    "BRICK": _build_brick,
}


def _extract_pbr_values(tree) -> dict:
    """Analyze an existing node tree and extract PBR-relevant values."""
    result = {
        "base_color": [0.8, 0.8, 0.8, 1.0],
        "metallic": 0.0,
        "roughness": 0.5,
        "alpha": 1.0,
        "emission_color": None,
        "emission_strength": 0.0,
        "transmission": 0.0,
        "base_color_image": None,
    }

    for node in tree.nodes:
        # ── Principled BSDF ──
        if node.type == "BSDF_PRINCIPLED":
            if hasattr(node.inputs["Base Color"], "default_value"):
                result["base_color"] = list(node.inputs["Base Color"].default_value)
            result["metallic"] = node.inputs["Metallic"].default_value
            result["roughness"] = node.inputs["Roughness"].default_value
            result["alpha"] = node.inputs["Alpha"].default_value

            if "Emission Color" in node.inputs:
                ec = node.inputs["Emission Color"].default_value
                result["emission_color"] = list(ec)
            if "Emission Strength" in node.inputs:
                result["emission_strength"] = node.inputs["Emission Strength"].default_value

            if "Transmission Weight" in node.inputs:
                result["transmission"] = node.inputs["Transmission Weight"].default_value
            elif "Transmission" in node.inputs:
                result["transmission"] = node.inputs["Transmission"].default_value

            # Check for connected base color texture
            bc_input = node.inputs["Base Color"]
            if bc_input.is_linked:
                linked_node = bc_input.links[0].from_node
                if linked_node.type == "TEX_IMAGE" and linked_node.image:
                    result["base_color_image"] = linked_node.image

            break  # Principled found, no need to keep searching

        # ── Diffuse BSDF fallback ──
        elif node.type == "BSDF_DIFFUSE":
            if hasattr(node.inputs["Color"], "default_value"):
                c = list(node.inputs["Color"].default_value)
                result["base_color"] = c if len(c) == 4 else c + [1.0]
            result["roughness"] = node.inputs["Roughness"].default_value
            # Don't break; a Principled might exist elsewhere

        # ── Glossy BSDF fallback ──
        elif node.type == "BSDF_GLOSSY":
            if hasattr(node.inputs["Color"], "default_value"):
                c = list(node.inputs["Color"].default_value)
                result["base_color"] = c if len(c) == 4 else c + [1.0]
            result["roughness"] = node.inputs["Roughness"].default_value
            result["metallic"] = 1.0

        # ── Emission fallback ──
        elif node.type == "EMISSION":
            if hasattr(node.inputs["Color"], "default_value"):
                result["emission_color"] = list(node.inputs["Color"].default_value)
            if "Strength" in node.inputs:
                result["emission_strength"] = node.inputs["Strength"].default_value

        # ── Glass BSDF fallback ──
        elif node.type == "BSDF_GLASS":
            if hasattr(node.inputs["Color"], "default_value"):
                c = list(node.inputs["Color"].default_value)
                result["base_color"] = c if len(c) == 4 else c + [1.0]
            result["roughness"] = node.inputs["Roughness"].default_value
            result["transmission"] = 1.0

    return result

