# MCP Blender

[![PyPI version](https://badge.fury.io/py/mcp-blender.svg)](https://badge.fury.io/py/mcp-blender)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Blender 4.2+](https://img.shields.io/badge/blender-4.2+-orange.svg)](https://www.blender.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Control Blender via the Model Context Protocol (MCP). This enables AI assistants like Claude to directly manipulate Blender scenes, create objects, apply materials, render images, and much more.

**Supports Blender 4.2 LTS and Blender 5.0**

## Features

- **86 tools** for comprehensive Blender control
- **Scene management** - Create, modify, and query scenes
- **Object manipulation** - Create primitives, transform, duplicate, join/separate
- **Materials & textures** - Create materials, set colors, configure Principled BSDF
- **Modifiers** - Add and configure 28+ modifier types
- **Animation** - Keyframes, actions, playback control
- **Rendering** - Render images/animations, configure engines
- **Import/Export** - glTF, FBX, OBJ, STL support
- **MSFS 2020/2024 content creation** - LOD systems, collision meshes, MSFS materials, animation events
- **MSFS aircraft livery tools** - Paint workflows, template support, AI-assisted livery transfer
- **Poly Haven integration** - Search and download free HDRIs, textures, and models
- **AI model generation** - Generate 3D models from text or images via Hyper3D Rodin

## Architecture

```
┌─────────────────┐     stdio      ┌─────────────────┐     TCP/JSON-RPC     ┌─────────────────┐
│   Claude Code   │ ◄────────────► │   MCP Server    │ ◄─────────────────► │  Blender Addon  │
│   (AI Client)   │                │  (Python proc)  │      port 9876       │ (socket server) │
└─────────────────┘                └─────────────────┘                      └─────────────────┘
```

The MCP server communicates with Claude Code via stdio and connects to a Blender addon via TCP sockets. The addon runs a non-blocking server inside Blender using `bpy.app.timers`.

## Installation

### 1. Install the MCP Server

```bash
pip install mcp-blender
```

Or install from source:

```bash
git clone https://github.com/yourusername/mcp-blender
cd mcp-blender
pip install -e .
```

### 2. Install the Blender Addon

**Option A: From ZIP (recommended)**

1. Download `blender_mcp_addon.zip` from the [releases page](https://github.com/yourusername/mcp-blender/releases)
2. In Blender: **Edit → Preferences → Add-ons → Install...**
3. Select the ZIP file and click "Install Add-on"
4. Enable "MCP Server Addon" by checking the box

**Option B: From source (for development)**

Copy or symlink the addon folder to your Blender addons directory:

```bash
# Linux
ln -s /path/to/mcp-blender/addon/blender_mcp_addon ~/.config/blender/4.2/scripts/addons/

# macOS
ln -s /path/to/mcp-blender/addon/blender_mcp_addon ~/Library/Application\ Support/Blender/4.2/scripts/addons/

# Windows (run as administrator)
mklink /D "%APPDATA%\Blender Foundation\Blender\4.2\scripts\addons\blender_mcp_addon" "C:\path\to\mcp-blender\addon\blender_mcp_addon"
```

Then enable the addon in Blender preferences.

### 3. Configure Claude Code

Add to your Claude Code MCP settings (`~/.claude.json` or `~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "blender": {
      "command": "mcp-blender",
      "args": ["--port", "9876"]
    }
  }
}
```

## Quick Start

1. **Start Blender** and open any project
2. In the 3D Viewport sidebar (press `N`), find the **"MCP Server"** panel
3. Click **"Start Server"** - you should see "Server running on port 9876"
4. **Start Claude Code** - the Blender tools should now be available

### Example Commands

Ask Claude to:

- *"Create a red cube at position (2, 0, 0)"*
- *"Add a subdivision surface modifier to the cube with 2 levels"*
- *"Set up a three-point lighting setup"*
- *"Render the scene to /tmp/render.png"*
- *"Search Poly Haven for brick textures and apply one to the cube"*

## Tools Reference

### Scene Tools (5)

| Tool | Description |
|------|-------------|
| `blender_scene_info` | Get scene name, frame range, object count, render settings |
| `blender_scene_new` | Create a new scene |
| `blender_scene_clear` | Remove all objects from the scene |
| `blender_scene_set_frame_range` | Set animation start/end frames |
| `blender_get_version` | Get Blender version and API info |

### Object Tools (10)

| Tool | Description |
|------|-------------|
| `blender_object_create` | Create primitives: cube, sphere, cylinder, plane, cone, torus, monkey, empty, camera, light |
| `blender_object_delete` | Delete object by name |
| `blender_object_list` | List all objects with types and visibility |
| `blender_object_get` | Get detailed object properties |
| `blender_object_transform` | Set location, rotation, and scale |
| `blender_object_duplicate` | Duplicate an object |
| `blender_object_join` | Join multiple objects into one |
| `blender_object_separate` | Separate object by loose parts, materials, or selection |
| `blender_object_parent` | Set parent-child relationships |
| `blender_object_select` | Select objects by name or pattern |

### Material Tools (6)

| Tool | Description |
|------|-------------|
| `blender_material_create` | Create a new material |
| `blender_material_assign` | Assign material to object |
| `blender_material_set_color` | Set base color (RGBA) |
| `blender_material_set_principled` | Configure Principled BSDF (metallic, roughness, etc.) |
| `blender_material_add_texture` | Add image texture to material |
| `blender_material_list` | List all materials |

### Modifier Tools (5)

| Tool | Description |
|------|-------------|
| `blender_modifier_add` | Add modifier (28+ types supported) |
| `blender_modifier_remove` | Remove modifier by name |
| `blender_modifier_apply` | Apply modifier to mesh |
| `blender_modifier_configure` | Set modifier parameters |
| `blender_modifier_list` | List modifiers on an object |

**Supported modifiers:** SUBSURF, BEVEL, SOLIDIFY, ARRAY, MIRROR, BOOLEAN, DECIMATE, REMESH, SMOOTH, LAPLACIANSMOOTH, TRIANGULATE, WIREFRAME, SKIN, ARMATURE, LATTICE, CURVE, SHRINKWRAP, SIMPLE_DEFORM, WAVE, DISPLACE, CAST, HOOK, MESH_DEFORM, SURFACE_DEFORM, WARP, LAPLACIANDEFORM, CORRECTIVE_SMOOTH, DATA_TRANSFER

### Animation Tools (7)

| Tool | Description |
|------|-------------|
| `blender_keyframe_insert` | Insert keyframe for property |
| `blender_keyframe_delete` | Delete keyframe |
| `blender_keyframe_list` | List keyframes on an object |
| `blender_action_create` | Create a new action |
| `blender_action_list` | List all actions |
| `blender_animation_play` | Play or pause animation |
| `blender_animation_goto_frame` | Jump to specific frame |

### Render Tools (5)

| Tool | Description |
|------|-------------|
| `blender_render_image` | Render current frame to file |
| `blender_render_animation` | Render animation sequence |
| `blender_render_set_engine` | Set render engine (CYCLES, BLENDER_EEVEE_NEXT, BLENDER_WORKBENCH) |
| `blender_render_set_resolution` | Set output resolution |
| `blender_render_screenshot` | Capture viewport screenshot |

### Export/Import Tools (5)

| Tool | Description |
|------|-------------|
| `blender_export_gltf` | Export to glTF/GLB format |
| `blender_export_fbx` | Export to FBX format |
| `blender_export_obj` | Export to OBJ format |
| `blender_export_stl` | Export to STL format |
| `blender_import_file` | Import file (auto-detects format) |

### External Integration Tools (4)

| Tool | Description |
|------|-------------|
| `blender_polyhaven_search` | Search Poly Haven for HDRIs, textures, or models |
| `blender_polyhaven_download` | Download and apply Poly Haven asset |
| `blender_ai_generate_model` | Generate 3D model from text or image (Hyper3D Rodin) |
| `blender_ai_model_status` | Check AI generation job status |

### MSFS 2020/2024 Content Creation Tools (20)

Tools for creating Microsoft Flight Simulator compatible content.

| Tool | Description |
|------|-------------|
| `blender_msfs_create_lod_hierarchy` | Create LOD hierarchy from base mesh |
| `blender_msfs_decimate_for_lod` | Decimate mesh to target ratio |
| `blender_msfs_setup_lod_distances` | Configure LOD switch distances |
| `blender_msfs_get_lod_info` | Get LOD hierarchy information |
| `blender_msfs_setup_material` | Set up MSFS-specific material |
| `blender_msfs_create_glass_material` | Create glass/windshield material |
| `blender_msfs_create_emissive_material` | Create emissive/light material |
| `blender_msfs_get_material_presets` | List available material presets |
| `blender_msfs_create_collision_mesh` | Create simplified collision mesh |
| `blender_msfs_create_collision_box` | Create box collision primitive |
| `blender_msfs_create_collision_convex` | Create convex hull collision |
| `blender_msfs_tag_collision_type` | Tag mesh as collision object |
| `blender_msfs_add_animation_tag` | Add animation event marker |
| `blender_msfs_setup_visibility_animation` | Configure show/hide animation |
| `blender_msfs_configure_animation_loop` | Set loop behavior |
| `blender_msfs_list_animation_tags` | List all animation tags |
| `blender_msfs_export_model` | Export with LODs, collision, animations |
| `blender_msfs_validate_for_export` | Validate for MSFS compatibility |
| `blender_msfs_get_export_settings` | Get export settings |
| `blender_msfs_batch_export_lods` | Batch export LOD hierarchy |

See [MSFS_ROADMAP.md](docs/MSFS_ROADMAP.md) for detailed MSFS workflow documentation.

### MSFS Aircraft Livery Tools (18)

Tools for creating and transferring aircraft liveries for virtual airlines.

| Tool | Description |
|------|-------------|
| `blender_msfs_livery_setup_paint_mode` | Set up object for texture painting |
| `blender_msfs_livery_create_paint_layers` | Create paint layers (primer, base, cheatline, etc.) |
| `blender_msfs_livery_load_template_overlay` | Load reference template as overlay |
| `blender_msfs_livery_export_uv_layout` | Export UV layout for external painting |
| `blender_msfs_livery_set_paint_brush` | Configure brush presets (airbrush, hard edge, etc.) |
| `blender_msfs_livery_sample_color` | Sample color from reference image |
| `blender_msfs_livery_get_paint_presets` | Get available paint layer and brush presets |
| `blender_msfs_livery_get_aircraft_templates` | List supported aircraft (FBW, Fenix, PMDG, etc.) |
| `blender_msfs_livery_get_template_info` | Get detailed template info for aircraft |
| `blender_msfs_livery_download_template` | Download/generate aircraft templates |
| `blender_msfs_livery_analyze` | Analyze livery image for colors and elements |
| `blender_msfs_livery_transfer` | Transfer livery between aircraft types |
| `blender_msfs_livery_extract_colors` | Extract color palette from livery |
| `blender_msfs_livery_map_elements` | Map design elements between templates |
| `blender_msfs_livery_export_textures` | Export livery textures (PNG, TGA) |
| `blender_msfs_livery_create_package` | Create MSFS livery package structure |
| `blender_msfs_livery_convert_to_dds` | Convert textures to DDS format |
| `blender_msfs_livery_validate_package` | Validate livery package for MSFS |

**Supported Aircraft:**
- FlyByWire A32NX (freeware)
- Fenix A320/A319/A321
- PMDG 737/777
- iniBuilds A310/A320neo
- Aerosoft CRJ
- Just Flight BAe 146
- Generic template for custom aircraft

## External Integrations

### Poly Haven

[Poly Haven](https://polyhaven.com) provides free HDRIs, textures, and 3D models. No API key required.

```
# Search for assets
blender_polyhaven_search(query="brick", asset_type="textures")

# Download and apply
blender_polyhaven_download(asset_id="brick_wall_001", resolution="2k")
```

Assets are cached locally to avoid re-downloading.

### Hyper3D Rodin (AI Model Generation)

Generate 3D models from text prompts or images using [Hyper3D Rodin](https://hyperhuman.deemos.com).

**Setup:** Set your API key as an environment variable:

```bash
export RODIN_API_KEY="your-api-key-here"
```

**Usage:**

```
# Text-to-3D
blender_ai_generate_model(prompt="a wooden chair", style="realistic", quality="medium")

# Image-to-3D
blender_ai_generate_model(image_path="/path/to/image.png")

# Check status and import when ready
blender_ai_model_status(job_id="abc123", auto_import=true)
```

**Supported styles:** realistic, cartoon, low_poly, sculpture, anime

**Supported formats:** glb (default), gltf, fbx, obj, usdz

## Version Compatibility

This addon includes a compatibility layer for Blender API differences:

| Feature | Blender 4.2 | Blender 5.0 |
|---------|-------------|-------------|
| Action FCurves | `action.fcurves` | `action.slots[].layers[].strips[].channels` |
| mathutils precision | float64 | float32 |
| Render engine | `BLENDER_EEVEE` | `BLENDER_EEVEE_NEXT` |

The compatibility layer handles these differences automatically.

## Configuration Options

### MCP Server

```bash
mcp-blender --help

Options:
  --host TEXT   Blender addon host [default: localhost]
  --port INT    Blender addon port [default: 9876]
```

### Blender Addon

The addon panel in the 3D Viewport sidebar offers:

- **Port:** TCP port for the socket server (default: 9876)
- **Start/Stop Server:** Toggle the MCP socket server

## Troubleshooting

### "Connection refused" errors

1. Make sure Blender is running
2. Check the MCP Server panel shows "Server running"
3. Verify the port matches (default: 9876)
4. Check firewall settings if running on different machines

### "Tool not found" errors

1. Restart Claude Code after adding the MCP server config
2. Verify `mcp-blender` is installed: `mcp-blender --help`
3. Check Claude Code's MCP server logs

### Addon not appearing in Blender

1. Check Blender's console for errors (Window → Toggle System Console on Windows)
2. Verify Python version compatibility (Blender 4.2+ uses Python 3.11+)
3. Try reinstalling the addon

### Poly Haven downloads fail

1. Check internet connectivity
2. Verify the asset ID exists on polyhaven.com
3. Check disk space for cache directory

### AI generation not working

1. Verify `RODIN_API_KEY` environment variable is set
2. Check API key validity at hyperhuman.deemos.com
3. Monitor job status with `blender_ai_model_status`

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/yourusername/mcp-blender
cd mcp-blender

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install with dev dependencies
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run unit tests (no Blender required)
pytest tests/ --ignore=tests/blender_integration_test.py

# Run Blender integration tests
blender --background --python tests/blender_integration_test.py
```

### Linting

```bash
ruff check .
ruff format .
```

### Building the Addon ZIP

```bash
python scripts/package_addon.py
# Creates dist/blender_mcp_addon-<version>.zip
```

### Project Structure

```
mcp-blender/
├── src/mcp_blender/           # MCP server package
│   ├── server.py              # Tool definitions and MCP handlers
│   ├── blender_client.py      # TCP client for Blender communication
│   └── types.py               # Shared type definitions
├── addon/blender_mcp_addon/   # Blender addon
│   ├── __init__.py            # Addon registration and UI
│   ├── socket_server.py       # TCP server using bpy.app.timers
│   ├── handlers.py            # Command handlers
│   ├── compat.py              # Version compatibility layer
│   ├── validation.py          # Parameter validation
│   ├── external/              # External integrations
│   │   ├── cache.py           # Asset caching system
│   │   ├── polyhaven.py       # Poly Haven API client
│   │   └── ai_models.py       # Hyper3D Rodin integration
│   └── msfs/                  # MSFS content creation tools
│       ├── lod.py             # LOD hierarchy management
│       ├── materials.py       # MSFS material extensions
│       ├── collision.py       # Collision mesh tools
│       ├── animation.py       # Animation tags and events
│       ├── export.py          # MSFS export utilities
│       └── livery/            # Aircraft livery tools
│           ├── painting.py    # Texture painting workflow
│           ├── templates.py   # Aircraft template definitions
│           ├── transfer.py    # AI-assisted livery transfer
│           └── export.py      # Livery package creation
├── tests/                     # Test suite
├── scripts/                   # Build scripts
└── docs/                      # Documentation
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- [Model Context Protocol](https://modelcontextprotocol.io/) by Anthropic
- [Blender](https://www.blender.org/) by the Blender Foundation
- [Poly Haven](https://polyhaven.com/) for free 3D assets
- [Hyper3D Rodin](https://hyperhuman.deemos.com/) for AI model generation
