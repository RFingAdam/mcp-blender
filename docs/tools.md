# Tools

`mcp-blender` exposes **218 MCP tools** across every Blender pipeline
stage. Rather than enumerate all 218 here, this page groups them by
category and links to the source. Each tool's argument schema is
available at runtime through the MCP protocol (`tools/list`).

Server-side dispatch:
[`src/mcp_blender/`](https://github.com/RFingAdam/mcp-blender/tree/main/src/mcp_blender).
Blender-side handlers (the actual `bpy` calls):
[`addon/blender_mcp_addon/`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon).

## Tool counts by category

| Category                       | Tools | Source |
| ------------------------------ | ----: | ------ |
| Scene                          |   5 | [`addon/.../handlers/scene.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Object                         |  10 | [`addon/.../handlers/object_ops.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Mesh editing                   |  24 | [`addon/.../handlers/mesh.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Materials + nodes              |  13 | [`addon/.../handlers/materials.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Modifiers                      |   5 | [`addon/.../handlers/modifiers.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Animation + keyframes          |   7 | [`addon/.../handlers/animation.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Render                         |   5 | [`addon/.../handlers/render.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Export / import                |   6 | [`addon/.../handlers/io.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Measurement + validation       |   7 | [`addon/.../handlers/measurement.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Baking                         |   6 | [`addon/.../handlers/baking.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Geometry nodes                 |   7 | [`addon/.../handlers/geonode.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Sculpting                      |   8 | [`addon/.../handlers/sculpting.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Rigging + armature             |   8 | [`addon/.../handlers/rigging.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Physics                        |   6 | [`addon/.../handlers/physics.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Collections + system           |   8 | [`addon/.../handlers/system.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| Annotations + grease pencil    |   6 | [`addon/.../handlers/annotation.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/handlers) |
| MSFS content                   |  20 | [`addon/.../msfs/`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/msfs) |
| MSFS livery                    |  18 | [`addon/.../msfs/livery/`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/msfs/livery) |
| AI 3D generation               |  21 | [`addon/.../external/ai_models.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/external) |
| AI texture generation          |   5 | [`addon/.../external/ai_backends/comfyui.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/external/ai_backends) |
| AI evaluation                  |   2 | [`addon/.../external/refinement.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/external) |
| AI self-refinement             |   7 | [`addon/.../external/refinement.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/external) |
| Poly Haven                     |   2 | [`addon/.../external/polyhaven.py`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon/external) |
| **Total**                      | **218** |    |

---

## Scene (5)

`scene_info`, `scene_new`, `scene_clear`, `scene_set_frame_range`, `get_version`.

Top-level scene queries and lifecycle.

## Object (10)

`object_create`, `object_delete`, `object_list`, `object_get`,
`object_transform`, `object_duplicate`, `object_join`,
`object_separate`, `object_parent`, `object_select`.

`object_create` supports primitives: cube, sphere, cylinder, plane,
cone, torus, monkey, empty, camera, light.

## Mesh editing (24)

`mesh_from_data`, `mesh_extrude`, `mesh_bevel`, `mesh_inset`,
`mesh_subdivide`, `mesh_loop_cut`, `mesh_bridge`, `mesh_fill`,
`mesh_dissolve`, `mesh_merge`, `mesh_split`, `mesh_separate_selected`,
`mesh_bisect`, `mesh_flatten`, `mesh_shrinkwrap`, `mesh_knife_project`,
`mesh_proportional_transform`, `mesh_select`, `mesh_select_trait`,
`mesh_select_edge_loops`, `mesh_select_linked_flat`,
`mesh_select_shortest_path`, `mesh_get_selection`, `mesh_tris_to_quads`,
`mesh_crease`, `mesh_mark_seam`, `mesh_mark_sharp`, `mesh_edge_slide`.

(Count includes selection helpers and topology marks.)

## Materials + nodes (13)

`material_create`, `material_assign`, `material_list`,
`material_set_color`, `material_set_principled`, `material_add_texture`,
`material_inspect_graph`, `material_node_add`, `material_node_connect`,
`material_node_group_create`, `material_procedural_preset`,
`material_convert_to_pbr`, `material_preview_render`.

23 procedural presets: CHROME, RUST, VEHICLE_PAINT, CARBON_FIBER, etc.

## Modifiers (5)

`modifier_add`, `modifier_remove`, `modifier_apply`,
`modifier_configure`, `modifier_list`.

Supported types (28+): SUBSURF, BEVEL, SOLIDIFY, ARRAY, MIRROR, BOOLEAN,
DECIMATE, REMESH, SMOOTH, LAPLACIANSMOOTH, TRIANGULATE, WIREFRAME, SKIN,
ARMATURE, LATTICE, CURVE, SHRINKWRAP, SIMPLE_DEFORM, WAVE, DISPLACE,
CAST, HOOK, MESH_DEFORM, SURFACE_DEFORM, WARP, LAPLACIANDEFORM,
CORRECTIVE_SMOOTH, DATA_TRANSFER.

## Animation + keyframes (7)

`keyframe_insert`, `keyframe_delete`, `keyframe_list`, `action_create`,
`action_list`, `animation_play`, `animation_goto_frame`.

## Render (5)

`render_image`, `render_animation`, `render_set_engine`,
`render_set_resolution`, `render_screenshot`, `render_multi_angle`.

Engines: CYCLES, BLENDER_EEVEE_NEXT, BLENDER_WORKBENCH.

## Export / import (6)

`export_gltf`, `export_fbx`, `export_obj`, `export_stl`, `export_usd`,
`import_file` (auto-detects format).

## Measurement + validation (7)

`measure_surface_area`, `measure_volume`, `measure_clearance`,
`measure_edge_angle`, `validate_dimensions`, `calibrate_from_reference`,
`validate_mesh_quality` (11-check audit).

## Baking (6)

`bake_pbr_batch` (diffuse / normal / roughness / metallic / AO /
emission in one call), `bake_highpoly_to_lowpoly`,
`bake_from_multires`, `bake_to_vertex_colors`, `bake_curvature`,
`bake_id_map`.

## Geometry nodes (7)

`geonode_create_group`, `geonode_apply`, `geonode_scatter_instances`,
`geonode_array_grid`, `geonode_deform_curve`, `geonode_extrude_profile`,
`geonode_inspect`.

## Sculpting (8)

`sculpt_setup`, `sculpt_mesh_filter`, `sculpt_mask_by_topology`,
`sculpt_face_set_create`, `sculpt_multires_reshape`,
`sculpt_to_retopo`, `sculpt_extract_mask`, `sculpt_remesh_voxel`.

## Rigging + armature (8)

`armature_create`, `autorig_preset` (BIPED, VEHICLE, MECHANICAL_ARM,
WHEEL_ASSEMBLY, PISTON, …), `constraint_add`, `constraint_preset`,
`bone_shape_assign`, `pose_library_save`, `pose_library_apply`,
`rig_validate`.

## Physics (6)

`physics_rigid_body_add`, `physics_rigid_body_batch`,
`physics_cloth_add` (7 presets), `physics_soft_body_add`,
`physics_fluid_quick` (Mantaflow), `physics_simulate`.

## Collections + system (8)

`collection_create`, `collection_list`, `collection_move`,
`collection_visibility`, `collection_instance`, `undo`, `redo`,
`save`, `save_as`.

## Annotations + grease pencil (6)

`annotation_add`, `annotation_text`, `annotation_dimension`,
`annotation_clear`, `grease_pencil_create`, `grease_pencil_markup`.

## MSFS content (20)

LOD: `msfs_create_lod_hierarchy`, `msfs_decimate_for_lod`,
`msfs_setup_lod_distances`, `msfs_get_lod_info`,
`msfs_batch_export_lods`.

Materials: `msfs_setup_material`, `msfs_create_glass_material`,
`msfs_create_emissive_material`, `msfs_get_material_presets`.

Collision: `msfs_create_collision_mesh`, `msfs_create_collision_box`,
`msfs_create_collision_convex`, `msfs_tag_collision_type`.

Animation: `msfs_add_animation_tag`, `msfs_setup_visibility_animation`,
`msfs_configure_animation_loop`, `msfs_list_animation_tags`.

Export: `msfs_export_model`, `msfs_validate_for_export`,
`msfs_get_export_settings`.

See [`MSFS_ROADMAP.md`](MSFS_ROADMAP.md).

## MSFS livery (18)

Paint workflow: `msfs_livery_setup_paint_mode`,
`msfs_livery_create_paint_layers`, `msfs_livery_load_template_overlay`,
`msfs_livery_export_uv_layout`, `msfs_livery_set_paint_brush`,
`msfs_livery_sample_color`, `msfs_livery_get_paint_presets`.

Templates + transfer: `msfs_livery_get_aircraft_templates`,
`msfs_livery_get_template_info`, `msfs_livery_download_template`,
`msfs_livery_analyze`, `msfs_livery_transfer`,
`msfs_livery_extract_colors`, `msfs_livery_map_elements`.

Packaging: `msfs_livery_export_textures`,
`msfs_livery_create_package`, `msfs_livery_convert_to_dds`,
`msfs_livery_validate_package`.

Supported aircraft: FlyByWire A32NX, Fenix A320/A319/A321,
PMDG 737/777, iniBuilds A310/A320neo, Aerosoft CRJ, Just Flight BAe 146,
generic.

## AI 3D generation (21)

Backend management (4): `ai_list_backends`, `ai_set_backend`,
`ai_get_backend_info`, `ai_configure_backend`.

Generation (5): `ai_generate_model`, `ai_generate_model_sync`,
`ai_model_status`, `ai_pipeline_generate`, `ai_pipeline_status`.

Probing (1): `ai_probe_backends`.

Mesh processing (7): `ai_mesh_cleanup`, `ai_mesh_decimate`,
`ai_mesh_remesh`, `ai_mesh_optimize`, `ai_auto_uv`,
`ai_fix_mesh_issues`, `ai_mesh_stats`.

Queue + control (4): `ai_evaluate`, `ai_refine`, `ai_set_backend`, etc.
(See [`ai_models.py`](https://github.com/RFingAdam/mcp-blender/blob/main/addon/blender_mcp_addon/external/ai_models.py)
for the full list and arguments.)

## AI texture generation (5)

`ai_generate_texture`, `ai_generate_texture_sync`,
`ai_generate_reference_image`, `ai_inpaint_texture`,
`ai_texture_from_render`.

ComfyUI / SDXL / ControlNet backed.

## AI evaluation (2)

`ai_evaluate`, `ai_refine` — Ollama vision scoring with category-specific
metrics (model / texture / animation).

## AI self-refinement (7)

`execute_script`, `render_multi_angle`, `analyze_viewport`,
`refine_iteration`, `refine_create_session`, `refine_get_session`,
`refine_list_sessions`.

See [`usage.md`](usage.md#scenario-iterative-3d-refinement) for a
full walkthrough.

## Poly Haven (2)

`polyhaven_search`, `polyhaven_download`. No API key required.

---

## How to query a tool's exact argument schema

Tool argument schemas are exposed via the MCP `tools/list` method at
runtime. From your client:

> *"What arguments does `blender_geonode_scatter_instances` take?"*

Your assistant reads the schema and reports the parameter names, types,
and defaults. Schemas are authoritative — this page only summarises.
