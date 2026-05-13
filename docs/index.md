# mcp-blender

**Control Blender from any MCP client — 218 tools across modeling, materials, sculpting, animation, AI 3D generation, and MSFS content creation.**
**Drive it from your IDE, terminal, or AI agent and run an iterative render-analyze-refine loop without leaving Blender.**

---

## What it is

`mcp-blender` exposes 218 Blender tools via the Model Context Protocol.
The MCP server speaks stdio; a Blender addon listens on local TCP and
dispatches into `bpy` on the main thread via `bpy.app.timers`. Supports
**Blender 4.2 LTS** and **Blender 5.0**.

## Install

```bash
pip install mcp-blender
```

Then install the Blender addon from
[`addon/blender_mcp_addon/`](https://github.com/RFingAdam/mcp-blender/tree/main/addon/blender_mcp_addon)
or the release ZIP. Enable it in Blender preferences.

## First call

=== "MCP"

    Add to your client's MCP config:

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

    Press `N` in the Blender viewport, open the "MCP Server" panel,
    click "Start Server". Then ask your assistant:

    > *"Create a red cube at (2, 0, 0), add a subdivision surface modifier with 2 levels, and render it to /tmp/render.png."*

## Where to next

- [Tool reference](tools.md) — 218 tools grouped by Blender pipeline stage
- [Usage examples](usage.md) — self-refinement loop, MSFS, livery walkthroughs
- [Architecture](architecture.md) — server / addon / TCP layout
- [MSFS roadmap](MSFS_ROADMAP.md) — MSFS content workflow

---

!!! note "Part of eng-mcp-suite"
    This MCP server is part of [eng-mcp-suite](https://github.com/RFingAdam/eng-mcp-suite) —
    an umbrella of engineering MCP servers. `mcp-blender` is a
    creative-tooling tangent in the family: it shares brand and MCP
    wiring, but doesn't fit the engineering compliance loop directly.
