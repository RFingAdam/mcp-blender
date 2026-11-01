"""Unit tests for the pure-Python harness layer (no Blender)."""

import jsonschema
import pytest

from mcp_blender.server import TOOLS
from tests.harness.cases import build_cases, minimal_args
from tests.harness.catalog import load_tools
from tests.harness.classify import classify


def test_load_tools_has_all():
    tools = load_tools()
    assert len(tools) == len(TOOLS)
    assert all(not k.startswith("blender_") for k in tools)


def test_every_required_param_resolves():
    for name, schema in load_tools().items():
        args = minimal_args(name, schema)
        for req in schema.get("required", []):
            assert req in args, f"{name} missing {req}"


def test_case_ids_unique_and_stable():
    tools = load_tools()
    a = [c.id for c in build_cases(tools)]
    b = [c.id for c in build_cases(tools)]
    assert a == b
    assert len(a) == len(set(a))


def test_invalid_pass_only_with_required():
    tools = load_tools()
    for c in build_cases(tools):
        if c.pass_name == "invalid":
            assert c.params == {}
            assert tools[c.tool].get("required")
    with_invalid = {c.tool for c in build_cases(tools) if c.pass_name == "invalid"}
    for name, schema in tools.items():
        assert (name in with_invalid) == bool(schema.get("required"))


def test_enum_sweep_covers_every_value():
    tools = load_tools()
    cases = [c for c in build_cases(tools) if c.pass_name == "enum"]
    for name, schema in tools.items():
        for param, spec in schema.get("properties", {}).items():
            for value in spec.get("enum", []):
                hits = [
                    c for c in cases if c.tool == name and c.id == f"{name}#enum:{param}={value}"
                ]
                assert len(hits) == 1
                assert hits[0].params[param] == value


def _exc(t, msg=""):
    return {"status": "exception", "type": t, "message": msg}


@pytest.mark.parametrize(
    "case_pass,outcome,expected",
    [
        ("minimal", {"status": "ok", "result": {"x": 1}}, "PASS"),
        ("minimal", {"status": "ok", "result": {"error": "x"}}, "SOFT_FAIL"),
        ("minimal", {"status": "ok", "result": {"success": False}}, "SOFT_FAIL"),
        ("minimal", {"status": "ok", "result": {"success": True, "error": None}}, "PASS"),
        ("minimal", {"status": "ok", "result": {"error": ""}}, "PASS"),
        ("minimal", _exc("ValidationError"), "BUG"),
        ("invalid", _exc("ValidationError"), "EXPECTED"),
        ("invalid", _exc("KeyError"), "BUG"),
        ("invalid", {"status": "ok", "result": {}}, "BUG"),
        (
            "minimal",
            {"status": "ok", "result": {"error": "x: harness: network disabled"}},
            "EXPECTED",
        ),
        ("invalid", {"status": "ok", "result": {"error": "harness: network disabled"}}, "EXPECTED"),
        ("minimal", {"status": "ok", "result": {"error": {"code": 1}}}, "SOFT_FAIL"),
        (
            "minimal",
            {"status": "ok", "result": {"error": ["harness: network disabled"]}},
            "EXPECTED",
        ),
        ("minimal", {"status": "ok", "result": {"error": 5}}, "SOFT_FAIL"),
        ("minimal", _exc("ImportError"), "BUG"),
        ("minimal", _exc("AttributeError"), "BUG"),
        ("minimal", _exc("TypeError"), "BUG"),
        ("minimal", _exc("NameError"), "BUG"),
        ("minimal", _exc("RuntimeError", "harness: network disabled"), "EXPECTED"),
        ("invalid", _exc("RuntimeError", "harness: network disabled"), "EXPECTED"),
        ("minimal", _exc("RuntimeError", "context is incorrect"), "BUG"),
        ("enum", _exc("ValueError"), "BUG"),
        ("enum", {"status": "ok", "result": {"x": 1}}, "PASS"),
        ("minimal", _exc("SystemExit", "1"), "CRASH"),
        ("invalid", _exc("SystemExit"), "CRASH"),
        ("minimal", {"status": "hang"}, "HANG"),
        ("minimal", None, "CRASH"),
    ],
)
def test_classify_table(case_pass, outcome, expected):
    assert classify(case_pass, outcome) == expected


def _strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)


def test_generated_args_satisfy_schema():
    import re

    tools = load_tools()
    for c in build_cases(tools):
        if c.pass_name == "invalid":
            continue
        try:
            jsonschema.validate(c.params, tools[c.tool])
        except jsonschema.ValidationError as e:
            pytest.fail(f"{c.id}: {e.message}")
        for s in _strings(c.params):
            assert set(re.findall(r"\{[^}]*\}", s)) <= {"{TMP}"}, (c.id, s)


def test_compare_identical_is_empty():
    from tests.harness.driver import compare

    assert compare({"a#minimal": "PASS"}, {"a#minimal": "PASS"}) == []


def test_compare_reports_worse_improved_added_removed():
    from tests.harness.driver import compare

    base = {"a#m": "PASS", "b#m": "BUG", "gone#m": "PASS", "same#m": "BUG"}
    now = {"a#m": "BUG", "b#m": "PASS", "new#m": "PASS", "same#m": "BUG"}
    lines = compare(base, now)
    assert len(lines) == 4
    text = "\n".join(lines)
    assert "a#m" in text and "worse" in text and "PASS -> BUG" in text
    assert "b#m" in text and "improved" in text and "BUG -> PASS" in text
    assert "new#m" in text and "added" in text
    assert "gone#m" in text and "removed" in text
    assert "same#m" not in text


def test_baseline_file_is_sorted_with_trailing_newline(tmp_path):
    from tests.harness.driver import write_baseline

    path = tmp_path / "b.json"
    write_baseline(path, {"z#m": "BUG", "a#m": "PASS"})
    assert path.read_text() == '{\n  "a#m": "PASS",\n  "z#m": "BUG"\n}\n'
