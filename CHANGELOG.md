# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
