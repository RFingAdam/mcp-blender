# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
