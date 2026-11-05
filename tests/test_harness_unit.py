"""Unit tests for the pure-Python harness layer (no Blender)."""

import json
from pathlib import Path

import jsonschema
import pytest

from mcp_blender.server import TOOLS
from tests.harness.cases import build_cases, minimal_args
from tests.harness.catalog import load_tools
from tests.harness.classify import classify
from tests.harness.fixtures import (
    FALSE_PASS_DEFECTS,
    KNOWN_UNREACHED,
    SOFT_FAIL_ALLOWED,
    SOFT_FAIL_DEFECTS,
)


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


def test_compare_reports_each_difference_exactly():
    from tests.harness.driver import compare

    base = {
        "a#m": "PASS",
        "b#m": "BUG",
        "c#m": "BUG",
        "gone#m": "PASS",
        "same#m": "BUG",
    }
    now = {
        "a#m": "BUG",
        "b#m": "PASS",
        "c#m": "SOFT_FAIL",
        "new#m": "PASS",
        "same#m": "BUG",
    }
    assert compare(base, now) == [
        "worse: a#m PASS -> BUG",
        "improved: b#m BUG -> PASS",
        "improved: c#m BUG -> SOFT_FAIL",
        "removed: gone#m (was PASS)",
        "added: new#m PASS",
    ]


def test_compare_reports_same_severity_change():
    from tests.harness.driver import compare

    assert compare({"a#m": "CRASH"}, {"a#m": "HANG"}) == ["changed: a#m CRASH -> HANG"]
    assert compare({"a#m": "PASS"}, {"a#m": "EXPECTED"}) == ["changed: a#m PASS -> EXPECTED"]


def test_compare_unknown_class_fails_loudly():
    from tests.harness.driver import compare

    with pytest.raises(KeyError):
        compare({"a#m": "PASS"}, {"a#m": "WAT"})


def _cli(monkeypatch, tmp_path, baseline, results, *flags):
    import json

    from tests.harness import driver

    path = tmp_path / "base.json"
    path.write_text(json.dumps(baseline))
    (tmp_path / "out").mkdir()
    monkeypatch.setattr(driver, "run", lambda *a, **k: results)
    argv = ["--blender", "x", "--out", str(tmp_path / "out"), *flags]
    return driver.main(argv + ["--check-baseline", str(path)])


def test_check_baseline_exit_zero_when_identical(monkeypatch, tmp_path):
    same = {"a#m": "PASS", "b#m": "BUG"}
    assert _cli(monkeypatch, tmp_path, same, dict(same)) == 0


@pytest.mark.parametrize(
    "baseline,results",
    [
        ({"a#m": "PASS"}, {"a#m": "BUG"}),
        ({"a#m": "BUG"}, {"a#m": "PASS"}),
        ({"a#m": "CRASH"}, {"a#m": "HANG"}),
        ({"a#m": "PASS"}, {"a#m": "PASS", "b#m": "PASS"}),
        ({"a#m": "PASS", "b#m": "PASS"}, {"a#m": "PASS"}),
    ],
    ids=["worse", "improved", "changed", "added", "removed"],
)
def test_check_baseline_exit_one_on_difference(monkeypatch, tmp_path, baseline, results):
    assert _cli(monkeypatch, tmp_path, baseline, results) == 1


@pytest.mark.parametrize("flag", ["--write-baseline", "--check-baseline"])
def test_only_rejected_with_baseline_flags(tmp_path, flag):
    from tests.harness import driver

    with pytest.raises(SystemExit):
        driver.main(
            ["--blender", "x", "--out", str(tmp_path), "--only", "t", flag, str(tmp_path / "b")]
        )


def test_both_baseline_flags_rejected(tmp_path):
    from tests.harness import driver

    with pytest.raises(SystemExit):
        driver.main(
            ["--blender", "x", "--out", str(tmp_path)]
            + ["--write-baseline", str(tmp_path / "a"), "--check-baseline", str(tmp_path / "b")]
        )


def test_a_crash_that_passes_alone_is_recorded_as_a_session_crash(tmp_path):
    from tests.harness import driver
    from tests.harness.cases import Case

    cases = [Case("a#m", "a", "minimal"), Case("b#m", "b", "minimal"), Case("c#m", "c", "minimal")]
    result = {"a#m": "CRASH", "b#m": "CRASH", "c#m": "PASS"}
    alone = {"a#m": "PASS", "b#m": "CRASH"}
    calls = []

    def fake_run(blender, cases, out_dir):
        calls.append([c.id for c in cases])
        return {c.id: alone[c.id] for c in cases}

    session = driver.retry_crashes("x", cases, result, tmp_path, runner=fake_run)
    assert calls == [["a#m"], ["b#m"]]
    assert session == {"a#m": "PASS"}
    assert result == {"a#m": "PASS", "b#m": "CRASH", "c#m": "PASS"}


def test_retry_crashes_flag_keeps_a_session_crash_out_of_the_diff(monkeypatch, tmp_path, capsys):
    import json

    from tests.harness import driver
    from tests.harness.cases import build_cases
    from tests.harness.catalog import load_tools

    ids = [c.id for c in build_cases(load_tools())]
    base = tmp_path / "base.json"
    base.write_text(json.dumps(dict.fromkeys(ids, "PASS")))

    def fake_run(blender, cases, out_dir):
        if len(cases) == 1:
            return {cases[0].id: "PASS"}
        return {c.id: "CRASH" if i == 0 else "PASS" for i, c in enumerate(cases)}

    monkeypatch.setattr(driver, "run", fake_run)
    (tmp_path / "out").mkdir()
    argv = ["--blender", "x", "--out", str(tmp_path / "out"), "--check-baseline", str(base)]
    assert driver.main(argv) == 1
    assert driver.main(argv + ["--retry-crashes"]) == 0
    assert f"session crash: {ids[0]} CRASH in the full run, PASS alone" in capsys.readouterr().err
    saved = json.loads((tmp_path / "out" / "session_crashes.json").read_text())
    assert saved == {ids[0]: "PASS"}


def _load_fetch():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_blender.py"
    spec = importlib.util.spec_from_file_location("fetch_blender", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_release(tmp_path, mod, monkeypatch):
    import hashlib
    import io
    import tarfile

    top = "blender-9.9.9-linux-x64"
    cache = tmp_path / "cache"
    cache.mkdir()
    tarball = cache / f"{top}.tar.xz"
    with tarfile.open(tarball, "w:xz") as tar:
        for name, data in (("blender", b"bin"), ("lib/data", b"data")):
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))
    monkeypatch.setattr(mod, "CACHE", cache)
    monkeypatch.setitem(mod.SHA256, "9.9.9", hashlib.sha256(tarball.read_bytes()).hexdigest())
    return top


def test_fetch_extracts_and_reuses(tmp_path, monkeypatch):
    mod = _load_fetch()
    top = _fake_release(tmp_path, mod, monkeypatch)
    dest = tmp_path / "dest"
    binary = mod.fetch("9.9.9", dest)
    assert binary == dest / top / "blender"
    assert (dest / top / "lib" / "data").read_bytes() == b"data"
    assert mod.fetch("9.9.9", dest) == binary


def test_fetch_ignores_partial_extraction(tmp_path, monkeypatch):
    import tarfile

    mod = _load_fetch()
    top = _fake_release(tmp_path, mod, monkeypatch)
    dest = tmp_path / "dest"
    real = tarfile.TarFile.extractall

    def interrupted(self, path=".", *args, **kwargs):
        member = self.getmembers()[0]
        self.extract(member, path)
        raise KeyboardInterrupt

    monkeypatch.setattr(tarfile.TarFile, "extractall", interrupted)
    with pytest.raises(KeyboardInterrupt):
        mod.fetch("9.9.9", dest)
    assert not (dest / top).exists()

    monkeypatch.setattr(tarfile.TarFile, "extractall", real)
    binary = mod.fetch("9.9.9", dest)
    assert (dest / top / "lib" / "data").exists()
    assert binary == dest / top / "blender"


def test_baseline_file_is_sorted_with_trailing_newline(tmp_path):
    from tests.harness.driver import write_baseline

    path = tmp_path / "b.json"
    write_baseline(path, {"z#m": "BUG", "a#m": "PASS"})
    assert path.read_text() == '{\n  "a#m": "PASS",\n  "z#m": "BUG"\n}\n'


BASELINES = Path(__file__).parent / "harness" / "baselines"
BASELINE_FILES = tuple(sorted(f.name for f in BASELINES.glob("blender-*.json")))


def test_every_supported_series_has_a_baseline():
    series = ("4.2", "4.3", "4.4", "4.5", "5.0", "5.1", "5.2")
    assert BASELINE_FILES == tuple(f"blender-{s}.json" for s in series)


def _baseline(name):
    return json.loads((BASELINES / name).read_text())


def _soft_fail_tools():
    return {
        case_id.split("#")[0]
        for name in BASELINE_FILES
        for case_id, cls in _baseline(name).items()
        if cls == "SOFT_FAIL"
    }


def test_every_soft_fail_tool_is_accounted_for():
    known = set(KNOWN_UNREACHED) | set(SOFT_FAIL_ALLOWED) | set(SOFT_FAIL_DEFECTS)
    missing = sorted(_soft_fail_tools() - known)
    assert not missing, (
        f"SOFT_FAIL tools not in KNOWN_UNREACHED, SOFT_FAIL_ALLOWED or SOFT_FAIL_DEFECTS: {missing}"
    )


def test_soft_fail_tables_have_no_dead_rows():
    dead = sorted((set(SOFT_FAIL_ALLOWED) | set(SOFT_FAIL_DEFECTS)) - _soft_fail_tools())
    assert not dead, f"rows with no SOFT_FAIL line in any baseline: {dead}"


def test_defect_tables_are_empty():
    # M3 ends when no tool hides a defect behind SOFT_FAIL or PASS. The dicts stay
    # so a later task can record one again.
    assert SOFT_FAIL_DEFECTS == {}
    assert FALSE_PASS_DEFECTS == {}


def test_soft_fail_tables_are_disjoint_and_defects_are_real_tools():
    assert not set(SOFT_FAIL_ALLOWED) & set(SOFT_FAIL_DEFECTS)
    tools = set(load_tools())
    for table in (SOFT_FAIL_ALLOWED, SOFT_FAIL_DEFECTS, FALSE_PASS_DEFECTS):
        assert set(table) <= tools, sorted(set(table) - tools)


@pytest.mark.parametrize("name", BASELINE_FILES)
def test_baseline_ids_match_generated_cases(name):
    ids = {c.id for c in build_cases(load_tools())}
    recorded = set(_baseline(name))
    missing, extra = sorted(ids - recorded), sorted(recorded - ids)
    assert not (missing or extra), (
        f"{name}: cases missing from the baseline {missing[:10]}, "
        f"cases in the baseline that no longer exist {extra[:10]}"
    )


def test_enum_overrides_reach_the_generated_case():
    from tests.harness.fixtures import ENUM_OVERRIDES

    assert ENUM_OVERRIDES
    cases = {c.id: c for c in build_cases(load_tools())}
    for (tool, param, value), extra in ENUM_OVERRIDES.items():
        case = cases[f"{tool}#enum:{param}={value}"]
        assert {k: case.params[k] for k in extra} == extra
        assert case.params[param] == value


def _crashing_run(monkeypatch, crashed):
    from tests.harness import driver
    from tests.harness.cases import build_cases
    from tests.harness.catalog import load_tools

    ids = [c.id for c in build_cases(load_tools())]
    marked = set(ids[:crashed])

    def fake_run(blender, cases, out_dir):
        if len(cases) == 1:
            return {cases[0].id: "PASS"}
        return {c.id: "CRASH" if c.id in marked else "PASS" for c in cases}

    monkeypatch.setattr(driver, "run", fake_run)
    return ids


def test_retry_crashes_passes_at_the_cap(monkeypatch, tmp_path, capsys):
    import json

    from tests.harness import driver

    ids = _crashing_run(monkeypatch, driver.MAX_SESSION_CRASHES)
    base = tmp_path / "base.json"
    base.write_text(json.dumps(dict.fromkeys(ids, "PASS")))
    out = tmp_path / "out"
    out.mkdir()
    argv = ["--blender", "x", "--out", str(out), "--check-baseline", str(base), "--retry-crashes"]
    assert driver.main(argv) == 0


def test_retry_crashes_fails_past_the_cap(monkeypatch, tmp_path, capsys):
    import json

    from tests.harness import driver

    assert driver.MAX_SESSION_CRASHES == 3

    ids = _crashing_run(monkeypatch, driver.MAX_SESSION_CRASHES + 1)
    base = tmp_path / "base.json"
    base.write_text(json.dumps(dict.fromkeys(ids, "PASS")))
    out = tmp_path / "out"
    out.mkdir()
    argv = ["--blender", "x", "--out", str(out), "--check-baseline", str(base), "--retry-crashes"]
    assert driver.main(argv) == 1
    assert "more than 3: " in capsys.readouterr().err
    # the results are still written, so the run can be inspected
    assert (out / "results.json").exists()
