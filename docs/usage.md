# Usage

Two practical walkthroughs: the self-refinement loop on a generated
mesh, and an MSFS aircraft livery transfer. For the full tool reference,
see [Tools](tools.md).

---

## Scenario: iterative 3D refinement

You want a low-poly pine tree mesh. You'll generate an initial draft
with `execute_script`, render from multiple angles, score it with the
Ollama vision model, and iterate until the score converges.

### Setup

```bash
pip install mcp-blender
ollama pull llava   # vision model
```

Enable the Blender addon, start the MCP socket server, register the MCP
config in your client. See [`index.md`](index.md#install) for details.

### Step 1 — Open a refinement session

> *"Start a refinement session for a low-poly pine tree."*

```python
blender_refine_create_session(
    object_name="Tree",
    prompt="A realistic low-poly pine tree, ~500 triangles, single trunk"
)
```

### Step 2 — Generate the initial mesh

> *"Generate a draft mesh with `bmesh` — trunk + 3 conical layers."*

```python
blender_execute_script(script="""
import bmesh, bpy
mesh = bpy.data.meshes.new("Tree")
obj = bpy.data.objects.new("Tree", mesh)
bpy.context.collection.objects.link(obj)
bm = bmesh.new()
# trunk
bmesh.ops.create_cone(bm, segments=8, radius1=0.15, radius2=0.10, depth=1.2)
# foliage layers
for h, r in [(1.1, 0.8), (1.7, 0.55), (2.2, 0.35)]:
    bmesh.ops.create_cone(bm, segments=8, radius1=r, radius2=0, depth=0.7,
                          matrix=...).
# ...
bm.to_mesh(mesh); bm.free()
""")
```

### Step 3 — First iteration

```python
blender_refine_iteration(
    object_name="Tree",
    iteration=0,
    max_iterations=5,
)
```

`refine_iteration` renders the mesh from front / right / top /
perspective, runs `analyze_viewport` against the Ollama vision model,
and returns a structured score plus suggested fixes.

Returned:

```json
{
  "iteration": 0,
  "score": 0.62,
  "suggestions": [
    "Foliage layers look too symmetric — vary radii by ±15%",
    "Trunk base is too narrow for visual stability"
  ]
}
```

### Step 4 — Apply fixes and iterate

> *"Apply the suggested fixes and run iteration 1."*

The agent edits the script, re-runs it, then calls
`refine_iteration` again. Score climbs to 0.78.

### Step 5 — Converge

Iterations 2 and 3 push the score to 0.91 and 0.93. The agent decides
to stop (delta < 0.02). Final session inspection:

```python
blender_refine_get_session(session_id="...")
```

Shows the full iteration history — scripts, renders, scores, and
suggestions.

---

## Scenario: MSFS livery transfer

You have a livery PNG painted for a Fenix A320 and want it on a
PMDG 737. `msfs_livery_transfer` maps the design between templates.

### Step 1 — Inspect available templates

```python
blender_msfs_livery_get_aircraft_templates()
```

Returns FBW A32NX, Fenix A320/319/321, PMDG 737/777, iniBuilds, …

### Step 2 — Analyze the source livery

```python
blender_msfs_livery_analyze(image_path="./fenix_livery.png")
```

Returns the color palette, identifiable elements (cheatline, logo,
nose, tail), and UV regions used.

### Step 3 — Transfer

```python
blender_msfs_livery_transfer(
    source_template="fenix_a320",
    target_template="pmdg_737",
    source_image="./fenix_livery.png",
    output_path="./pmdg_737_livery.png",
)
```

The transfer maps each identified element from the source UV layout to
the target UV layout, preserving brand colors via
`msfs_livery_extract_colors`.

### Step 4 — Package + validate

```python
blender_msfs_livery_create_package(...)
blender_msfs_livery_convert_to_dds(...)
blender_msfs_livery_validate_package(package_path="./MyAirline-PMDG737")
```

The result is a ready-to-drop MSFS livery package.

---

## What just happened

In two scenarios you've driven Blender through 9+ MCP tools end-to-end
without writing a UI for it. The self-refinement loop is the unique
strength: the agent generates, evaluates, fixes, and repeats — all
inside the MCP protocol.

- For more tools: [Tool reference](tools.md)
- For how this fits in the suite: [Architecture](architecture.md)
- For sibling MCPs: [eng-mcp-suite catalog](https://github.com/RFingAdam/eng-mcp-suite#whats-included)
