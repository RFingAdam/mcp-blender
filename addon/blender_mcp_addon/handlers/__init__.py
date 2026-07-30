"""Command handlers for MCP socket server.

This package organises handlers into domain-specific mixin modules.  The
public API is the ``CommandHandlers`` class which inherits from every mixin
and wires up the handler dispatch table in ``_register_handlers()``.
"""

from typing import Any

from .ai import AIHandlersMixin
from .animation import AnimationHandlersMixin
from .annotations import AnnotationHandlersMixin
from .armature import ArmatureHandlersMixin
from .baking import BakingHandlersMixin
from .collections import CollectionHandlersMixin
from .export_import import ExportImportHandlersMixin
from .geonodes import GeoNodesHandlersMixin
from .materials import MaterialHandlersMixin
from .measurement import MeasurementHandlersMixin
from .mesh_editing import MeshEditingHandlersMixin
from .modifiers import ModifierHandlersMixin
from .msfs import MSFSHandlersMixin
from .objects import ObjectHandlersMixin
from .physics import PhysicsHandlersMixin
from .render import RenderHandlersMixin
from .scene import SceneHandlersMixin
from .sculpt import SculptHandlersMixin
from .text_objects import TextObjectHandlersMixin


class CommandHandlers(
    SceneHandlersMixin,
    ObjectHandlersMixin,
    MaterialHandlersMixin,
    ModifierHandlersMixin,
    AnimationHandlersMixin,
    RenderHandlersMixin,
    ExportImportHandlersMixin,
    MeshEditingHandlersMixin,
    SculptHandlersMixin,
    ArmatureHandlersMixin,
    PhysicsHandlersMixin,
    MeasurementHandlersMixin,
    CollectionHandlersMixin,
    AnnotationHandlersMixin,
    AIHandlersMixin,
    MSFSHandlersMixin,
    BakingHandlersMixin,
    GeoNodesHandlersMixin,
    TextObjectHandlersMixin,
):
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

        # Text object tools (native vector/curve-based text, not raster reconstruction)
        self._handlers["text_create"] = self._handle_text_create
        self._handlers["text_set_properties"] = self._handle_text_set_properties
        self._handlers["text_to_mesh"] = self._handle_text_to_mesh

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
