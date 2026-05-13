# Architecture

How `mcp-blender` is built, and how it composes with the rest of
[eng-mcp-suite](https://github.com/RFingAdam/eng-mcp-suite).

## Internal layout

```
┌──────────────────────────────────────────────────────────────────┐
│  User-facing surfaces                                            │
│  ┌────────────────┐                                              │
│  │  MCP server    │ stdio MCP protocol                           │
│  │  (Python)      │                                              │
│  └───────┬────────┘                                              │
└──────────┼───────────────────────────────────────────────────────┘
           │ TCP/JSON-RPC on localhost:9876
┌──────────▼───────────────────────────────────────────────────────┐
│  Blender addon (runs inside Blender)                             │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │  socket_server │  │  handlers/       │  │  bpy.app.timers │  │
│  │  (TCP listen)  │  │  (218 dispatchers)│ │  (main thread)  │  │
│  └────────────────┘  └──────────────────┘  └─────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
           │ writes back via render / generated assets
┌──────────▼───────────────────────────────────────────────────────┐
│  External integrations                                           │
│  • Poly Haven    (free HDRIs / textures / models, no key)        │
│  • AI 3D backends (Rodin / Meshy / Tripo / TripoSR / SF3D / ...) │
│  • Ollama vision (refinement scoring)                            │
└──────────────────────────────────────────────────────────────────┘
```

Critically, the addon runs a **non-blocking** TCP server inside
Blender using `bpy.app.timers`, so the main thread continues to render
the viewport while waiting for commands. Long-running operations (AI
generation, multi-angle render, vision analysis) use a job queue and
return `job_id` for polling.

## Source layout

```
mcp-blender/
├── src/mcp_blender/             ← MCP server package
│   ├── server.py                 ← tool definitions + MCP handlers
│   ├── blender_client.py         ← TCP client for Blender comms
│   └── types.py                  ← shared type definitions
├── addon/blender_mcp_addon/     ← Blender addon (runs inside Blender)
│   ├── __init__.py               ← addon registration + UI
│   ├── socket_server.py          ← TCP server (bpy.app.timers)
│   ├── handlers/                 ← 218 command dispatchers (20-file pkg)
│   ├── compat.py                 ← Blender 4.2 / 5.0 compatibility
│   ├── validation.py             ← parameter validation
│   ├── utils.py                  ← shared utilities
│   ├── external/                 ← integrations
│   │   ├── cache.py              ← asset caching
│   │   ├── polyhaven.py          ← Poly Haven API client
│   │   ├── refinement.py         ← refinement session state
│   │   ├── ai_models.py          ← AI 3D orchestration
│   │   ├── mesh_processing.py    ← mesh cleanup / decimation
│   │   ├── job_queue.py          ← persistent job tracking
│   │   └── ai_backends/          ← Rodin / Meshy / Tripo / TripoSR / …
│   └── msfs/                     ← MSFS content + livery tools
├── assets/                       ← logo-banner.svg, banner-legacy.svg
├── docs/                         ← this docs/ directory
├── scripts/                      ← build / packaging scripts
└── tests/                        ← unit + Blender integration tests
```

## Position in eng-mcp-suite

`mcp-blender` is a **creative-tooling tangent** in the eng-mcp-suite
family — it shares the brand, MCP wiring, and docs structure with the
engineering MCPs, but doesn't fit the engineering compliance loop
directly.

```
   ┌───────────────────────────────────┐
   │ AI agent (Claude Code / Desktop)  │
   └──────┬──────────────────┬─────────┘
          │ via MCP          │ via MCP
   ┌──────▼─────────┐  ┌─────▼─────────────┐
   │ engineering    │  │  mcp-blender      │  ← creative tooling
   │ MCPs (suite)   │  │  (this MCP)        │
   └────────────────┘  └────────────────────┘
```

### Feeds / consumes

- No direct data exchange with sibling engineering MCPs today.
- Shares the brand banner (`assets/logo-banner.svg`), docs scaffold,
  and `eng-mcp-suite` README cross-link block.

### Workflow bundles

`mcp-blender` is not part of the engineering compliance bundles
(`emc-compliance`, `pcb-review`, `rf-design`). It's catalogued in the
suite manifest as a standalone creative-tooling member.

---

## Design decisions

- **Two-process split.** The MCP server is a pure-Python stdio process;
  Blender runs the addon as a TCP-listening helper. Keeps Blender out
  of the MCP message loop and makes the server safe to restart without
  losing Blender state.
- **`bpy.app.timers` dispatch.** Every command runs on Blender's main
  thread. The socket server drops commands into a queue;
  `bpy.app.timers` drains the queue inside the Blender event loop.
- **20-file handler package.** Originally a single `handlers.py`; was
  refactored into 20 modules so each pipeline stage owns its own file
  and the LSP / search experience stays sane at 218 tools.
- **Job queue for long-running tools.** AI generation, multi-angle
  render, and vision analysis return a `job_id`; clients poll
  `*_status` tools. Avoids blocking the MCP stdio while a 3D model
  generates for 60 s.
- **Blender 4.2 / 5.0 compatibility layer.** `compat.py` shims the
  three known API breaks (action FCurves, mathutils precision, EEVEE
  vs EEVEE_NEXT) so handlers stay version-agnostic.
- **MIT licensed.** No GPL inheritance from Blender, since the addon
  is run by Blender, not linked into it.
