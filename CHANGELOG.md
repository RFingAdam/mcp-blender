# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] — 2026-05-13

### Changed
- **License: MIT → AGPL-3.0-or-later.** Aligns with the eng-mcp-suite
  toolkit-wide AGPL move. The underlying Blender application is GPL-3.0+
  and is invoked at runtime by this wrapper without redistribution; the
  wrapper's AGPL license is independent of Blender's GPL. See the
  [LICENSE_SUMMARY](https://github.com/RFingAdam/eng-mcp-suite/blob/main/LICENSE_SUMMARY.md)
  for the toolkit-wide rationale.

## [0.3.0] - 2026-03-25

### Added

- **Material Inspection & Manipulation** (7 new tools):
  - `material_inspect_graph` — return full shader node graph as structured JSON
  - `material_node_add` — add any shader node to a material
  - `material_node_connect` — connect nodes via socket names
  - `material_node_group_create` — create reusable node groups
  - `material_procedural_preset` — 23 one-call procedural materials (VEHICLE_PAINT, CHROME, RUST, CARBON_FIBER, etc.)
  - `material_convert_to_pbr` — convert materials to clean Principled BSDF for GLTF/MSFS/UE5
  - `material_preview_render` — render material preview on standard shape

- **Measurement & Validation** (7 new tools):
  - `measure_surface_area` — total + per-material area breakdown
  - `measure_volume` — mesh volume with manifold check
  - `measure_clearance` — min/max/avg distance between two objects
  - `validate_dimensions` — check dimensions against spec with tolerance
  - `calibrate_from_reference` — scale object to match known real-world dimension
  - `measure_edge_angle` — dihedral angles at edges with threshold flagging
  - `validate_mesh_quality` — 11-check comprehensive mesh quality audit

- **Baking** (6 new tools):
  - `bake_pbr_batch` — bake ALL PBR channels (diffuse, normal, roughness, metallic, AO, emission, displacement) in one call
  - `bake_highpoly_to_lowpoly` — selected-to-active baking
  - `bake_from_multires` — bake from multires sculpt data
  - `bake_to_vertex_colors` — bake lighting/AO to vertex colors
  - `bake_curvature` — curvature map for wear/edge effects
  - `bake_id_map` — color ID map per material/object/face_set

- **Geometry Nodes** (7 new tools — first-ever GN support via MCP):
  - `geonode_create_group` — create typed node group with inputs/outputs
  - `geonode_apply` — apply GN group as modifier with input values
  - `geonode_scatter_instances` — one-call scatter with Poisson, density, random scale/rotation
  - `geonode_array_grid` — parametric arrays (linear, grid, radial, hexagonal)
  - `geonode_deform_curve` — deform mesh along curve
  - `geonode_extrude_profile` — sweep profile along curve path
  - `geonode_inspect` — read current GN setup and input values

- **Sculpting** (8 new tools — pipeline-focused, not brush strokes):
  - `sculpt_setup` — enter sculpt mode with multires/dyntopo/symmetry config
  - `sculpt_mesh_filter` — global mesh filters (SMOOTH, SHARPEN, INFLATE, etc.)
  - `sculpt_mask_by_topology` — mask by cavity/curvature/vertex group
  - `sculpt_face_set_create` — face sets by linked/material/normal/UV
  - `sculpt_multires_reshape` — manage multires levels
  - `sculpt_to_retopo` — full sculpt-to-retopo pipeline with displacement baking
  - `sculpt_extract_mask` — extract masked region as separate mesh
  - `sculpt_remesh_voxel` — voxel remesh with configurable resolution

- **Rigging & Armature** (8 new tools — with auto-rig presets):
  - `armature_create` — create armature from bone chain definitions
  - `autorig_preset` — one-call auto-rig (BIPED, VEHICLE, MECHANICAL_ARM, WHEEL_ASSEMBLY, TURRET, PISTON, LANDING_GEAR, etc.)
  - `constraint_add` — add bone/object constraints (IK, COPY_ROT, TRACK_TO, etc.)
  - `constraint_preset` — preset constraint setups (IK_ARM, PISTON_PAIR, WHEEL_SPIN, etc.)
  - `bone_shape_assign` — custom control shapes for bones
  - `pose_library_save` / `pose_library_apply` — save and restore poses with blending
  - `rig_validate` — validate rig for MIXAMO/UE5/MSFS export

- **Physics Simulation** (6 new tools):
  - `physics_rigid_body_add` — add rigid body with collision shape config
  - `physics_rigid_body_batch` — batch add rigid bodies to multiple objects
  - `physics_simulate` — run simulation with optional apply-to-mesh
  - `physics_cloth_add` — cloth with 7 presets (SILK, CANVAS, TARP, etc.) + wind
  - `physics_soft_body_add` — soft body for deformable objects
  - `physics_fluid_quick` — quick Mantaflow fluid setup

- **Annotations & Grease Pencil** (6 new tools):
  - `annotation_add` — 3D annotation strokes
  - `annotation_text` — text labels at 3D points
  - `annotation_dimension` — dimension lines with measurement display
  - `annotation_clear` — clear annotation layers
  - `grease_pencil_create` — create GP objects with strokes
  - `grease_pencil_markup` — overlay markup on rendered images

- **Collections & System** (8 new tools):
  - `collection_create`, `collection_list`, `collection_move`, `collection_visibility`
  - `undo`, `redo`, `save`, `save_as`

- GitHub issue templates (bug report, feature request)
- Pull request template with tool checklist

### Changed

- Total tool count increased from 155 to **218** (63 new tools across 9 categories)
- Updated test suite to cover new tool categories (84 tests passing)
- Added GitHub repo description and topics for discoverability

## [0.2.1] - 2025-02-06

### Added

- **AI Texture Generation (sync)**: `blender_ai_generate_texture_sync` — queues ComfyUI job and polls until complete in one call, eliminating the need for manual status polling
- **AI Output Evaluation**: `blender_ai_evaluate` — evaluate any render/output (model, texture, animation) using Ollama vision with category-specific scoring criteria
- **AI Self-Refinement**: `blender_ai_refine` — run one iteration of render → evaluate → suggest loop for iterative quality improvement
- Ollama Vision `evaluate_output()` method with structured scoring and category-specific criteria (model/texture/animation)
- `refine_with_feedback()` orchestration function for iterative self-refinement sessions
- Asset organization: `assets/generated/` directory for generated models and textures (gitignored)

### Changed

- Total tool count increased from 97 to 100
- Blend model files moved to `assets/generated/mototok/` and removed from git tracking
- Updated `.gitignore` to exclude generated assets and blend files

## [0.2.0] - 2025-02-05

### Added

- **AI Self-Refinement Loop** (7 new tools):
  - Script execution: `execute_script` — run arbitrary Python/bmesh code in Blender
  - Multi-angle rendering: `render_multi_angle` — render from front, right, top, perspective
  - Vision analysis: `analyze_viewport` — analyze renders with Ollama vision model
  - Refinement iteration: `refine_iteration` — render + analyze + convergence check
  - Session management: `refine_create_session`, `refine_get_session`, `refine_list_sessions`
- **Refinement session state management** module (`refinement.py`)
- **Ollama Vision** `analyze_for_refinement()` method for structured model feedback
- **TripoSR subprocess execution** — runs via system Python for PyTorch/CUDA support
- **Stable Fast 3D** backend for local image-to-3D generation
- **Multi-Backend AI 3D Generation System**:
  - Backend Management tools: list_backends, set_backend, get_backend_info, configure_backend
  - Enhanced Generation tools: generate_variations, cancel_generation, redo_generation
  - Mesh Processing tools: mesh_cleanup, mesh_decimate, mesh_remesh, mesh_optimize, auto_uv, fix_mesh_issues, mesh_stats
  - Queue Management tools: queue_list, queue_clear, get_history
- **Multi-backend support** for AI 3D generation:
  - Cloud backends: Hyper3D Rodin, Meshy.ai, Tripo AI
  - Local backends: TripoSR, Hunyuan3D 2.1, Stable Fast 3D
  - Helper backends: Ollama Vision (image understanding), ComfyUI (custom workflows)
- **Backend Manager** with automatic selection, fallback chains, and preference settings
- **Mesh Processing Pipeline** for generated models:
  - Cleanup (remove doubles, fix normals, delete loose geometry)
  - Decimate (collapse, unsubdiv, planar methods)
  - Remesh (voxel, quad, sharp methods)
  - Auto UV unwrap (smart project, lightmap, cube project)
  - Issue detection and fixing (non-manifold, zero-area faces, etc.)
- **Persistent Job Queue** with history tracking across Blender sessions
- Local-only generation mode (no API keys required when using local backends)

- **MSFS 2020/2024 Content Creation Tools** (20 tools):
  - LOD tools (4): create_lod_hierarchy, decimate_for_lod, setup_lod_distances, get_lod_info
  - Material tools (4): setup_material, create_glass_material, create_emissive_material, get_material_presets
  - Collision tools (4): create_collision_mesh, create_collision_box, create_collision_convex, tag_collision_type
  - Animation tools (4): add_animation_tag, setup_visibility_animation, configure_animation_loop, list_animation_tags
  - Export tools (4): export_model, validate_for_export, get_export_settings, batch_export_lods
- MSFS material type support (standard, windshield, clear_coat, glass, anisotropic, etc.)
- MSFS collision types (collider, road, water, trigger)
- Animation event tags for MSFS (sound, effect, visibility)
- glTF export with MSFS custom properties in extras
- MSFS_ROADMAP.md documentation

- **MSFS Aircraft Livery Tools** (18 tools):
  - Painting tools (7): setup_paint_mode, create_paint_layers, load_template_overlay, export_uv_layout, set_paint_brush, sample_color, get_paint_presets
  - Template tools (3): get_aircraft_templates, get_template_info, download_template
  - Transfer tools (4): analyze, transfer, extract_colors, map_elements
  - Export tools (4): export_textures, create_package, convert_to_dds, validate_package
- Aircraft template support for FlyByWire A32NX, Fenix A320, PMDG 737/777, iniBuilds A310/A320neo, Aerosoft CRJ, and more
- Paint layer presets for livery workflow (primer, base_color, cheatline, belly, details, decals, weathering, clearcoat)
- Brush presets for livery painting (soft_airbrush, hard_edge, detail_brush, smudge, clone, fill)
- AI-assisted livery analysis and transfer between aircraft
- MSFS livery package creation with manifest.json and layout.json
- DDS conversion support (requires texconv)

### Changed

- Version bump to 0.2.0
- Total tool count increased from 44 to 97
- TripoSR backend rewritten to use subprocess (avoids Blender Python limitations with PyTorch/CUDA)
- Simplified `compat.py` — removed redundant BSDF input branching
- `get_event_loop()` → `get_running_loop()` deprecation fix in `blender_client.py`
- Removed unused imports across multiple modules
- Refactored AI generation system to use pluggable backend architecture
- Enhanced `blender_ai_generate_model` with backend selection parameter
- Enhanced `blender_ai_model_status` with auto-import and mesh optimization options

## [0.1.0] - 2025-02-05

### Added

- Initial release of MCP Blender server
- **44 tools** for comprehensive Blender control:
  - Scene tools (5): info, new, clear, set_frame_range, get_version
  - Object tools (10): create, delete, list, get, transform, duplicate, join, separate, parent, select
  - Material tools (6): create, assign, set_color, set_principled, add_texture, list
  - Modifier tools (5): add, remove, apply, configure, list
  - Animation tools (7): keyframe_insert, keyframe_delete, keyframe_list, action_create, action_list, play, goto_frame
  - Render tools (5): image, animation, set_engine, set_resolution, screenshot
  - Export tools (5): gltf, fbx, obj, stl, import_file
  - External tools (4): polyhaven_search, polyhaven_download, ai_generate_model, ai_model_status
- Blender addon with socket server (TCP/JSON-RPC on port 9876)
- Version compatibility layer for Blender 4.2 LTS and 5.0
- Poly Haven integration for free HDRIs, textures, and 3D models
- Hyper3D Rodin integration for AI-based 3D model generation (text-to-3D and image-to-3D)
- Asset caching system for downloaded external assets
- Comprehensive test suite (41 unit tests, 31 integration tests)

### Technical Details

- MCP server communicates via stdio with Claude Code
- Async TCP client for Blender communication
- Non-blocking socket server using `bpy.app.timers`
- JSON-RPC 2.0 protocol for command communication

[0.2.1]: https://github.com/RFingAdam/mcp-blender/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/RFingAdam/mcp-blender/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/RFingAdam/mcp-blender/releases/tag/v0.1.0
