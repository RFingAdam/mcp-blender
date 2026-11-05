# Contributing to MCP Blender

Thank you for your interest in contributing to MCP Blender! This document provides guidelines and instructions for contributing.
## Before you contribute

By submitting a pull request to this repository, you agree to the terms
of [CLA.md](CLA.md). A short contributor license agreement that lets the
Maintainer change how this Project is licensed in future without needing
to track down every past contributor individually. You keep your own copyright; you're just
granting the Maintainer the same relicensing rights over your
contribution that they already have over the rest of the codebase.

No signature or bot step is required today: opening the PR is the
agreement. Read CLA.md before you submit if you want the full terms.


## Development Setup

### Prerequisites

- Python 3.10 or later
- Blender 4.5 LTS or 5.2 LTS (for testing). Meshwire supports 4.2 through 5.2, and the other series
  run nightly on a best-effort basis.
- Git

### Setting Up the Development Environment

1. **Clone the repository:**
   ```bash
   git clone https://github.com/RFingAdam/meshwire
   cd meshwire
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   # or
   .venv\Scripts\activate     # Windows
   ```

3. **Install development dependencies:**
   ```bash
   pip install -e ".[dev]"
   ```

   Or using [uv](https://github.com/astral-sh/uv) (recommended for faster installs):
   ```bash
   uv pip install -e ".[dev]"
   ```

4. **Install the Blender addon:**
   ```bash
   # Symlink the addon to Blender's addons folder
   ln -s $(pwd)/addon/blender_mcp_addon ~/.config/blender/4.5/scripts/addons/
   ```

## Code Style

We use [Ruff](https://github.com/astral-sh/ruff) for linting and formatting. CI fails if
`ruff format --check .` would change a Python file, so run `ruff format .` before you push.
Code blocks in Markdown are examples and are not formatted.

```bash
# Check for issues
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .
```

### Style Guidelines

- Line length: 100 characters
- Use type hints for function signatures
- Write docstrings for public functions and classes
- Follow PEP 8 naming conventions

## Testing

### Running Unit Tests

Unit tests don't require Blender:

```bash
pytest tests/ --ignore=tests/blender_integration_test.py -v
```

### Running Tests Against Real Blender

The truth harness runs every tool in real headless Blender. See
[Truth harness](#truth-harness) below. The older
`tests/blender_integration_test.py` script is not run in CI.

### Writing Tests

- Add unit tests to `tests/test_*.py`
- Real-Blender behaviour is covered by the truth harness, so a new tool needs no extra script
- Ensure tests are deterministic and don't depend on external state

## Truth harness

The truth harness runs every tool in real headless Blender and compares the results with
committed baselines. It runs on Blender 4.5 and 5.2 on every pull request, and a difference there
blocks the merge. Blender 4.2, 4.3, 4.4, 5.0 and 5.1 run nightly and are best effort. Baselines live
in `tests/harness/baselines/`. They hold case ids and result classes only, never messages or paths.

Each tool gets several cases: a minimal call, one call per enum value, and a call with a
required argument left out. Each case ends up in one class:

- `PASS`: the tool returned a result with no error.
- `EXPECTED`: the failure is the right one. The network was blocked on purpose, or a bad
  argument raised a validation error.
- `SOFT_FAIL`: the tool returned an error result instead of raising. Often benign, such as an
  AI backend that is offline. Sometimes a real defect.
- `BUG`: the tool raised an exception it should not have raised, or an `#invalid` case did not
  raise a validation error.
- `CRASH`: Blender died during the case.
- `HANG`: the case ran past its time limit and was killed.
- `FAIL`: used only by the socket lane, when a check did not hold.

### Reading a failed check

A failed check prints one line per difference from the baseline:

- `worse: id OLD -> NEW`: the class got more severe.
- `improved: id OLD -> NEW`: the class got less severe. This fails too, because an
  improvement must be recorded in the baseline.
- `changed: id OLD -> NEW`: the class changed with no change in severity.
- `added: id NEW`: a case exists that the baseline does not know.
- `removed: id (was OLD)`: the baseline has a case that no longer exists.

### Session crashes

Late in a full run, Blender 4.2 and 4.3 sometimes crash inside Blender itself. The crash lands
on a different heavy case each time (an export, a preview render, `scene_new`), and that case
passes when it runs alone. The nightly job passes `--retry-crashes`, which reruns each crashed
case alone in a fresh Blender. A case that passes alone takes its solo class and is printed as
`session crash: id CRASH in the full run, CLASS alone`. The list is also saved to
`session_crashes.json`. A case that crashes alone too stays `CRASH`. The 4.5 and 5.2 jobs never
retry, so any crash there fails the check. A run with `--retry-crashes` that finds more than 3
session crashes exits 1 even when the baseline matches, because that many is not the known segfault.

### Reproduce locally

`scripts/fetch_blender.py` downloads and checks a Blender build. It supports linux-x64 only.

```bash
BIN=$(python scripts/fetch_blender.py 4.5.15 --dest ~/blender)
python -m tests.harness.driver --blender "$BIN" --out runs/4.5 \
    --check-baseline tests/harness/baselines/blender-4.5.json
```

CI runs this under `xvfb-run -a`. On a Linux machine with no display, do the same. `runs/` is
git-ignored.

To record new results, use `--write-baseline tests/harness/baselines/blender-4.5.json` in place
of `--check-baseline`. The driver refuses to write `blender-X.Y.json` from a different Blender
series. A run takes several minutes. Run it with the dev dependencies installed
(`uv sync --extra dev`).

### Without Linux

Download the `harness-<version>` artifact from the failed CI run. `driver-<series>/results.json`
has the same shape as a baseline. Copy it over the baseline file, sorted by key, indented by two
spaces, with a trailing newline. This is what `write_baseline` writes:

```bash
python -c "import json,sys; d=json.load(open(sys.argv[1])); open(sys.argv[2],'w').write(json.dumps(d,indent=2,sort_keys=True)+'\n')" \
    driver-4.5/results.json tests/harness/baselines/blender-4.5.json
```

Either way, after a 4.5, 5.2 or socket lane baseline changes, run `python scripts/tool_status.py`.
It rewrites the tool counts in `README.md` from the baselines, and `tests/test_readme.py` fails
until they match.

### The socket lane

The socket lane starts a GUI Blender (under `xvfb-run`) with the real addon socket and checks
the scene afterwards instead of trusting the reply. Run it with:

```bash
xvfb-run -a python -m tests.harness.socket_lane --blender "$BIN" --out runs/socket-4.5 \
    --check-baseline tests/harness/baselines/socket-lane.json
```

Use `--write-baseline` to update it. The file is keyed by Blender series (`4.5`, `5.2`) and
the lane replaces only the series it ran. An artifact's `results.json` is
`{"<series>": {...}}`, so merge that one key into the file. Do not copy it over.

### Adding a tool

A new tool shows up as `added:` lines. That is expected. Record them in the 4.5 and 5.2
baselines. Copy the same lines into every other `blender-*.json` baseline too, so the sync test
passes. The nightly job flags any real difference there.

If the new tool has a benign `SOFT_FAIL` case, such as no AI backend, add the tool to
`SOFT_FAIL_ALLOWED` in `tests/harness/fixtures.py`, with a reason. A test fails until you do. A
`SOFT_FAIL` that hides a real defect needs a fix, not a table entry: `SOFT_FAIL_DEFECTS` must
stay empty.

## Project Structure

```
meshwire/
├── src/mcp_blender/           # MCP server package
│   ├── server.py              # Tool definitions and MCP handlers
│   ├── blender_client.py      # TCP client for Blender
│   └── tools/                 # Tool category modules
├── addon/blender_mcp_addon/   # Blender addon
│   ├── __init__.py            # Addon registration
│   ├── socket_server.py       # TCP server
│   ├── handlers/              # Command handlers, one file per domain
│   ├── compat.py              # Version compatibility
│   ├── utils.py               # Shared utility functions
│   └── external/              # External integrations
│       ├── refinement.py      # Refinement session state
│       ├── ai_models.py       # AI generation orchestration
│       └── ai_backends/       # AI backend implementations
├── assets/                    # Static and generated assets
│   └── generated/             # AI-generated models & textures (gitignored)
├── tests/                     # Test suite
└── scripts/                   # Build scripts
```

## Adding New Tools

### 1. Add the Tool Definition

In `src/mcp_blender/server.py`, add a `Tool` to the `TOOLS` list:

```python
Tool(
    name="blender_my_new_tool",
    description="What this tool does",
    inputSchema={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "Parameter description"},
        },
        "required": ["param1"],
    },
),
```

### 2. Add the Handler

In the matching file under `addon/blender_mcp_addon/handlers/`:

1. Register the handler in `_register_handlers()`:
   ```python
   self._handlers["my_new_tool"] = self._handle_my_new_tool
   ```

2. Implement the handler:
   ```python
   def _handle_my_new_tool(self, params: dict) -> dict:
       """Handler docstring."""
       # Implementation using bpy
       return {"result": "value"}
   ```

### 3. Add Tests

Add a schema test in `tests/test_tools.py`. The truth harness generates cases for the
new tool on its own, so record its results in the baselines. See
[Truth harness](#truth-harness).

## Version Compatibility

When adding features that differ between Blender versions:

1. Add detection in `addon/blender_mcp_addon/compat.py`
2. Use the compatibility functions in handlers
3. Test on both Blender 4.5 and 5.2

Detect what Blender offers, never its version number. Read the identifier from the
running Blender (`hasattr`, `bl_rna.properties`, enum items, `dir(bpy.ops.x)`), as in
`compat.boolean_solver`:
```python
offered = _enum_identifiers(bpy.types.BooleanModifier, "solver")
```

## Pull Request Process

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes** following the guidelines above

3. **Run tests and linting:**
   ```bash
   ruff check .
   ruff format --check .
   pytest tests/ --ignore=tests/blender_integration_test.py
   ```

4. **Commit with a clear message:**
   ```bash
   git commit -m "Add feature: description of what it does"
   ```

5. **Push and create a PR:**
   ```bash
   git push origin feature/my-feature
   ```

6. **In your PR description:**
   - Describe what the change does
   - Reference any related issues
   - Note if it affects version compatibility

## Reporting Issues

When reporting issues, please include:

- Blender version
- Python version
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Relevant error messages or logs

## Questions?

Feel free to open an issue for questions or discussions about the project.
