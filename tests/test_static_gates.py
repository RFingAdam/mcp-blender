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
    defined: set[str] = set()
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


def _call_arg(node: ast.Call, index: int, keyword: str) -> ast.expr | None:
    """The argument at a position, or passed by keyword, or None."""
    if index < len(node.args) and not isinstance(node.args[index], ast.Starred):
        return node.args[index]
    for kw in node.keywords:
        if kw.arg == keyword:
            return kw.value
    return None


VALIDATORS = (
    "require_param",
    "optional_param",
    "validate_vector3",
    "validate_color",
    "validate_enum",
    "validate_filepath",
)


def _validator_signatures() -> dict[str, tuple[list[str], int]]:
    """Helper name -> (parameter names in order, how many are required), from validation.py."""
    out: dict[str, tuple[list[str], int]] = {}
    for node in _parse(ADDON_DIR / "validation.py").body:
        if isinstance(node, ast.FunctionDef) and node.name in VALIDATORS:
            names = [a.arg for a in node.args.args]
            out[node.name] = (names, len(names) - len(node.args.defaults))
    return out


def _validator_aliases(tree: ast.Module) -> dict[str, str]:
    """Local alias -> validator name for ``from x import validate_enum as ve``."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname and alias.name in VALIDATORS:
                    out[alias.asname] = alias.name
    return out


def _signature_problems(node: ast.Call, names: list[str], required: int) -> list[str]:
    """What is wrong with a call against a helper's signature (empty when it binds)."""
    if any(isinstance(a, ast.Starred) for a in node.args) or any(
        k.arg is None for k in node.keywords
    ):
        return []
    problems = []
    given = set(names[: len(node.args)])
    if len(node.args) > len(names):
        problems.append("too many arguments")
    for kw in node.keywords:
        if kw.arg not in names:
            problems.append(f"unexpected keyword {kw.arg}")
        elif kw.arg in given:
            problems.append(f"repeated argument {kw.arg}")
        else:
            given.add(kw.arg)
    problems += [f"missing {n}" for n in names[:required] if n not in given]
    return problems


def check_validator_calls(addon_dir: Path = ADDON_DIR) -> list[str]:
    """Validator helper calls that do not match their signatures in validation.py.

    Covers ``require_param``, ``optional_param``, ``validate_vector3``,
    ``validate_color``, ``validate_enum`` and ``validate_filepath``. Also flags
    ``validate_enum`` with name/allowed swapped: a string ``allowed`` makes the
    enum comprehension iterate characters, so every real value is rejected.
    ``validate_filepath(value)`` without ``name`` raises TypeError.
    """
    signatures = _validator_signatures()
    out: list[str] = []
    for path in _python_files(addon_dir):
        rel = _rel(path, addon_dir)
        tree = _parse(path)
        aliases = _validator_aliases(tree)
        for node, symbol in _enclosing_symbols(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = _called_name(node)
            if isinstance(node.func, ast.Name):
                fname = aliases.get(fname, fname)
            if fname not in signatures:
                continue
            names, required = signatures[fname]
            first = _call_arg(node, 0, names[0])
            label = ast.unparse(first) if first is not None else "?"
            for problem in _signature_problems(node, names, required):
                out.append(f"{rel}::{symbol}: {fname} {problem}: {label}")
            if fname == "validate_enum":
                name_arg = _call_arg(node, 1, "name")
                allowed_arg = _call_arg(node, 2, "allowed")
                if name_arg is None or allowed_arg is None:
                    continue
                if isinstance(name_arg, (ast.List, ast.Tuple)) or (
                    _const_str(allowed_arg) is not None
                ):
                    swapped = next(
                        (
                            ast.unparse(a)
                            for a in (allowed_arg, name_arg)
                            if _const_str(a) is not None
                        ),
                        label,
                    )
                    out.append(f"{rel}::{symbol}: validate_enum swapped: {swapped}")
    return sorted(out)


def check_validate_filepath_result_used(addon_dir: Path = ADDON_DIR) -> list[str]:
    """``validate_filepath`` calls used as a bare statement.

    The helper expands ``~`` and makes the path absolute, so discarding the
    return value validates a path the handler then uses in its raw form.
    """
    out: list[str] = []
    for path in _python_files(addon_dir):
        rel = _rel(path, addon_dir)
        tree = _parse(path)
        aliases = _validator_aliases(tree)
        for node, symbol in _enclosing_symbols(tree):
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
                continue
            call = node.value
            fname = _called_name(call)
            if isinstance(call.func, ast.Name):
                fname = aliases.get(fname, fname)
            if fname != "validate_filepath":
                continue
            first = _call_arg(call, 0, "value")
            label = ast.unparse(first) if first is not None else "?"
            out.append(f"{rel}::{symbol}: validate_filepath result unused: {label}")
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
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("require_param", "optional_param")
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == pname
        ):
            key = _const_str(node.args[1])
            if key is not None:
                handled.add(id(node.args[0]))
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
    "validate_filepath_result_used": check_validate_filepath_result_used,
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


def _diff(expected: list[str], actual: list[str]) -> tuple[list[str], list[str]]:
    """Return (new, stale) entries as multisets, so count changes show up."""
    exp, act = Counter(expected), Counter(actual)
    return sorted((act - exp).elements()), sorted((exp - act).elements())


@pytest.mark.parametrize("name", sorted(CHECKS))
def test_against_baseline(name):
    new, stale = _diff(_load_baseline()[name], CHECKS[name]())
    assert not new, f"{name}: new violations (fix them):\n  " + "\n  ".join(new)
    assert not stale, (
        f"{name}: baseline entries no longer occur or occur fewer times "
        f"(remove them from static_gate_baseline.json):\n  " + "\n  ".join(stale)
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


def test_fixture_validate_filepath_result_used(tmp_path):
    addon = _make_addon(
        tmp_path,
        {
            "a.py": "def f(v):\n"
            "    validate_filepath(v, 'p')\n"
            "    p = validate_filepath(v, 'p')\n"
            "    return validate_filepath(v, 'p')\n",
        },
    )
    assert check_validate_filepath_result_used(addon) == [
        "addon/pkg/a.py::f: validate_filepath result unused: v"
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


def test_fixture_schema_params_require_param_reads_one_key(tmp_path):
    addon = _make_addon(
        tmp_path,
        {
            "handlers/__init__.py": _REGISTRY,
            "handlers/a.py": "class A:\n    def _handle_x(self, params):\n"
            "        require_param(params, 'size', int)\n"
            "        optional_param(params, 'bogus', 1)\n",
        },
    )
    tools = {"x": {"properties": {"size": {}, "unused": {}}}}
    assert check_schema_params(addon, tools) == [
        "addon/pkg/handlers/a.py::_handle_x: reads 'bogus' not in schema",
        "addon/pkg/handlers/a.py::_handle_x: schema 'unused' never read",
    ]


def test_fixture_tool_handler_parity(tmp_path):
    addon = _make_addon(tmp_path, {"handlers/__init__.py": _REGISTRY})
    tools = {"x": {}, "no_handler": {}}
    assert check_tool_handler_parity(addon, tools) == [
        "handler without tool: orphan",
        "tool without handler: no_handler",
    ]


def test_fixture_validator_keyword_and_aliased_calls(tmp_path):
    addon = _make_addon(
        tmp_path,
        {
            "a.py": "from ..validation import validate_enum as ve, validate_filepath as vf\n"
            "from ..validation import validate_enum\n"
            "def f(v):\n"
            "    validate_enum(v, name='mode', allowed='ABC')\n"
            "    validate_enum(v, allowed='mode', name=['A'])\n"
            "    validate_enum(v, name='mode', allowed=['A'])\n"
            "    ve(v, ['A'], 'size')\n"
            "    ve(v, 'size', ['A'])\n"
            "    vf(v)\n"
            "    vf(v, name='path')\n",
        },
    )
    assert check_validator_calls(addon) == [
        "addon/pkg/a.py::f: validate_enum swapped: 'ABC'",
        "addon/pkg/a.py::f: validate_enum swapped: 'mode'",
        "addon/pkg/a.py::f: validate_enum swapped: 'size'",
        "addon/pkg/a.py::f: validate_filepath missing name: v",
    ]


def test_fixture_validator_signatures(tmp_path):
    addon = _make_addon(
        tmp_path,
        {
            "a.py": "from ..validation import require_param as rp\n"
            "def f(p):\n"
            "    require_param(p, 'a')\n"
            "    require_param(p)\n"
            "    rp(p, 'a', int, 1)\n"
            "    optional_param(p, 'a', 1, int)\n"
            "    optional_param(p, 'a', default=1, param_type=int)\n"
            "    optional_param(p, 'a', dflt=1)\n"
            "    optional_param(p, 'a', 1, default=2)\n"
            "    validate_vector3(p)\n"
            "    validate_vector3(p, 'loc')\n"
            "    validate_color(p, name='c')\n"
            "    validate_color(p, 'c', True)\n"
            "    validate_enum(p, 'mode')\n"
            "    validate_filepath(p, 'x', True)\n"
            "    validate_filepath(*p)\n",
        },
    )
    assert check_validator_calls(addon) == [
        "addon/pkg/a.py::f: optional_param repeated argument default: p",
        "addon/pkg/a.py::f: optional_param unexpected keyword dflt: p",
        "addon/pkg/a.py::f: require_param missing name: p",
        "addon/pkg/a.py::f: require_param too many arguments: p",
        "addon/pkg/a.py::f: validate_color too many arguments: p",
        "addon/pkg/a.py::f: validate_enum missing allowed: p",
        "addon/pkg/a.py::f: validate_vector3 missing name: p",
    ]


def test_fixture_self_attributes_accepts_defined_members(tmp_path):
    addon = _make_addon(
        tmp_path,
        {
            "handlers/__init__.py": "",
            "handlers/a.py": "class A:\n"
            "    def __init__(self):\n        self._made = 1\n"
            "    @property\n    def _prop(self):\n        return 1\n"
            "    def run(self):\n"
            "        return self._made, self._prop, self._other()\n",
            "handlers/b.py": "class B:\n    def _other(self):\n        pass\n",
        },
    )
    assert check_self_attributes(addon) == []


def test_diff_reports_new_stale_and_count_changes():
    assert _diff(["a", "b"], ["a", "b"]) == ([], [])
    assert _diff(["a"], ["a", "b"]) == (["b"], [])
    assert _diff(["a", "b"], ["a"]) == ([], ["b"])
    assert _diff(["a"], ["a", "a"]) == (["a"], [])
    assert _diff(["a", "a"], ["a"]) == ([], ["a"])


def _module_frozenset(name: str) -> set[str]:
    """String members of a module-level ``name: frozenset[str] = frozenset({...})``."""
    for node in _parse(ADDON_DIR / "handlers" / "__init__.py").body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and target.id == name:
            return {
                n.value for n in ast.walk(node.value)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            }
    raise AssertionError(f"{name} not found in handlers/__init__.py")


def test_non_mutating_names_are_registered():
    non_mutating = _module_frozenset("NON_MUTATING")
    assert non_mutating
    assert sorted(non_mutating - set(_registered_handlers(ADDON_DIR))) == []


def test_undo_and_redo_never_push():
    non_mutating = _module_frozenset("NON_MUTATING")
    harness_only = _module_frozenset("HARNESS_ONLY")
    assert {"undo", "redo", "ping"} <= non_mutating
    assert {"harness_reset", "harness_exec"} <= harness_only


def test_read_tools_are_non_mutating():
    non_mutating = _module_frozenset("NON_MUTATING")
    reads = [
        name
        for name in _registered_handlers(ADDON_DIR)
        if name.endswith(("_get", "_list", "_info", "_status"))
        or name.startswith(("get_", "list_"))
    ]
    assert reads
    assert sorted(set(reads) - non_mutating) == []


if __name__ == "__main__":
    if "--write-baseline" in sys.argv:
        _write_baseline()
