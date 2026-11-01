# mcp-blender

Control Blender from any MCP client, with tools for modeling, materials, sculpting, animation,
AI 3D generation, and Microsoft Flight Simulator content.

[![License](https://img.shields.io/badge/License-AGPL--3.0-1E40AF.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-3776AB.svg)](https://www.python.org/downloads/)
[![Blender 4.5 | 5.2 LTS](https://img.shields.io/badge/blender-4.5%20%7C%205.2%20LTS-F5792A.svg)](https://www.blender.org/)
[![MCP](https://img.shields.io/badge/MCP-server-A78BFA.svg)](https://modelcontextprotocol.io)

[Quick start](#quick-start) ·
[Tools](#tools) ·
[Self-refinement loop](#self-refinement-loop) ·
[Security](#security) ·
[Documentation](#documentation)

> **Status, October 2026:** a full audit found that many tools fail in real Blender, including
> every MSFS tool, most bake tools, and a group of mesh tools. Fixes are landing now and are
> tracked in the [issues](https://github.com/RFingAdam/mcp-blender/issues). Treat those areas
> as not working until the next release.

---

## What is mcp-blender?

`mcp-blender` is an MCP server for AI clients such as Claude Desktop, Claude Code, and Codex CLI.
The server speaks the Model Context Protocol over stdio. A Blender addon listens on a local TCP
socket and runs each command on Blender's main thread through `bpy.app.timers`.

```
┌─────────────────┐    stdio     ┌─────────────────┐   TCP/JSON-RPC   ┌─────────────────┐
│  MCP client     │ ◄──────────► │   MCP Server    │ ◄──────────────► │  Blender Addon  │
│  (Claude / …)   │              │  (Python proc)  │   port 9876      │  (bpy.app.timers)│
└─────────────────┘              └─────────────────┘                  └─────────────────┘
```

- **Blender coverage:** scene, object, mesh, material, modifier, animation, render, export,
  baking, geometry nodes, sculpting, rigging, physics, and annotations.
- **MSFS content:** LOD, collision, material, animation, and livery tools for Microsoft Flight
  Simulator. This area is being rebuilt and does not work in the current release.
- **AI 3D generation:** text and image to 3D through Hyper3D Rodin, Meshy, Tripo, TripoSR,
  Stable Fast 3D, Hunyuan3D, and ComfyUI.
- **Self-refinement loop:** render an object from several angles, score it with an Ollama vision
  model, and iterate.
- **Poly Haven:** free HDRIs, textures, and models with no API key.

---

## Quick start

### 1. Run the MCP server

The `mcp-blender` package on PyPI is an unrelated project, so install this one from GitHub.
With [uv](https://docs.astral.sh/uv/) there is nothing to install up front:

```bash
uvx --from git+https://github.com/RFingAdam/mcp-blender mcp-blender --help
```

Or with pip:

```bash
pip install "mcp-blender @ git+https://github.com/RFingAdam/mcp-blender.git"
```

### 2. Install the Blender addon

Build the addon ZIP from source. Recent releases don't include one yet.

```bash
git clone https://github.com/RFingAdam/mcp-blender
cd mcp-blender
python scripts/package_addon.py
# creates dist/blender_mcp_addon-<version>.zip
```

In Blender, open **Edit > Preferences > Add-ons**, choose **Install from Disk** from the menu at
the top right, select the ZIP, and enable **MCP Server Addon**.

### 3. Configure your MCP client

```json
{
  "mcpServers": {
    "blender": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/RFingAdam/mcp-blender",
        "mcp-blender"
      ]
    }
  }
}
```

If you installed with pip, use `"command": "mcp-blender"` with no `args`.

### 4. Connect

1. In Blender's 3D viewport, press `N` and open the **MCP Server** tab.
2. Click **Start Server**.
3. Restart your MCP client. The Blender tools appear in its tool list.

Then try:

> Create a red cube at (2, 0, 0), add a subdivision surface modifier with 2 levels, and render
> it to /tmp/render.png.

---

## Tools

The server defines 218 tools. This table lists what exists, not what has been verified to work;
see the status note above. The tool list is in [`docs/tools.md`](docs/tools.md).

| Category                     | Tools | Examples                                                 |
| ---------------------------- | ----: | -------------------------------------------------------- |
| Scene                        |     5 | `scene_info`, `scene_new`, `scene_clear`                 |
| Objects                      |    12 | `object_create`, `object_duplicate`, `object_delete`     |
| Mesh, curves, booleans       |    35 | `mesh_bevel`, `mesh_bridge`, `curve_create`, `boolean_op` |
| Materials and nodes          |    13 | `material_create`, `material_inspect_graph`              |
| Modifiers                    |     5 | `modifier_add`, `modifier_configure`, `modifier_apply`   |
| Animation                    |     7 | `keyframe_delete`, `animation_play`, `action_create`     |
| Render                       |     6 | `render_image`, `render_multi_angle`, `render_screenshot` |
| Import and export            |     6 | `export_gltf`, `export_fbx`, `export_usd`                |
| Measurement and validation   |    10 | `measure_volume`, `measure_clearance`                    |
| Baking                       |     6 | `bake_pbr_batch`, `bake_curvature`                       |
| Geometry nodes               |     7 | `geonode_array_grid`, `geonode_extrude_profile`          |
| Sculpting                    |     8 | `sculpt_mesh_filter`, `sculpt_extract_mask`              |
| Rigging                      |     8 | `armature_create`, `autorig_preset`, `constraint_preset` |
| Physics                      |     6 | `physics_rigid_body_add`, `physics_cloth_add`            |
| Collections and session      |     9 | `collection_create`, `undo`, `redo`                      |
| Annotations                  |     6 | `annotation_dimension`, `grease_pencil_create`           |
| MSFS content                 |    20 | `msfs_create_lod_hierarchy`, `msfs_setup_material`       |
| MSFS livery                  |    18 | `msfs_livery_transfer`, `msfs_livery_create_package`     |
| AI generation and refinement |    29 | `ai_generate_model`, `ai_evaluate`, `refine_iteration`   |
| Poly Haven                   |     2 | `polyhaven_search`, `polyhaven_download`                 |

Every tool name takes a `blender_` prefix, for example `blender_scene_info`.

---

## Self-refinement loop

The agent writes mesh code, renders from several angles, an Ollama vision model scores the result,
and the agent applies fixes until the score stops improving.

```
┌───────────┐  execute_script  ┌─────────┐  render_multi_angle  ┌──────────────┐
│  agent    │ ──────────────► │ Blender  │ ───────────────────► │  PNG images  │
│  (LLM)    │                 │  (bpy)   │                      └──────┬───────┘
└─────┬─────┘                 └─────────┘                              │
      │                                                  analyze_viewport
      │  apply fix                                                     │
      │  (loop)                                                        ▼
      │                                                     ┌──────────────────┐
      └─────────────────────────────────────────────────────│  Ollama Vision   │
                              feedback + score              │ llama3.2-vision  │
                                                            └──────────────────┘
```

```python
# 1. Open a refinement session
blender_refine_create_session(object_name="Tree", prompt="A realistic low-poly pine tree")

# 2. Generate an initial mesh
blender_execute_script(script="import bmesh; ...")

# 3. Evaluate
blender_refine_iteration(object_name="Tree", iteration=0, max_iterations=5)

# 4. Apply fixes from the feedback, then evaluate again
blender_execute_script(script="# fix issues from analysis ...")
blender_refine_iteration(object_name="Tree", iteration=1, previous_score=0.6)

# 5. Inspect the session
blender_refine_get_session(session_id="...")
```

See [`docs/usage.md`](docs/usage.md) for a walkthrough.

---

## External integrations

### Poly Haven

[Poly Haven](https://polyhaven.com) provides free HDRIs, textures, and 3D models with no API key.
Downloads are cached locally.

```
blender_polyhaven_search(query="brick", asset_type="textures")
blender_polyhaven_download(asset_id="brick_wall_001", resolution="2k")
```

### AI 3D model generation

| Backend        | Type  | Requirements | Capabilities                          |
| -------------- | ----- | ------------ | ------------------------------------- |
| Hyper3D Rodin  | Cloud | API key      | Text-to-3D, Image-to-3D               |
| Meshy.ai       | Cloud | API key      | Text-to-3D, Image-to-3D, texturing    |
| Tripo AI       | Cloud | API key      | Text-to-3D, Image-to-3D               |
| TripoSR        | Local | 4 GB VRAM    | Image-to-3D                           |
| Stable Fast 3D | Local | 6 GB VRAM    | Image-to-3D                           |
| Hunyuan3D      | Local | 16 GB VRAM   | Text-to-3D, Image-to-3D               |
| ComfyUI        | Local | Varies       | Custom workflows                      |

Cloud setup:

```bash
export RODIN_API_KEY="your-rodin-key"
export MESHY_API_KEY="your-meshy-key"
export TRIPO_API_KEY="your-tripo-key"
```

Local setup:

```bash
# TripoSR is not on PyPI: clone it and put it on PYTHONPATH
git clone https://github.com/VAST-AI-Research/TripoSR
pip install -r TripoSR/requirements.txt
export PYTHONPATH="$PWD/TripoSR:$PYTHONPATH"

ollama pull llama3.2-vision:11b   # vision model for evaluation and refinement
```

Usage:

```
blender_ai_generate_model(prompt="a wooden chair", style="realistic")
blender_ai_generate_model(image_path="/path/to/image.png")
blender_ai_model_status(job_id="abc123", auto_import=true)
```

Styles: `realistic`, `cartoon`, `low_poly`, `sculpture`, `anime`.
Formats: `glb` (default), `gltf`, `fbx`, `obj`, `usdz`.

---

## Security

The addon's socket has no authentication yet, and `blender_execute_script` runs arbitrary Python
inside Blender. Any process on your machine that can reach the port can run code as you.

- Only start the server on a machine you trust, and stop it when you're done.
- Keep the host set to localhost. Don't bind it to `0.0.0.0` or expose port 9876.
- Don't run untrusted prompts or scripts against a Blender session with work you care about.

Authentication and a Python execution switch are planned for the next stable release
([#12](https://github.com/RFingAdam/mcp-blender/issues/12)).

---

## Configuration

```
mcp-blender [--host HOST] [--port PORT]

  --host HOST   Blender addon host (default: 127.0.0.1)
  --port PORT   Blender addon port (default: 9876)
```

The **MCP Server** tab in Blender's sidebar sets the socket port and starts or stops the server.

---

## Blender versions

Blender 4.5 LTS and 5.2 LTS are tested on every pull request. Blender 4.2 LTS is tested nightly on a
best-effort basis.

---

## Troubleshooting

**"Connection refused":** make sure Blender is running, the **MCP Server** tab shows the server
running, and the port matches.

**"Tool not found":** restart your MCP client after editing its config, confirm the server command
runs on its own with `--help`, and check the client's MCP log.

**Addon doesn't appear in Blender:** check Blender's system console for errors and try reinstalling
the ZIP.

**Poly Haven downloads fail:** check your connection, confirm the asset ID exists on polyhaven.com,
and check disk space.

**AI generation doesn't work:** `blender_ai_list_backends` shows backend status. Check your API keys
for cloud backends, or your models and VRAM for local ones. Follow a job with
`blender_ai_model_status`.

---

## Documentation

- **[Quick start](docs/index.md):** install through first call.
- **[Tool reference](docs/tools.md):** tools grouped by stage.
- **[Usage examples](docs/usage.md):** self-refinement, MSFS, and livery walkthroughs.
- **[Architecture](docs/architecture.md):** how the server and addon fit together.
- **[MSFS roadmap](docs/MSFS_ROADMAP.md):** planned MSFS workflow.

---

## Development

```bash
git clone https://github.com/RFingAdam/mcp-blender
cd mcp-blender
python -m venv .venv
source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

```bash
pytest tests/ --ignore=tests/blender_integration_test.py   # unit tests
python -m tests.harness.driver --help   # truth harness, needs Blender; see CONTRIBUTING.md
ruff check .
ruff format .
python scripts/package_addon.py   # builds the addon ZIP
```

Contributions are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## License

[AGPL-3.0-or-later](LICENSE).

## Trademarks

This project is not affiliated with, endorsed by, or sponsored by the Blender Foundation.
"Blender" is a trademark of the Blender Foundation, used here only to identify the software this
project works with.

## Acknowledgments

- **[Blender Foundation](https://www.blender.org/)** for Blender.
- **[Poly Haven](https://polyhaven.com/)** for free 3D assets.
- **[Hyper3D Rodin](https://hyper3d.ai/)**, **[Meshy.ai](https://www.meshy.ai/)**,
  **[Tripo](https://www.tripo3d.ai/)**, **TripoSR**, **Stable Fast 3D**, **Hunyuan3D**, and
  **ComfyUI** for AI 3D backends.
- **The MCP working group** for the [Model Context Protocol](https://modelcontextprotocol.io).
