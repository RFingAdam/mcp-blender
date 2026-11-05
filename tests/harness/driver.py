"""Drive Blender through the harness cases, resuming after crashes and hangs."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import assets
from .cases import Case
from .classify import classify
from .env import blender_env

SLOW_TOOLS = frozenset(
    {
        "ai_refine",
        "ai_texture_from_render",
        "bake_curvature",
        "bake_from_multires",
        "bake_highpoly_to_lowpoly",
        "bake_id_map",
        "bake_pbr_batch",
        "bake_to_vertex_colors",
        "material_preview_render",
        "physics_cloth_add",
        "physics_fluid_quick",
        "physics_simulate",
        "render_animation",
        "render_image",
        "render_multi_angle",
        "render_screenshot",
    }
)
SLOW_TIMEOUT = 180.0
STARTUP_TIMEOUT = 120.0
KILL_GRACE = 3.0
POLL = 0.05
RUNNER = Path(__file__).with_name("runner.py")
DIFF_HINT = "see CONTRIBUTING.md, section 'Truth harness', for how to read and record these lines"


def select(cases: list[Case], only: list[str]) -> list[Case]:
    return [c for c in cases if c.tool in only] if only else cases


def _read_events(path: Path, offset: int) -> tuple[list[dict], int]:
    """Parse complete JSONL lines after offset; leave a partial last line unread."""
    with path.open("rb") as fh:
        fh.seek(offset)
        data = fh.read()
    events = []
    consumed = 0
    for raw in data.splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            break
        consumed += len(raw)
        try:
            events.append(json.loads(raw))
        except ValueError:
            pass
    return events, offset + consumed


def _terminate(proc: subprocess.Popen) -> None:
    """SIGTERM the process group, escalate to SIGKILL after a grace period."""
    for sig, wait in ((signal.SIGTERM, KILL_GRACE), (signal.SIGKILL, None)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(timeout=wait)
            break
        except subprocess.TimeoutExpired:
            continue
    proc.wait()


def _keep_crash_dumps(tmp_dir: Path, out_dir: Path, index: int) -> None:
    """Move Blender's crash backtraces out of the temp dir before it is deleted."""
    for n, dump in enumerate(sorted(tmp_dir.glob("*.crash.txt"))):
        suffix = "" if n == 0 else f"-{n}"
        shutil.move(str(dump), out_dir / f"crash-{index}{suffix}.txt")


def run(blender: str, cases: list[Case], out_dir: Path, timeout: float = 30.0) -> dict[str, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_dir / "tmp"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir()
    try:
        assets.prepare(tmp_dir)
        return _run(blender, cases, out_dir, tmp_dir, timeout)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _run(
    blender: str, cases: list[Case], out_dir: Path, tmp_dir: Path, timeout: float
) -> dict[str, str]:
    cases_file = out_dir / "cases.json"
    events_file = out_dir / "events.jsonl"
    log_file = out_dir / "blender.log"
    scene_file = out_dir / "scene.blend"
    cases_file.write_text(json.dumps([dataclasses.asdict(c) for c in cases]))
    scene_file.unlink(missing_ok=True)
    events_file.write_bytes(b"")
    log_file.write_bytes(b"")

    env = blender_env(tmp_dir)
    outcomes: dict[int, dict | None] = {}
    offset = 0
    nxt = 0
    while nxt < len(cases):
        cmd = [
            blender, "-b", "--factory-startup", "--python", str(RUNNER), "--",
            "--cases", str(cases_file), "--out", str(events_file),
            "--scene", str(scene_file), "--start", str(nxt), "--tmp", str(tmp_dir),
        ]  # fmt: skip
        with log_file.open("ab") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=log, env=env, start_new_session=True)
        current: int | None = None
        last_end: int | None = None
        timed_out = False
        try:
            deadline = time.monotonic() + max(timeout, STARTUP_TIMEOUT)
            while True:
                events, offset = _read_events(events_file, offset)
                for ev in events:
                    if ev.get("event") == "start":
                        current = ev["i"]
                        limit = SLOW_TIMEOUT if cases[current].tool in SLOW_TOOLS else timeout
                        deadline = time.monotonic() + limit
                    elif ev.get("event") == "end":
                        outcomes[ev["i"]] = ev["outcome"]
                        current, last_end = None, ev["i"]
                        deadline = time.monotonic() + max(timeout, STARTUP_TIMEOUT)
                if proc.poll() is not None:
                    events, offset = _read_events(events_file, offset)
                    for ev in events:
                        if ev.get("event") == "start":
                            current = ev["i"]
                        elif ev.get("event") == "end":
                            outcomes[ev["i"]] = ev["outcome"]
                            current, last_end = None, ev["i"]
                    break
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                time.sleep(POLL)
        finally:
            if proc.poll() is None:
                _terminate(proc)
        if timed_out:
            # The deadline decided this case. An end written during the kill must not reach
            # the next spawn, where it would overwrite the HANG.
            _, offset = _read_events(events_file, offset)
        # A start without an end is the culprit. Otherwise, if the spawn ended badly
        # (timeout, nonzero exit, or stopped before the last case), blame the last case
        # that finished, or the next case when nothing ran at all.
        reached_end = max(outcomes, default=-1) + 1 >= len(cases)
        failed = timed_out or proc.returncode != 0 or not reached_end
        if current is None and failed:
            current = last_end if last_end is not None else nxt
        if current is not None:
            outcomes[current] = {"status": "hang"} if timed_out else None
        _keep_crash_dumps(tmp_dir, out_dir, current if current is not None else nxt)
        nxt = max(outcomes, default=-1) + 1

    return {c.id: classify(c.pass_name, outcomes.get(i)) for i, c in enumerate(cases)}


def retry_crashes(
    blender: str, cases: list[Case], result: dict[str, str], out_dir: Path, runner=None
) -> dict[str, str]:
    """Rerun each crashed case alone in a fresh Blender, and return the ones that pass alone.

    Blender 4.2 and 4.3 sometimes crash inside Blender late in a full run, on a different heavy
    case each time, and the case passes when run alone. A case that also crashes alone keeps
    CRASH. The others take their class from the solo run, so ``result`` is updated in place.
    """
    runner = runner or run
    session = {}
    for case in cases:
        if result.get(case.id) != "CRASH":
            continue
        alone = runner(blender, [case], Path(out_dir) / re.sub(r"[^\w.=-]", "_", case.id))
        if alone[case.id] != "CRASH":
            result[case.id] = session[case.id] = alone[case.id]
    return session


SEVERITY = {"PASS": 0, "EXPECTED": 0, "SOFT_FAIL": 1, "BUG": 2, "FAIL": 2, "CRASH": 3, "HANG": 3}


def compare(baseline: dict[str, str], results: dict[str, str]) -> list[str]:
    """One line per difference between a baseline and a fresh run."""
    lines = []
    for case_id in sorted(baseline.keys() | results.keys()):
        old, new = baseline.get(case_id), results.get(case_id)
        if old == new:
            continue
        if old is None:
            lines.append(f"added: {case_id} {new}")
        elif new is None:
            lines.append(f"removed: {case_id} (was {old})")
        elif SEVERITY[new] > SEVERITY[old]:
            lines.append(f"worse: {case_id} {old} -> {new}")
        elif SEVERITY[new] < SEVERITY[old]:
            lines.append(f"improved: {case_id} {old} -> {new}")
        else:
            lines.append(f"changed: {case_id} {old} -> {new}")
    return lines


def write_baseline(path: Path, results: dict[str, str]) -> None:
    Path(path).write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--only", action="append", default=[], metavar="TOOL")
    parser.add_argument("--write-baseline", type=Path, metavar="FILE")
    parser.add_argument("--check-baseline", type=Path, metavar="FILE")
    parser.add_argument(
        "--retry-crashes",
        action="store_true",
        help="rerun each crashed case alone; one that passes alone is a session crash",
    )
    args = parser.parse_args(argv)
    if args.write_baseline and args.check_baseline:
        parser.error("--write-baseline and --check-baseline are mutually exclusive")
    if args.only and (args.write_baseline or args.check_baseline):
        parser.error("--only cannot be combined with a baseline flag (partial run)")

    named = args.write_baseline and re.fullmatch(
        r"blender-(\d+\.\d+)\.json", args.write_baseline.name
    )
    if named:
        from .socket_lane import _blender_series

        got = _blender_series(args.blender)
        if got != named.group(1):
            parser.error(f"{args.write_baseline.name} is for Blender {named.group(1)}, got {got}")

    from .cases import build_cases
    from .catalog import load_tools

    cases = select(build_cases(load_tools()), args.only)
    result = run(args.blender, cases, args.out)
    if args.retry_crashes:
        session = retry_crashes(args.blender, cases, result, args.out / "retry")
        (args.out / "session_crashes.json").write_text(json.dumps(session, indent=2))
        for case_id, alone in sorted(session.items()):
            print(f"session crash: {case_id} CRASH in the full run, {alone} alone", file=sys.stderr)
    (args.out / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    for case_id in sorted(result):
        print(f"{case_id} {result[case_id]}")
    if args.write_baseline:
        write_baseline(args.write_baseline, result)
    if args.check_baseline:
        diff = compare(json.loads(args.check_baseline.read_text()), result)
        for line in diff:
            print(line, file=sys.stderr)
        if diff:
            print(DIFF_HINT, file=sys.stderr)
        return 1 if diff else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
