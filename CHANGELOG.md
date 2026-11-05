# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **`mesh_select` combines criteria with AND** (#38). Several criteria used to be unioned, so a
  second criterion could only add elements. An element now has to match every criterion given; a
  criterion that does not apply to the mode is ignored. The tool description says so.
- **Mesh tools use Blender's real identifiers.** `mesh_subdivide` maps `INNERVERT` to the
  `INNER_VERT` that `bmesh.ops.subdivide_edges` takes. `mesh_edge_slide` passes `use_even`, not
  `even`, and returns "needs an open 3D viewport" in background mode, where the slide operator
  crashes Blender 4.5. `mesh_crease` writes the `crease_edge` attribute, since
  `BMLayerAccessEdge.crease` is gone. `curve_to_mesh` no longer lists `fill_type` `NONE`, which
  Blender rejects for 3D curves; a 2D curve still accepts it.
- **Each successful tool call is one undo step in the GUI.** Operators called from the socket
  timer push no undo step, so `undo` reverted nothing or too much. `CommandHandlers.handle` now
  calls `bpy.ops.ed.undo_push(message=<tool>)` after a tool that does not report an error or
  `success: false`, after any rename the tool made. Read-only tools (`NON_MUTATING`), `undo`,
  `redo` and `ping` never push, so redo keeps working. `execute_script` no longer pushes a step
  of its own before running, which left an extra no-op step. Background mode has undo disabled
  and is unchanged.
- **Viewport-only tools no longer crash Blender, and work in a GUI session (closes #37).**
  `mesh_loop_cut`, `mesh_knife_project`, `sculpt_mesh_filter`, `sculpt_mask_by_topology`
  (`ALL`, `NONE` and `invert`) and `render_screenshot` call operators that need a 3D viewport.
  In background mode they segfaulted or raised. They now find a viewport by walking the window
  manager, because the socket server runs handlers from a timer where `bpy.context.area` is
  None, and run the operator under `temp_override`. With no viewport they return
  `{"success": false, "error": "<tool> needs an open 3D viewport"}`. `sculpt_mesh_filter` maps
  `ENHANCE_DETAIL` to Blender's `ENHANCE_DETAILS` and `SURFACE_NOISE` to `RANDOM`.
  `mesh_knife_project` lost its boolean INTERSECT fallback, which deleted everything outside
  the cutter, and now selects the cutter after entering Edit mode so the operator sees it.
  Mesh tools that enter Edit mode (`mesh_loop_cut`, `mesh_bridge`, `mesh_fill`,
  `mesh_edge_slide`, `mesh_knife_project`, `mesh_separate_selected`,
  `mesh_select_shortest_path`, `mesh_select_edge_loops`) return to Object mode when they fail.

- **Missing arguments are rejected with a validation error, and `~` paths work.** Sixteen
  tools (`object_create`, `object_delete`, `object_get`, `object_transform`,
  `object_duplicate`, `object_join`, `object_separate`, `object_parent`,
  `material_set_principled`, `material_add_texture`, `render_animation`,
  `render_screenshot`, `render_set_engine`, `render_set_resolution`, `polyhaven_download`,
  `ai_model_status`) and `ai_pipeline_status` raised a bare `KeyError` or accepted `{}`.
  They now report the missing parameter through `require_param`. `validate_filepath` returns
  the absolute path with `~` expanded, checks existence after expansion and leaves Blender
  `//` paths alone. `ai_inpaint_texture` and `reference_image_setup` called it without a
  `name` or discarded the result; a static gate now catches an unused result.

- **Five of the six baking tools never worked.** `bake_pbr_batch`, `bake_highpoly_to_lowpoly`,
  `bake_from_multires`, `bake_to_vertex_colors` and `bake_id_map` called eight `_bake_*`
  helpers that were never written, so each raised `AttributeError` once past argument
  checks. The helpers now exist. The target image node and the emission wiring that
  `METALLIC` and `DISPLACEMENT` bake through are tracked as they are added and removed
  in a `finally`, including when the bake raises. A material is left with the same
  nodes, links, socket values, selection, active node and active Material Output
  (including a Cycles-only output) it had; this is checked on a linked and an unlinked
  Metallic socket, a displacement chain, a shared material and a multi-slot object, on
  Blender 4.2, 4.5 and 5.2. The render engine, the bake settings and the object
  selection are also put back after each bake, which they were not. A setting that cannot be
  put back, such as an add-on render engine that is no longer installed, is named in
  `warnings`. `bake_id_map` now
  restores material slots and face material indices in every colour mode. An object
  with no node material gets a clear error from `bake_pbr_batch`; the other tools add a
  temporary material and remove it again. A bake that writes no file, including
  `channels: []`, returns an error rather than `success`, and empty material slots are
  named in a `warnings` entry. `bake_from_multires` called an operator that rejects its
  map types; it now uses the multires baker, and bakes to level 0 when the modifier is
  at its top level, since a level baked to itself carries no displacement.
  `bake_highpoly_to_lowpoly` now lists the `normal_space` parameter it already read.
  `bake_curvature` never called the helpers and is unchanged.
- **All 38 `msfs_*` tools failed on every call.** `handlers/msfs.py` imported
  `from .msfs`, which resolves to the handler module itself, so each call raised an
  ImportError or "not a package". It now imports the `msfs` package. These tools
  now run; their output is not yet verified. Five more defects behind the import:
  `msfs_create_glass_material` set `Material.shadow_method`, absent from Blender
  4.5 and later; `msfs_export_model` passed the removed `export_colors` option and
  the format `GLTF`, which the exporter spells `GLTF_SEPARATE`;
  `msfs_livery_extract_colors`, `msfs_livery_transfer` and
  `msfs_livery_map_elements` did not accept the parameters their schemas offer;
  and `msfs_livery_export_uv_layout` now says it needs a GPU context in background
  mode instead of raising, and no longer leaves the object in Edit mode.
- **`ai_auto_uv` read freed memory.** It held a UV layer reference across a mode change, then
  read its name. The outcome depended on what was left in that memory: it crashed Blender 5.2
  every time and failed unpredictably on 4.5.
- **`validate_enum()` called with swapped arguments in 20 handlers.** Every
  affected handler rejected all of its documented enum values, because the
  `allowed` list landed in the `name` slot and the parameter-name string landed
  in `allowed`, so iterating a `str` made the check compare against its individual
  characters. `mesh_fill`, `curve_create`, `curve_to_mesh`, `mesh_extrude`,
  `mesh_select`, `mesh_select_shortest_path` and others were unusable as a
  result, and the error messages they raised named the wrong parameter.
- **`import_file` could not import `.stl`.** It called `bpy.ops.import_mesh.stl`,
  which Blender 4.x removed; now uses `bpy.ops.wm.stl_import`, matching the
  `wm.stl_export` already used on the export side.
- **`render_set_engine` failed on Blender 5.x.** `compat.get_eevee_engine_name()`
  hard-coded `BLENDER_EEVEE_NEXT` for 4.2+, but 5.0 renamed the engine back to
  `BLENDER_EEVEE`. It now queries the `engine` enum instead of mapping from the
  version number.

Thanks to Muhammet Ali (`muhammetali`) for this fix.

### Added

- `tests/test_handler_signatures.py`: Blender-free static checks that guard
  against `validate_enum` argument-order regressions and against calling
  Blender operators removed in 4.x.
- Integration tests for the STL export/import round-trip and for `mesh_fill`
  enum handling.

## [0.5.0a1] - 2026-11-01

First release on PyPI, as `meshwire`. This is an alpha: many tools still fail in real Blender, and
the socket has no authentication yet. See the README status note.

### Added
- A truth harness that runs every tool in real headless Blender on every PR and fails on any
  unrecorded change. See the Truth harness section of `CONTRIBUTING.md`.
- `meshwire --version`.
- A release workflow that publishes to PyPI and attaches the addon ZIP to the GitHub release.

### Changed
- One version for the whole project, in `src/mcp_blender/__init__.py`. It was four different
  numbers in different files.
- Renamed the project to Meshwire. Blender's trademark policy asks third parties not to use its
  name in product names, and an original name makes clear this is not an official Blender project.
  Old GitHub URLs redirect. The `mcp-blender` command still works as an alias for `meshwire`.
  Python module names are unchanged for now.
- Added a new logo. It is original artwork and uses nothing from the Blender logo.

## [0.4.0]: 2026-05-13

### Changed
- **License: MIT to AGPL-3.0-or-later.**

## [0.3.0] - 2026-03-25

### Added

- **Material Inspection & Manipulation** (7 new tools):
  - `material_inspect_graph`: return full shader node graph as structured JSON
  - `material_node_add`: add any shader node to a material
  - `material_node_connect`: connect nodes via socket names
  - `material_node_group_create`: create reusable node groups
  - `material_procedural_preset`: 23 one-call procedural materials (VEHICLE_PAINT, CHROME, RUST, CARBON_FIBER, etc.)
  - `material_convert_to_pbr`: convert materials to clean Principled BSDF for GLTF/MSFS/UE5
  - `material_preview_render`: render material preview on standard shape

- **Measurement & Validation** (7 new tools):
  - `measure_surface_area`: total + per-material area breakdown
  - `measure_volume`: mesh volume with manifold check
  - `measure_clearance`: min/max/avg distance between two objects
  - `validate_dimensions`. Check dimensions against spec with tolerance
  - `calibrate_from_reference`: scale object to match known real-world dimension
  - `measure_edge_angle`: dihedral angles at edges with threshold flagging
  - `validate_mesh_quality`: 11-check comprehensive mesh quality audit

- **Baking** (6 new tools):
  - `bake_pbr_batch`: bake ALL PBR channels (diffuse, normal, roughness, metallic, AO, emission, displacement) in one call
  - `bake_highpoly_to_lowpoly`: selected-to-active baking
  - `bake_from_multires`: bake from multires sculpt data
  - `bake_to_vertex_colors`: bake lighting/AO to vertex colors
  - `bake_curvature`: curvature map for wear/edge effects
  - `bake_id_map`: color ID map per material/object/face_set

- **Geometry Nodes** (7 new tools: first-ever GN support via MCP):
  - `geonode_create_group`: create typed node group with inputs/outputs
  - `geonode_apply`: apply GN group as modifier with input values
  - `geonode_scatter_instances`. One-call scatter with Poisson, density, random scale/rotation
  - `geonode_array_grid`: parametric arrays (linear, grid, radial, hexagonal)
  - `geonode_deform_curve`: deform mesh along curve
  - `geonode_extrude_profile`: sweep profile along curve path
  - `geonode_inspect`: read current GN setup and input values

- **Sculpting** (8 new tools: pipeline-focused, not brush strokes):
  - `sculpt_setup`: enter sculpt mode with multires/dyntopo/symmetry config
  - `sculpt_mesh_filter`: global mesh filters (SMOOTH, SHARPEN, INFLATE, etc.)
  - `sculpt_mask_by_topology`: mask by cavity/curvature/vertex group
  - `sculpt_face_set_create`: face sets by linked/material/normal/UV
  - `sculpt_multires_reshape`: manage multires levels
  - `sculpt_to_retopo`: full sculpt-to-retopo pipeline with displacement baking
  - `sculpt_extract_mask`: extract masked region as separate mesh
  - `sculpt_remesh_voxel`: voxel remesh with configurable resolution

- **Rigging & Armature** (8 new tools: with auto-rig presets):
  - `armature_create`: create armature from bone chain definitions
  - `autorig_preset`. One-call auto-rig (BIPED, VEHICLE, MECHANICAL_ARM, WHEEL_ASSEMBLY, TURRET, PISTON, LANDING_GEAR, etc.)
  - `constraint_add`: add bone/object constraints (IK, COPY_ROT, TRACK_TO, etc.)
  - `constraint_preset`: preset constraint setups (IK_ARM, PISTON_PAIR, WHEEL_SPIN, etc.)
  - `bone_shape_assign`: custom control shapes for bones
  - `pose_library_save` / `pose_library_apply`: save and restore poses with blending
  - `rig_validate`: validate rig for MIXAMO/UE5/MSFS export

- **Physics Simulation** (6 new tools):
  - `physics_rigid_body_add`: add rigid body with collision shape config
  - `physics_rigid_body_batch`: batch add rigid bodies to multiple objects
  - `physics_simulate`. Run simulation with optional apply-to-mesh
  - `physics_cloth_add`: cloth with 7 presets (SILK, CANVAS, TARP, etc.) + wind
  - `physics_soft_body_add`: soft body for deformable objects
  - `physics_fluid_quick`: quick Mantaflow fluid setup

- **Annotations & Grease Pencil** (6 new tools):
  - `annotation_add`: 3D annotation strokes
  - `annotation_text`: text labels at 3D points
  - `annotation_dimension`: dimension lines with measurement display
  - `annotation_clear`: clear annotation layers
  - `grease_pencil_create`: create GP objects with strokes
  - `grease_pencil_markup`: overlay markup on rendered images

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

- **AI Texture Generation (sync)**: `blender_ai_generate_texture_sync`: queues ComfyUI job and polls until complete in one call, eliminating the need for manual status polling
- **AI Output Evaluation**: `blender_ai_evaluate`: evaluate any render/output (model, texture, animation) using Ollama vision with category-specific scoring criteria
- **AI Self-Refinement**: `blender_ai_refine`. Run one iteration of render → evaluate → suggest loop for iterative quality improvement
- Ollama Vision `evaluate_output()` method with structured scoring and category-specific criteria (model/texture/animation)
- `refine_with_feedback()` orchestration function for iterative self-refinement sessions
- Asset organization: `assets/generated/` directory for generated models and textures (gitignored)

### Changed

- Total tool count increased from 97 to 100
- Blend model files removed from git tracking
- Updated `.gitignore` to exclude generated assets and blend files

## [0.2.0] - 2025-02-05

### Added

- **AI Self-Refinement Loop** (7 new tools):
  - Script execution: `execute_script`. Run arbitrary Python/bmesh code in Blender
  - Multi-angle rendering: `render_multi_angle`: render from front, right, top, perspective
  - Vision analysis: `analyze_viewport`: analyze renders with Ollama vision model
  - Refinement iteration: `refine_iteration`: render + analyze + convergence check
  - Session management: `refine_create_session`, `refine_get_session`, `refine_list_sessions`
- **Refinement session state management** module (`refinement.py`)
- **Ollama Vision** `analyze_for_refinement()` method for structured model feedback
- **TripoSR subprocess execution**: runs via system Python for PyTorch/CUDA support
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
- Simplified `compat.py`: removed redundant BSDF input branching
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

[0.5.0a1]: https://github.com/RFingAdam/meshwire/releases/tag/v0.5.0a1
[0.2.1]: https://github.com/RFingAdam/meshwire/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/RFingAdam/meshwire/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/RFingAdam/meshwire/releases/tag/v0.1.0
