"""Static checks on addon handler call signatures.

These tests parse the addon source with ``ast`` and require neither Blender
nor the MCP server dependencies, so they run in plain ``pytest``.

They guard against two classes of bug that are invisible until a handler is
actually invoked at runtime:

1. ``validate_enum(value, name, allowed)`` called with ``name`` and ``allowed``
   swapped. Because ``allowed`` is then a ``str``, the ``[a.upper() for a in
   allowed]`` comprehension iterates its characters, so every real enum value
   is rejected and only single letters are accepted.
2. Blender operators that were removed in Blender 4.x. The addon targets
   4.2 LTS and 5.x, where the legacy ``import_mesh.*`` / ``export_mesh.*``
   operators no longer exist.
"""

import ast
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent.parent / "addon" / "blender_mcp_addon"

# Operators removed in Blender 4.x, mapped to their replacement.
REMOVED_OPERATORS = {
    "import_mesh.stl": "wm.stl_import",
    "export_mesh.stl": "wm.stl_export",
    "import_scene.obj": "wm.obj_import",
    "export_scene.obj": "wm.obj_export",
}


def _python_files():
    return sorted(p for p in ADDON_DIR.rglob("*.py"))


def _attr_path(node):
    """Return a dotted name for an attribute chain, or None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def test_validate_enum_argument_order():
    """validate_enum's 2nd arg must be the parameter name, 3rd the allowed list."""
    offenders = []
    checked = 0

    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "validate_enum"):
                continue
            checked += 1
            if len(node.args) < 3:
                continue
            name_arg, allowed_arg = node.args[1], node.args[2]
            swapped = isinstance(name_arg, (ast.List, ast.Tuple)) or (
                isinstance(allowed_arg, ast.Constant) and isinstance(allowed_arg.value, str)
            )
            if swapped:
                offenders.append(f"{path.relative_to(ADDON_DIR.parent)}:{node.lineno}")

    assert checked > 0, "no validate_enum calls found - did the addon layout change?"
    assert not offenders, (
        "validate_enum(value, name, allowed) called with swapped arguments at:\n  "
        + "\n  ".join(offenders)
    )


def test_no_removed_blender_operators():
    """The addon must not call operators that Blender 4.x removed."""
    offenders = []

    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            dotted = _attr_path(node.func)
            if not dotted or not dotted.startswith("bpy.ops."):
                continue
            op = dotted[len("bpy.ops."):]
            if op in REMOVED_OPERATORS:
                offenders.append(
                    f"{path.relative_to(ADDON_DIR.parent)}:{node.lineno}: "
                    f"bpy.ops.{op} was removed in Blender 4.x, use "
                    f"bpy.ops.{REMOVED_OPERATORS[op]}"
                )

    assert not offenders, "removed Blender operators still in use:\n  " + "\n  ".join(offenders)
