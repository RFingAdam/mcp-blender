# meshwire

**Control Blender from any MCP client: 218 tools across modeling, materials, sculpting, animation, AI 3D generation, and MSFS content creation.**
**Drive it from your IDE, terminal, or AI agent and run an iterative render-analyze-refine loop without leaving Blender.**

---

## What it is

`meshwire` exposes 218 Blender tools via the Model Context Protocol.
The MCP server speaks stdio; a Blender addon listens on local TCP and
dispatches into `bpy` on the main thread via `bpy.app.timers`. Supports
every Blender series from 4.2 through 5.2, and 4.2 is the minimum. **Blender 4.5 LTS** and
**Blender 5.2 LTS** are gated on every PR. Blender 4.2, 4.3, 4.4, 5.0 and 5.1 are tested nightly,
best effort.

## Install

Meshwire is in alpha, so ask for pre-releases.

```bash
pip install --pre meshwire
```

Then install the Blender addon from
[`addon/blender_mcp_addon/`](https://github.com/RFingAdam/meshwire/tree/main/addon/blender_mcp_addon)
or the release ZIP. Enable it in Blender preferences.

## First call

=== "MCP"

    Add to your client's MCP config:

    ```json
    {
      "mcpServers": {
        "blender": {
          "command": "meshwire",
          "args": ["--port", "9876"]
        }
      }
    }
    ```

    Press `N` in the Blender viewport, open the "Meshwire" panel,
    click "Start Server". Then ask your assistant:

    > *"Create a red cube at (2, 0, 0), add a subdivision surface modifier with 2 levels, and render it to /tmp/render.png."*

## Where to next

- [Tool reference](tools.md): 218 tools grouped by Blender pipeline stage
- [Usage examples](usage.md): self-refinement loop, MSFS, livery walkthroughs
- [Architecture](architecture.md): server / addon / TCP layout
- [MSFS roadmap](MSFS_ROADMAP.md): MSFS content workflow
