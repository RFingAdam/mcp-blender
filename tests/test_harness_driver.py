"""Driver tests against a fake Blender executable."""

from __future__ import annotations

import json
import os
import stat
import textwrap
import time
from pathlib import Path

import pytest

from tests.harness import driver
from tests.harness.cases import Case

FAKE = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, signal, sys, time

    if "--version" in sys.argv:
        print(os.environ.get("FAKE_VERSION", "Blender 4.5.15"))
        sys.exit(0)
    args = sys.argv[sys.argv.index("--") + 1:]
    opt = dict(zip(args[::2], args[1::2]))
    cases = json.load(open(opt["--cases"]))
    out = open(opt["--out"], "a")

    def emit(obj):
        out.write(json.dumps(obj) + "\\n")
        out.flush()
        os.fsync(out.fileno())

    open(os.path.join(os.path.dirname(opt["--out"]), "seen_tmpdir"), "w").write(
        os.environ.get("TMPDIR", "") + "|" + opt["--tmp"] + "|" + str(os.path.exists(opt["--tmp"] + "/in.png"))
    )
    open(os.path.join(os.path.dirname(opt["--out"]), "seen_user"), "w").write(
        os.environ.get("BLENDER_USER_RESOURCES", "")
    )
    for i in range(int(opt["--start"]), len(cases)):
        mode = cases[i]["params"].get("fake", "ok")
        if mode == "die_before_start":
            os._exit(1)
        emit({"i": i, "event": "start"})
        print("garbage {not json", flush=True)
        if mode == "crash":
            os._exit(1)
        if mode == "crash_file":
            open(os.path.join(os.environ["TMPDIR"], "scene.crash.txt"), "w").write("trace")
            os._exit(1)
        if mode == "pid_hang":
            open(os.path.join(os.path.dirname(opt["--out"]), "pid"), "w").write(str(os.getpid()))
            time.sleep(60)
        if mode == "exit":
            sys.exit(3)
        if mode == "hang":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(60)
        if mode == "late_end":
            def finish_on_term(*_):
                emit({"i": i, "event": "end", "outcome": {"status": "ok", "result": {}}})
                os._exit(0)

            signal.signal(signal.SIGTERM, finish_on_term)
            time.sleep(60)
        emit({"i": i, "event": "end", "outcome": {"status": "ok", "result": {"n": i}}})
        if mode == "die_after":
            os._exit(1)
        if mode == "hang_after":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(60)
        if mode == "exit0_after":
            sys.exit(0)
        if mode == "exit139_after":
            os._exit(139)
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


def test_fake_blender_exit_is_crash(fake_blender, tmp_path):
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


def test_tmp_dir_lives_under_out_and_is_removed(fake_blender, tmp_path):
    out = tmp_path / "out"
    driver.run(fake_blender, make_cases("ok"), out)
    tmpdir, tmp_arg, has_asset = (out / "seen_tmpdir").read_text().split("|")
    assert tmpdir == tmp_arg == str(out / "tmp")
    assert has_asset == "True"
    assert not (out / "tmp").exists()


def test_death_between_cases_blames_last_finished(fake_blender, tmp_path):
    result = driver.run(fake_blender, make_cases("ok", "die_after", "ok"), tmp_path / "out")
    assert result == {"t0#minimal": "PASS", "t1#minimal": "CRASH", "t2#minimal": "PASS"}


def test_end_written_during_the_kill_does_not_undo_a_hang(fake_blender, tmp_path):
    result = driver.run(fake_blender, make_cases("late_end", "ok"), tmp_path / "out", timeout=1)
    assert result == {"t0#minimal": "HANG", "t1#minimal": "PASS"}


def test_hang_between_cases_blames_last_finished(fake_blender, tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "STARTUP_TIMEOUT", 1.0)
    result = driver.run(
        fake_blender, make_cases("ok", "hang_after", "ok"), tmp_path / "out", timeout=1
    )
    assert result == {"t0#minimal": "PASS", "t1#minimal": "HANG", "t2#minimal": "PASS"}


def test_clean_exit_before_last_case_is_crash(fake_blender, tmp_path):
    result = driver.run(fake_blender, make_cases("ok", "exit0_after", "ok"), tmp_path / "out")
    assert result == {"t0#minimal": "PASS", "t1#minimal": "CRASH", "t2#minimal": "PASS"}


def test_nonzero_exit_after_last_case_is_crash(fake_blender, tmp_path):
    result = driver.run(fake_blender, make_cases("ok", "exit139_after"), tmp_path / "out")
    assert result == {"t0#minimal": "PASS", "t1#minimal": "CRASH"}


def test_death_at_startup_blames_next_case(fake_blender, tmp_path):
    cases = make_cases("die_before_start", "ok", "die_after", "die_before_start", "ok")
    result = driver.run(fake_blender, cases, tmp_path / "out")
    assert list(result.values()) == ["CRASH", "PASS", "CRASH", "CRASH", "PASS"]


def test_interrupt_does_not_orphan_blender(fake_blender, tmp_path, monkeypatch):
    out = tmp_path / "out"
    real = driver._read_events

    def interrupt_once_started(path, offset):
        for _ in range(200):
            if (out / "pid").exists() and (out / "pid").read_text():
                raise KeyboardInterrupt
            time.sleep(0.05)
        return real(path, offset)

    monkeypatch.setattr(driver, "_read_events", interrupt_once_started)
    with pytest.raises(KeyboardInterrupt):
        driver.run(fake_blender, make_cases("pid_hang"), out)
    pid = int((out / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_crash_dump_is_kept_under_blamed_index(fake_blender, tmp_path):
    out = tmp_path / "out"
    result = driver.run(fake_blender, make_cases("ok", "crash_file", "ok"), out)
    assert result["t1#minimal"] == "CRASH"
    assert (out / "crash-1.txt").read_text() == "trace"
    assert not (out / "tmp").exists()


def _stub_catalog(monkeypatch):
    from tests.harness import cases, catalog

    monkeypatch.setattr(catalog, "load_tools", lambda: [])
    monkeypatch.setattr(cases, "build_cases", lambda tools: make_cases("ok"))


def test_write_baseline_rejects_wrong_version_before_running(
    fake_blender, tmp_path, monkeypatch, capsys
):
    _stub_catalog(monkeypatch)
    monkeypatch.setenv("FAKE_VERSION", "Blender 4.2.23")
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        driver.main(
            ["--blender", fake_blender, "--out", str(out),
             "--write-baseline", str(tmp_path / "blender-4.5.json")]
        )  # fmt: skip
    assert exc.value.code == 2
    assert "4.5" in capsys.readouterr().err
    assert not out.exists()


def test_write_baseline_accepts_matching_and_unmatched_names(fake_blender, tmp_path, monkeypatch):
    _stub_catalog(monkeypatch)
    for name in ("blender-4.5.json", "anything.json"):
        target = tmp_path / name
        code = driver.main(
            ["--blender", fake_blender, "--out", str(tmp_path / "o" / name),
             "--write-baseline", str(target)]
        )  # fmt: skip
        assert code == 0
        assert json.loads(target.read_text()) == {"t0#minimal": "PASS"}


def test_check_baseline_diff_points_at_contributing(fake_blender, tmp_path, monkeypatch, capsys):
    _stub_catalog(monkeypatch)
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"t0#minimal": "CRASH"}))
    code = driver.main(
        ["--blender", fake_blender, "--out", str(tmp_path / "o"), "--check-baseline", str(base)]
    )
    err = capsys.readouterr().err.strip().splitlines()
    assert code == 1
    assert err[0].startswith("improved:")
    assert "CONTRIBUTING.md" in err[-1] and "Truth harness" in err[-1]


def test_blender_env_keeps_user_files_under_the_run_tmp_dir(tmp_path):
    from tests.harness.env import blender_env

    env = blender_env(tmp_path / "tmp")
    user = Path(env["BLENDER_USER_RESOURCES"])
    assert user.is_dir()
    assert (tmp_path / "tmp") in user.parents
    assert env["TMPDIR"] == str(tmp_path / "tmp")
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_blender_env_overrides_a_developers_own_resource_dir(tmp_path, monkeypatch):
    from tests.harness.env import blender_env

    monkeypatch.setenv("BLENDER_USER_RESOURCES", "/home/dev/blender")
    monkeypatch.setenv("BLENDER_USER_CONFIG", "/home/dev/config")
    env = blender_env(tmp_path)
    assert env["BLENDER_USER_RESOURCES"].startswith(str(tmp_path))
    assert "BLENDER_USER_CONFIG" not in env


def test_driver_blender_sees_the_resource_dir_under_its_tmp_dir(fake_blender, tmp_path):
    out = tmp_path / "out"
    driver.run(fake_blender, make_cases("ok"), out)
    seen = (out / "seen_user").read_text()
    assert seen.startswith(str(out / "tmp"))
