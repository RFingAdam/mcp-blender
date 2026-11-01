"""Driver tests against a fake Blender executable."""

from __future__ import annotations

import stat
import textwrap
from pathlib import Path

import pytest

from tests.harness import driver
from tests.harness.cases import Case

FAKE = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, signal, sys, time

    args = sys.argv[sys.argv.index("--") + 1:]
    opt = dict(zip(args[::2], args[1::2]))
    cases = json.load(open(opt["--cases"]))
    out = open(opt["--out"], "a")

    def emit(obj):
        out.write(json.dumps(obj) + "\\n")
        out.flush()
        os.fsync(out.fileno())

    for i in range(int(opt["--start"]), len(cases)):
        mode = cases[i]["params"].get("fake", "ok")
        emit({"i": i, "event": "start"})
        print("garbage {not json", flush=True)
        if mode == "crash":
            os._exit(1)
        if mode == "exit":
            sys.exit(3)
        if mode == "hang":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(60)
        emit({"i": i, "event": "end", "outcome": {"status": "ok", "result": {"n": i}}})
    """
)


@pytest.fixture
def fake_blender(tmp_path: Path) -> str:
    path = tmp_path / "fake_blender.py"
    path.write_text(FAKE)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def make_cases(*modes: str) -> list[Case]:
    return [Case(f"t{n}#minimal", f"t{n}", "minimal", {"fake": m}) for n, m in enumerate(modes)]


def test_all_cases_complete(fake_blender, tmp_path):
    result = driver.run(fake_blender, make_cases("ok", "ok", "ok"), tmp_path / "out")
    assert result == {"t0#minimal": "PASS", "t1#minimal": "PASS", "t2#minimal": "PASS"}


def test_crash_resumes(fake_blender, tmp_path):
    result = driver.run(fake_blender, make_cases("ok", "crash", "ok"), tmp_path / "out")
    assert result == {"t0#minimal": "PASS", "t1#minimal": "CRASH", "t2#minimal": "PASS"}


def test_sys_exit_is_crash(fake_blender, tmp_path):
    result = driver.run(fake_blender, make_cases("exit", "ok"), tmp_path / "out")
    assert result == {"t0#minimal": "CRASH", "t1#minimal": "PASS"}


def test_hang_resumes(fake_blender, tmp_path):
    result = driver.run(fake_blender, make_cases("ok", "hang", "ok"), tmp_path / "out", timeout=1)
    assert result == {"t0#minimal": "PASS", "t1#minimal": "HANG", "t2#minimal": "PASS"}


def test_stdout_noise_ignored(fake_blender, tmp_path):
    result = driver.run(fake_blender, make_cases("ok", "ok"), tmp_path / "out")
    assert set(result.values()) == {"PASS"}


def test_only_filters_by_tool(fake_blender, tmp_path):
    cases = make_cases("ok", "ok", "ok")
    assert [c.tool for c in driver.select(cases, ["t1"])] == ["t1"]
    assert driver.select(cases, []) == cases
