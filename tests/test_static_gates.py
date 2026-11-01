"""Static AST gates over the addon source.

Each check parses the addon with ``ast`` only: no ``bpy``, no addon import. A
check returns a sorted list of stable violation strings (repo-relative path plus
symbol, no line numbers). ``tests/static_gate_baseline.json`` records today's
violations per check. The tests fail on a new violation and on a baseline entry
that no longer occurs, so fixing a bug forces a baseline update.

Regenerate the baseline with::

    python -m tests.test_static_gates --write-baseline
"""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = REPO_ROOT / "addon" / "blender_mcp_addon"
BASELINE_PATH = Path(__file__).resolve().parent / "static_gate_baseline.json"

# Attributes every handler object has that no mixin defines by name.
_INHERITED_SELF_ATTRS = {"_handlers"}


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _python_files(addon_dir: Path) -> list[Path]:
    return sorted(p for p in addon_dir.rglob("*.py") if "__pycache__" not in p.parts)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _rel(path: Path, addon_dir: Path) -> str:
    """Stable repo-relative posix path (falls back to the addon-relative path)."""
    try:
        return path.relative_to(addon_dir.parent.parent).as_posix()
    except ValueError:
        return path.relative_to(addon_dir).as_posix()


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _module_defined_names(tree: ast.Module) -> set[str]:
    """Names bound at module top level (defs, classes, assigns, imports)."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
    return names


# ---------------------------------------------------------------------------
# Check 1: relative imports that point at the importing module itself
# ---------------------------------------------------------------------------


def _resolve_relative(path: Path, node: ast.ImportFrom, addon_dir: Path) -> Path | None:
    """Return the file a ``from .x import y`` resolves to, or None if absent."""
    base = path.parent
    for _ in range(node.level - 1):
        base = base.parent
    if base != addon_dir and addon_dir not in base.parents:
        return None
    target = base.joinpath(*(node.module or "").split("."))
    if target.with_suffix(".py").is_file():
        return target.with_suffix(".py")
    if (target / "__init__.py").is_file():
        return target / "__init__.py"
    return None


def check_relative_imports(addon_dir: Path = ADDON_DIR) -> list[str]:
    """Names imported from a relative module that is the file itself or missing.

    ``handlers/msfs.py`` doing ``from .msfs import x`` resolves to itself, not to
    the sibling ``msfs`` package, so the name is undefined and the import fails
    when the handler runs.
    """
    out: list[str] = []
    for path in _python_files(addon_dir):
        tree = _parse(path)
        own_names = _module_defined_names(tree)
        rel = _rel(path, addon_dir)
        for node, symbol in _enclosing_symbols(tree):
            if not (isinstance(node, ast.ImportFrom) and node.level and node.module):
                continue
            target = _resolve_relative(path, node, addon_dir)
            dots = "." * node.level
            if target is None:
                out.append(f"{rel}::{symbol}: unresolved import {dots}{node.module}")
            elif target == path:
                for alias in node.names:
                    if alias.name not in own_names:
                        out.append(f"{rel}::{symbol}: self-import {dots}{node.module}.{alias.name}")
    return sorted(out)


# ---------------------------------------------------------------------------
# Check 2: self._x attributes no mixin defines
# ---------------------------------------------------------------------------


def _handler_classes(addon_dir: Path) -> list[tuple[Path, ast.ClassDef]]:
    out = []
    for path in sorted((addon_dir / "handlers").glob("*.py")):
        for node in _parse(path).body:
            if isinstance(node, ast.ClassDef):
                out.append((path, node))
    return out


def _class_member_names(cls: ast.ClassDef) -> set[str]:
    """Methods, class attributes, and ``self.x = ...`` assignments in a class."""
    names: set[str] = set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    for node in ast.walk(cls):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                names.add(node.attr)
    return names


def check_self_attributes(addon_dir: Path = ADDON_DIR) -> list[str]:
    """``self._name`` reads that no handler mixin defines.

    Module-level functions in ``_helpers.py`` do not count: calling one as
    ``self._bake_x()`` still raises AttributeError.
    """
    classes = _handler_classes(addon_dir)
    defined = set(_INHERITED_SELF_ATTRS)
    for _, cls in classes:
        defined |= _class_member_names(cls)

    out: list[str] = []
    for path in sorted({path for path, _ in classes}):
        rel = _rel(path, addon_dir)
        for node, symbol in _enclosing_symbols(_parse(path)):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Load)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and node.attr.startswith("_")
                and not node.attr.startswith("__")
                and node.attr not in defined
            ):
                out.append(f"{rel}::{symbol}: self.{node.attr}")
    return sorted(out)


# ---------------------------------------------------------------------------
# Check 3: validator call shapes
# ---------------------------------------------------------------------------


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _enclosing_symbols(tree: ast.Module):
    """Yield (node, 'Class.func' or 'func' or '<module>') for every node."""

    def visit(node: ast.AST, scope: tuple[str, ...]):
        yield node, ".".join(scope) or "<module>"
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                yield from visit(child, scope + (child.name,))
            else:
                yield from visit(child, scope)

    yield from visit(tree, ())


def check_validator_calls(addon_dir: Path = ADDON_DIR) -> list[str]:
    """``validate_enum`` with name/allowed swapped, ``validate_filepath`` without name.

    A string ``allowed`` makes the enum comprehension iterate characters, so
    every real value is rejected. ``validate_filepath(value)`` without ``name``
    raises TypeError.
    """
    out: list[str] = []
    for path in _python_files(addon_dir):
        rel = _rel(path, addon_dir)
        for node, symbol in _enclosing_symbols(_parse(path)):
            if not isinstance(node, ast.Call):
                continue
            fname = _called_name(node)
            kwargs = {k.arg for k in node.keywords if k.arg}
            if fname == "validate_enum" and len(node.args) >= 3:
                name_arg, allowed_arg = node.args[1], node.args[2]
                if isinstance(name_arg, (ast.List, ast.Tuple)) or (
                    _const_str(allowed_arg) is not None
                ):
                    label = next(
                        (
                            ast.unparse(a)
                            for a in (allowed_arg, name_arg)
                            if _const_str(a) is not None
                        ),
                        ast.unparse(node.args[0]),
                    )
                    out.append(f"{rel}::{symbol}: validate_enum swapped: {label}")
            elif fname == "validate_filepath":
                has_star = any(isinstance(a, ast.Starred) for a in node.args)
                if len(node.args) < 2 and "name" not in kwargs and not has_star:
                    out.append(
                        f"{rel}::{symbol}: validate_filepath missing name: "
                        f"{ast.unparse(node.args[0]) if node.args else '?'}"
                    )
    return sorted(out)


# ---------------------------------------------------------------------------
# Handler registry and schema checks
# ---------------------------------------------------------------------------


def _registered_handlers(addon_dir: Path) -> dict[str, str]:
    """Map handler key to method name from ``_register_handlers``."""
    init = addon_dir / "handlers" / "__init__.py"
    out: dict[str, str] = {}
    for node in ast.walk(_parse(init)):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Attribute)
            and target.value.attr == "_handlers"
        ):
            continue
        key = _const_str(target.slice)
        if (
            key is not None
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "self"
        ):
            out[key] = node.value.attr
    return out


def _method_index(addon_dir: Path) -> dict[str, tuple[Path, ast.FunctionDef]]:
    index: dict[str, tuple[Path, ast.FunctionDef]] = {}
    for path, cls in _handler_classes(addon_dir):
        for node in cls.body:
            if isinstance(node, ast.FunctionDef):
                index.setdefault(node.name, (path, node))
    return index


def _tools() -> dict[str, dict]:
    from tests.harness.catalog import load_tools

    return load_tools()


def check_tool_handler_parity(
    addon_dir: Path = ADDON_DIR, tools: dict[str, dict] | None = None
) -> list[str]:
    """Registered handlers with no tool, and tools with no registered handler."""
    tools = _tools() if tools is None else tools
    handlers = set(_registered_handlers(addon_dir))
    out = [f"handler without tool: {name}" for name in handlers - set(tools)]
    out += [f"tool without handler: {name}" for name in set(tools) - handlers]
    return sorted(out)


def _param_reads(func: ast.FunctionDef) -> tuple[set[str], bool]:
    """Keys read from the params argument, and whether params escapes whole."""
    args = func.args.args
    if len(args) < 2:
        return set(), False
    pname = args[1].arg
    keys: set[str] = set()
    handled: set[int] = set()
    for node in ast.walk(func):
        key = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "pop")
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == pname
            and node.args
        ):
            key = _const_str(node.args[0])
            handled.add(id(node.func.value))
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == pname
        ):
            key = _const_str(node.slice)
            handled.add(id(node.value))
        elif (
            isinstance(node, ast.Compare)
            and isinstance(node.comparators[0], ast.Name)
            and node.comparators[0].id == pname
            and isinstance(node.ops[0], (ast.In, ast.NotIn))
        ):
            key = _const_str(node.left)
            handled.add(id(node.comparators[0]))
        if key is not None:
            keys.add(key)
    escapes = any(
        isinstance(n, ast.Name) and n.id == pname and id(n) not in handled for n in ast.walk(func)
    )
    return keys, escapes


def check_schema_params(
    addon_dir: Path = ADDON_DIR, tools: dict[str, dict] | None = None
) -> list[str]:
    """Diff a handler's ``params`` reads against its tool schema properties.

    Reports keys the handler reads that the schema cannot send, and schema
    properties the handler never reads (unless ``params`` is passed on whole).
    """
    tools = _tools() if tools is None else tools
    methods = _method_index(addon_dir)
    out: set[str] = set()
    for key, method_name in _registered_handlers(addon_dir).items():
        if key not in tools or method_name not in methods:
            continue
        path, func = methods[method_name]
        rel = _rel(path, addon_dir)
        props = set(tools[key].get("properties", {}))
        reads, escapes = _param_reads(func)
        for name in reads - props:
            out.add(f"{rel}::{method_name}: reads '{name}' not in schema")
        if not escapes:
            for name in props - reads:
                out.add(f"{rel}::{method_name}: schema '{name}' never read")
    return sorted(out)


# ---------------------------------------------------------------------------
# Baseline plumbing
# ---------------------------------------------------------------------------

CHECKS = {
    "relative_imports": check_relative_imports,
    "self_attributes": check_self_attributes,
    "validator_calls": check_validator_calls,
    "schema_params": check_schema_params,
    "tool_handler_parity": check_tool_handler_parity,
}


def _load_baseline() -> dict[str, list[str]]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _write_baseline() -> None:
    data = {name: fn() for name, fn in CHECKS.items()}
    BASELINE_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    for name, found in data.items():
        print(f"{name}: {len(found)}")


@pytest.mark.parametrize("name", sorted(CHECKS))
def test_against_baseline(name):
    expected = Counter(_load_baseline()[name])
    actual = Counter(CHECKS[name]())
    new = sorted((actual - expected).elements())
    stale = sorted((expected - actual).elements())
    assert not new, f"{name}: new violations (fix them):\n  " + "\n  ".join(new)
    assert not stale, (
        f"{name}: baseline entries no longer occur or occur fewer times (remove them from "
        f"static_gate_baseline.json):\n  " + "\n  ".join(stale)
    )


# ---------------------------------------------------------------------------
# Seeded fixtures: each check must catch its bug class
# ---------------------------------------------------------------------------


def _make_addon(tmp_path: Path, files: dict[str, str]) -> Path:
    addon = tmp_path / "addon" / "pkg"
    for rel, text in files.items():
        target = addon / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return addon


def test_fixture_self_import(tmp_path):
    addon = _make_addon(
        tmp_path,
        {
            "__init__.py": "",
            "handlers/__init__.py": "",
            "handlers/msfs.py": "def local():\n    pass\n\n"
            "def f():\n    from .msfs import thing\n    from .msfs import local\n",
            "msfs/__init__.py": "thing = 1\n",
        },
    )
    assert check_relative_imports(addon) == [
        "addon/pkg/handlers/msfs.py::f: self-import .msfs.thing"
    ]


def test_fixture_unresolved_import(tmp_path):
    addon = _make_addon(
        tmp_path,
        {"__init__.py": "", "a.py": "from .nope import x\n"},
    )
    assert check_relative_imports(addon) == ["addon/pkg/a.py::<module>: unresolved import .nope"]


def test_fixture_missing_self_attribute(tmp_path):
    addon = _make_addon(
        tmp_path,
        {
            "handlers/__init__.py": "",
            "handlers/a.py": "class A:\n    def _ok(self):\n        pass\n"
            "    def run(self):\n        self._ok()\n        self._missing()\n",
            "handlers/_helpers.py": "def _missing():\n    pass\n",
        },
    )
    assert check_self_attributes(addon) == ["addon/pkg/handlers/a.py::A.run: self._missing"]


def test_fixture_validator_calls(tmp_path):
    addon = _make_addon(
        tmp_path,
        {
            "a.py": "def f(v):\n"
            "    validate_enum(v, ['A'], 'name')\n"
            "    validate_enum(v, 'mode', 'ABC')\n"
            "    validate_enum(v, 'mode', ['A'])\n"
            "    validate_filepath(v)\n"
            "    validate_filepath(v, 'path')\n"
            "    validate_filepath(v, name='path')\n",
        },
    )
    assert check_validator_calls(addon) == [
        "addon/pkg/a.py::f: validate_enum swapped: 'ABC'",
        "addon/pkg/a.py::f: validate_enum swapped: 'name'",
        "addon/pkg/a.py::f: validate_filepath missing name: v",
    ]


def test_fixture_two_swapped_calls_are_two_entries_and_a_third_fails(tmp_path):
    two = "def f(v):\n    validate_enum(v, ['A'], 'mode')\n    validate_enum(v, ['A'], 'size')\n"
    addon = _make_addon(tmp_path, {"a.py": two})
    baseline = check_validator_calls(addon)
    assert len(baseline) == 2
    assert baseline[0] != baseline[1]

    # A third call, identical to an existing one, must change the count.
    addon = _make_addon(tmp_path, {"a.py": two + "    validate_enum(v, ['A'], 'mode')\n"})
    grown = check_validator_calls(addon)
    assert len(grown) == 3
    assert (Counter(grown) - Counter(baseline)).total() == 1


_REGISTRY = (
    "class CH:\n    def _register_handlers(self):\n"
    '        self._handlers["x"] = self._handle_x\n'
    '        self._handlers["orphan"] = self._handle_orphan\n'
)


def test_fixture_schema_params(tmp_path):
    addon = _make_addon(
        tmp_path,
        {
            "handlers/__init__.py": _REGISTRY,
            "handlers/a.py": "class A:\n    def _handle_x(self, params):\n"
            "        params.get('size')\n        params['bogus']\n"
            "    def _handle_orphan(self, params):\n        pass\n",
        },
    )
    tools = {"x": {"properties": {"size": {}, "unused": {}}}}
    assert check_schema_params(addon, tools) == [
        "addon/pkg/handlers/a.py::_handle_x: reads 'bogus' not in schema",
        "addon/pkg/handlers/a.py::_handle_x: schema 'unused' never read",
    ]


def test_fixture_schema_params_whole_params_escape(tmp_path):
    addon = _make_addon(
        tmp_path,
        {
            "handlers/__init__.py": _REGISTRY,
            "handlers/a.py": "class A:\n    def _handle_x(self, params):\n"
            "        return other(params)\n",
        },
    )
    assert check_schema_params(addon, {"x": {"properties": {"size": {}}}}) == []


def test_fixture_tool_handler_parity(tmp_path):
    addon = _make_addon(tmp_path, {"handlers/__init__.py": _REGISTRY})
    tools = {"x": {}, "no_handler": {}}
    assert check_tool_handler_parity(addon, tools) == [
        "handler without tool: orphan",
        "tool without handler: no_handler",
    ]


def test_parity_baseline_has_expected_toolless_handlers():
    """ping and the ai_* handlers are the only ones without a tool."""
    found = [v for v in check_tool_handler_parity() if v.startswith("handler without")]
    assert len(found) == 8


if __name__ == "__main__":
    if "--write-baseline" in sys.argv:
        _write_baseline()
