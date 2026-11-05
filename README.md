<p align="center"><img src="https://raw.githubusercontent.com/RFingAdam/meshwire/main/assets/logo.svg" width="140" alt="Meshwire logo"></p>

# Meshwire

An independent MCP server for Blender. Control Blender from any MCP client, with tools for
modeling, materials, sculpting, animation, AI 3D generation, and Microsoft Flight Simulator content.

[![License](https://img.shields.io/badge/License-AGPL--3.0-1E40AF.svg)](https://github.com/RFingAdam/meshwire/blob/main/LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-3776AB.svg)](https://www.python.org/downloads/)
[![Blender 4.5 | 5.2 LTS](https://img.shields.io/badge/blender-4.5%20%7C%205.2%20LTS-F5792A.svg)](https://www.blender.org/)
[![MCP](https://img.shields.io/badge/MCP-server-A78BFA.svg)](https://modelcontextprotocol.io)

[Quick start](#quick-start) ·
[Tools](#tools) ·
[Self-refinement loop](#self-refinement-loop) ·
[Security](#security) ·
[Documentation](#documentation)

<!-- generated:status -->
> **Status:** every pull request runs each tool in real Blender 4.5 LTS and 5.2 LTS.
> **186 of 218 tools work on both.**
> 23 need what a headless test cannot provide, such as a GUI, an AI backend, or an earlier call.
> 9 have a known failure.
> Each list is under [Tools](#tools), and fixes are tracked in the [issues](https://github.com/RFingAdam/meshwire/issues).
<!-- /generated:status -->

---

## What is Meshwire?

Meshwire is an MCP server for AI clients such as Claude Desktop, Claude Code, and Codex CLI.
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
  Simulator. These tools now run in the test harness, but no generated package has been
  loaded in the sim yet, so treat their output as unproven until it has.
- **AI 3D generation:** text and image to 3D through Hyper3D Rodin, Meshy, Tripo, TripoSR,
  Stable Fast 3D, Hunyuan3D, and ComfyUI.
- **Self-refinement loop:** render an object from several angles, score it with an Ollama vision
  model, and iterate.
- **Poly Haven:** free HDRIs, textures, and models with no API key.

---

## Quick start

### 1. Run the MCP server

Meshwire is in alpha, so ask for pre-releases.
With [uv](https://docs.astral.sh/uv/) there is nothing to install up front:

```bash
uvx --prerelease allow meshwire --help
```

Or with pip:

```bash
pip install --pre meshwire
```

### 2. Install the Blender addon

Download `blender_mcp_addon-<version>.zip` from [Releases](https://github.com/RFingAdam/meshwire/releases),
or build it from source:

```bash
git clone https://github.com/RFingAdam/meshwire
cd meshwire
python scripts/package_addon.py
# creates dist/blender_mcp_addon-<version>.zip
```

In Blender, open **Edit > Preferences > Add-ons**, choose **Install from Disk** from the menu at
the top right, select the ZIP, and enable **Meshwire**.

### 3. Configure your MCP client

```json
{
  "mcpServers": {
    "blender": {
      "command": "uvx",
      "args": ["--prerelease", "allow", "meshwire"]
    }
  }
}
```

If you installed with pip, use `"command": "meshwire"` with no `args`.

### 4. Connect

1. In Blender's 3D viewport, press `N` and open the **Meshwire** tab.
2. Click **Start Server**.
3. Restart your MCP client. The Blender tools appear in its tool list.

Then try:

> Create a red cube at (2, 0, 0), add a subdivision surface modifier with 2 levels, and render
> it to /tmp/render.png.

---

## Tools

Each tool is run in headless Blender with valid input, with every value of each enum, and with no
arguments at all. A tool counts as working when every valid call succeeds or returns the error it
should. That does not prove the output is right, so a second test drives Blender through the real
socket and checks the result for core tools such as object creation, render, and bake. The
numbers below are generated from the test baselines by `scripts/tool_status.py`, and a test fails
if they drift. More detail per area is in
[`docs/tools.md`](https://github.com/RFingAdam/meshwire/blob/main/docs/tools.md).

<!-- generated:tools -->
| Area | Tools | Work on 4.5 | Work on 5.2 | Examples |
| --- | ---: | ---: | ---: | --- |
| Scene | 5 | 5 | 5 | `scene_info`, `scene_new` |
| Objects | 13 | 13 | 13 | `object_create`, `object_duplicate` |
| Mesh, curves, booleans | 38 | 35 | 35 | `mesh_bevel`, `curve_create` |
| Materials and nodes | 13 | 13 | 13 | `material_create`, `material_inspect_graph` |
| Modifiers | 5 | 5 | 5 | `modifier_add`, `modifier_apply` |
| Animation | 7 | 7 | 7 | `keyframe_delete`, `action_create` |
| Render | 6 | 5 | 5 | `render_image`, `render_multi_angle` |
| Import and export | 6 | 5 | 5 | `export_fbx`, `export_usd` |
| Measurement and validation | 7 | 7 | 7 | `measure_volume`, `measure_clearance` |
| Baking | 6 | 6 | 6 | `bake_pbr_batch`, `bake_from_multires` |
| Geometry nodes | 7 | 7 | 7 | `geonode_array_grid`, `geonode_extrude_profile` |
| Sculpting | 8 | 4 | 4 | `sculpt_setup`, `sculpt_remesh_voxel` |
| Rigging | 8 | 7 | 7 | `armature_create`, `autorig_preset` |
| Physics | 6 | 4 | 4 | `physics_rigid_body_add`, `physics_cloth_add` |
| Collections and session | 8 | 6 | 6 | `collection_create`, `save_as` |
| Annotations | 6 | 4 | 5 | `annotation_dimension`, `annotation_text` |
| MSFS content | 20 | 20 | 20 | `msfs_create_lod_hierarchy`, `msfs_setup_material` |
| MSFS livery | 18 | 15 | 15 | `msfs_livery_transfer`, `msfs_livery_create_package` |
| AI generation and refinement | 29 | 16 | 16 | `ai_evaluate`, `refine_iteration` |
| Poly Haven | 2 | 2 | 2 | `polyhaven_search`, `polyhaven_download` |
| **Total** | **218** | **186** | **187** |  |

<details><summary>9 tools with a known failure</summary>

| Tool | Fails on |
| --- | --- |
| `ai_auto_uv` | 4.5, 5.2 |
| `ai_mesh_decimate` | 4.5, 5.2 |
| `ai_pipeline_generate` | 4.5, 5.2 |
| `ai_texture_from_render` | 4.5, 5.2 |
| `constraint_add` | 4.5, 5.2 |
| `export_gltf` | 4.5, 5.2 |
| `grease_pencil_markup` | 4.5, 5.2 |
| `physics_fluid_quick` | 4.5, 5.2 |
| `physics_simulate` | 4.5, 5.2 |

Socket checks that still fail: `reply_16mb_complete`.

</details>

<details><summary>23 tools that cannot be checked headless</summary>

| Tool | Why |
| --- | --- |
| `ai_generate_model` | no AI backend is reachable offline |
| `ai_generate_model_sync` | no AI backend is reachable offline |
| `ai_generate_reference_image` | no AI backend is reachable offline |
| `ai_generate_texture` | no AI backend is reachable offline |
| `ai_generate_texture_sync` | no AI backend is reachable offline |
| `ai_inpaint_texture` | no AI backend is reachable offline |
| `ai_model_status` | needs a job id that only a live AI backend can issue |
| `ai_pipeline_status` | needs a pipeline id that only a live AI backend can issue |
| `annotation_add` | Blender 4.3 to 4.5 offers no Python call that creates an annotation stroke, so the tool says so; the socket test annotation_add_draws_or_says_why checks both outcomes |
| `mesh_edge_slide` | needs a 3D viewport; socket lane covers it |
| `mesh_knife_project` | needs a 3D viewport; socket lane covers it |
| `mesh_loop_cut` | needs a 3D viewport; socket lane covers it |
| `msfs_livery_convert_to_dds` | needs texconv from DirectXTex, which is not installed here |
| `msfs_livery_export_uv_layout` | the UV exporter draws on the GPU, which background mode lacks; the socket test checks it in a GUI |
| `msfs_livery_set_paint_brush` | needs texture paint mode from a prior msfs_livery_setup_paint_mode call, which a fresh-scene case cannot make; the socket test msfs_paint_brush_after_setup runs both |
| `redo` | Blender disables undo in background mode |
| `refine_get_session` | needs a session id from a prior refine_create_session call |
| `render_screenshot` | needs a 3D viewport; socket lane covers it |
| `sculpt_face_set_create` | face_sets_init crashes Blender in background mode, so it needs a 3D viewport; socket lane covers it |
| `sculpt_mask_by_topology` | the mask operators need a 3D viewport and crash Blender in background mode; socket lane covers it |
| `sculpt_mesh_filter` | needs a 3D viewport; socket lane covers it |
| `sculpt_multires_reshape` | the fixture mesh has no subdivision levels to rebuild or unsubdivide |
| `undo` | Blender disables undo in background mode |

</details>
<!-- /generated:tools -->

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

See [`docs/usage.md`](https://github.com/RFingAdam/meshwire/blob/main/docs/usage.md) for a walkthrough.

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
([#12](https://github.com/RFingAdam/meshwire/issues/12)).

---

## Configuration

```
meshwire [--host HOST] [--port PORT]

  --host HOST   Blender addon host (default: 127.0.0.1)
  --port PORT   Blender addon port (default: 9876)
```

The **Meshwire** tab in Blender's sidebar sets the socket port and starts or stops the server.

---

## Blender versions

Blender 4.5 LTS and 5.2 LTS are tested on every pull request. Blender 4.2 LTS is tested nightly on a
best-effort basis.

---

## Troubleshooting

**"Connection refused":** make sure Blender is running, the **Meshwire** tab shows the server
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

- **[Quick start](https://github.com/RFingAdam/meshwire/blob/main/docs/index.md):** install through first call.
- **[Tool reference](https://github.com/RFingAdam/meshwire/blob/main/docs/tools.md):** tools grouped by stage.
- **[Usage examples](https://github.com/RFingAdam/meshwire/blob/main/docs/usage.md):** self-refinement, MSFS, and livery walkthroughs.
- **[Architecture](https://github.com/RFingAdam/meshwire/blob/main/docs/architecture.md):** how the server and addon fit together.
- **[MSFS roadmap](https://github.com/RFingAdam/meshwire/blob/main/docs/MSFS_ROADMAP.md):** planned MSFS workflow.

---

## Development

```bash
git clone https://github.com/RFingAdam/meshwire
cd meshwire
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

Contributions are welcome. See [`CONTRIBUTING.md`](https://github.com/RFingAdam/meshwire/blob/main/CONTRIBUTING.md).

---

## License

[AGPL-3.0-or-later](https://github.com/RFingAdam/meshwire/blob/main/LICENSE).

## Trademarks

Meshwire is an independent project. It is not affiliated with, endorsed by, or sponsored by the
Blender Foundation, Microsoft, or Asobo Studio. Blender is a registered trademark of the Blender
Foundation. Microsoft Flight Simulator is a trademark of Microsoft Corporation. These names are used
only to say what Meshwire works with.

## Acknowledgments

- **[Blender Foundation](https://www.blender.org/)** for Blender.
- **[Poly Haven](https://polyhaven.com/)** for free 3D assets.
- **[Hyper3D Rodin](https://hyper3d.ai/)**, **[Meshy.ai](https://www.meshy.ai/)**,
  **[Tripo](https://www.tripo3d.ai/)**, **TripoSR**, **Stable Fast 3D**, **Hunyuan3D**, and
  **ComfyUI** for AI 3D backends.
- **The MCP working group** for the [Model Context Protocol](https://modelcontextprotocol.io).
