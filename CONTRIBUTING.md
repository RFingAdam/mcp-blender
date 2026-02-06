# Contributing to MCP Blender

Thank you for your interest in contributing to MCP Blender! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.10 or later
- Blender 4.2 LTS or 5.0 (for testing)
- Git

### Setting Up the Development Environment

1. **Clone the repository:**
   ```bash
   git clone https://github.com/RFingAdam/mcp-blender
   cd mcp-blender
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
   ln -s $(pwd)/addon/blender_mcp_addon ~/.config/blender/4.2/scripts/addons/
   ```

## Code Style

We use [Ruff](https://github.com/astral-sh/ruff) for linting and formatting.

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

### Running Integration Tests

Integration tests require Blender:

```bash
blender --background --python tests/blender_integration_test.py
```

### Writing Tests

- Add unit tests to `tests/test_*.py`
- Add integration tests to `tests/blender_integration_test.py`
- Ensure tests are deterministic and don't depend on external state

## Project Structure

```
mcp-blender/
├── src/mcp_blender/           # MCP server package
│   ├── server.py              # Tool definitions and MCP handlers
│   ├── blender_client.py      # TCP client for Blender
│   └── tools/                 # Tool category modules
├── addon/blender_mcp_addon/   # Blender addon
│   ├── __init__.py            # Addon registration
│   ├── socket_server.py       # TCP server
│   ├── handlers.py            # Command handlers
│   ├── compat.py              # Version compatibility
│   ├── utils.py               # Shared utility functions
│   └── external/              # External integrations
│       ├── refinement.py      # Refinement session state
│       └── ai_backends/
│           └── stable_fast_3d.py  # Stable Fast 3D backend
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

In `addon/blender_mcp_addon/handlers.py`:

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

Add tests for the new tool in both:
- `tests/test_tools.py` (schema validation)
- `tests/blender_integration_test.py` (functional test)

## Version Compatibility

When adding features that differ between Blender versions:

1. Add detection in `addon/blender_mcp_addon/compat.py`
2. Use the compatibility functions in handlers
3. Test on both Blender 4.2 and 5.0

Example:
```python
from .compat import IS_5_0_OR_LATER

if IS_5_0_OR_LATER:
    # Blender 5.0 code path
else:
    # Blender 4.2 code path
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
