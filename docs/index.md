# meshwire

**Control Blender from any MCP client: 218 tools across modeling, materials, sculpting, animation, AI 3D generation, and MSFS content creation.**
**Drive it from your IDE, terminal, or AI agent and run an iterative render-analyze-refine loop without leaving Blender.**

---

## What it is

`meshwire` exposes 218 Blender tools via the Model Context Protocol.
The MCP server speaks stdio; a Blender addon listens on local TCP and
dispatches into `bpy` on the main thread via `bpy.app.timers`. Supports
Blender 4.2 through 5.2. **Blender 4.5 LTS** and **Blender 5.2 LTS** are tested on every PR.
Blender 4.2, 4.3, 4.4, 5.0 and 5.1 are tested nightly, best effort.

## Install

```bash
pip install meshwire
```

Then download `meshwire-addon-<version>.zip` from the
[GitHub release](https://github.com/RFingAdam/meshwire/releases), or build it with
`python scripts/package_addon.py`. In Blender, open **Edit > Preferences > Get Extensions**, open the
dropdown arrow at the top right, choose **Install from Disk...** and select the ZIP. Do not unzip it.

## First call

=== "MCP"

    Add to your client's MCP config:

    ```json
    {
      "mcpServers": {
        "blender": {
          "command": "meshwire"
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
