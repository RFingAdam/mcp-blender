# Architecture

How `mcp-blender` is built.

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

The addon runs a non-blocking TCP server inside Blender using
`bpy.app.timers`, so the UI stays responsive while it waits for commands.
Each command then runs inline on the main thread, which blocks the UI until
it finishes. AI model generation returns a `job_id` for polling; other
long-running work, such as renders and bakes, does not.

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
│   ├── compat.py                 ← Blender version compatibility
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
├── docs/                         ← this docs/ directory
├── scripts/                      ← build / packaging scripts
└── tests/                        ← unit tests + truth harness (real Blender)
```

## Design decisions

- **Two-process split.** The MCP server is a pure-Python stdio process;
  Blender runs the addon as a TCP-listening helper. Keeps Blender out
  of the MCP message loop and makes the server safe to restart without
  losing Blender state.
- **`bpy.app.timers` dispatch.** A timer polls the socket and runs each
  command inline on Blender's main thread.
- **20-file handler package.** Originally a single `handlers.py`; was
  refactored into 20 modules so each pipeline stage owns its own file
  and the LSP / search experience stays sane at 218 tools.
- **Jobs for AI generation.** AI model generation returns a `job_id` and
  clients poll `blender_ai_model_status`.
- **Compatibility layer.** `compat.py` is meant to shim Blender API
  differences. Its Blender 5.x paths are known to be incorrect and are being
  fixed.
