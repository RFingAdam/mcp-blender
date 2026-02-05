# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

- Total tool count increased from 48 to 86

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

[Unreleased]: https://github.com/RFingAdam/mcp-blender/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/RFingAdam/mcp-blender/releases/tag/v0.1.0
