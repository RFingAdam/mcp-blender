"""Drive a real GUI Blender through the real addon socket and check postconditions.

Stdlib only: the lane speaks the newline-delimited JSON protocol itself, so it fails
if the protocol breaks. A tool that reports success without doing the work is caught
by checking the scene (or the reply) afterwards, not by trusting the reply's status.

Outcomes: PASS, FAIL, CRASH (Blender died) or HANG (no reply at all in time).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .driver import compare

HERE = Path(__file__).resolve().parent
BOOT = HERE / "socket_boot.py"
STARTUP_TIMEOUT = 120.0
PING_TIMEOUT = 10.0
CHECK_TIMEOUT = 60.0
KILL_GRACE = 3.0
SCREEN = "1280x800x24"
BIG_REPLY_BYTES = 16 * 1024 * 1024


# --- protocol -------------------------------------------------------------------


class ReplyTimeout(Exception):
    """No complete reply line inside the budget. ``got`` is the bytes seen so far."""

    def __init__(self, got: int):
        super().__init__(f"no complete reply in time ({got} bytes received)")
        self.got = got


class ConnectionClosed(Exception):
    def __init__(self, got: int):
        super().__init__(f"connection closed before end of reply ({got} bytes received)")
        self.got = got


class BadReply(Exception):
    pass


class CheckFailed(Exception):
    """A postcondition did not hold."""


class RpcError(CheckFailed):
    """The server answered a request with a JSON-RPC error."""


class Budget:
    """A wall-clock allowance shared by every read of one check."""

    def __init__(self, seconds: float):
        self._end = time.monotonic() + seconds

    def remaining(self) -> float:
        return self._end - time.monotonic()


def encode_request(req_id: int, method: str, params: dict) -> bytes:
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
    return json.dumps(msg).encode("utf-8") + b"\n"


def read_reply(sock: socket.socket, budget: Budget) -> dict:
    """Read one newline-terminated JSON reply. Every recv is bounded by the budget."""
    chunks: list[bytes] = []
    got = 0
    while True:
        left = budget.remaining()
        if left <= 0:
            raise ReplyTimeout(got)
        sock.settimeout(left)
        try:
            data = sock.recv(1 << 20)
        except (socket.timeout, TimeoutError):
            raise ReplyTimeout(got) from None
        except OSError as exc:
            raise ConnectionClosed(got) from exc
        if not data:
            raise ConnectionClosed(got)
        got += len(data)
        end = data.find(b"\n")
        if end < 0:
            chunks.append(data)
            continue
        chunks.append(data[:end])
        line = b"".join(chunks)
        try:
            return json.loads(line.decode("utf-8"))
        except ValueError as exc:
            raise BadReply(f"reply is not JSON ({len(line)} bytes): {exc}") from None


class Conn:
    """One client connection; every call draws on the check's budget."""

    def __init__(self, port: int, budget: Budget):
        self.budget = budget
        self._next_id = 0
        left = max(budget.remaining(), 0.1)
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=left)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def send_raw(self, data: bytes) -> None:
        self.sock.settimeout(max(self.budget.remaining(), 0.1))
        self.sock.sendall(data)

    def call(self, method: str, params: dict | None = None):
        """Send a request, return its result. Error replies raise RpcError."""
        self._next_id += 1
        self.send_raw(encode_request(self._next_id, method, params or {}))
        reply = read_reply(self.sock, self.budget)
        if reply.get("id") != self._next_id:
            raise BadReply(f"reply id {reply.get('id')!r} != request id {self._next_id}")
        if "error" in reply:
            raise RpcError(f"{method}: {reply['error'].get('message')}")
        return reply.get("result")

    def exec(self, code: str):
        """Harness-side setup or inspection that does not use the tools under test."""
        return self.call("harness_exec", {"code": code})


# --- process control ------------------------------------------------------------


class TeardownError(RuntimeError):
    pass


def _group_gone(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    return False


def teardown(proc: subprocess.Popen, grace: float = KILL_GRACE) -> None:
    """Kill the whole process group (Blender and Xvfb) and confirm nothing is left."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        deadline = time.monotonic() + (grace if sig == signal.SIGTERM else 5.0)
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        while time.monotonic() < deadline:
            try:
                proc.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
            if proc.poll() is not None and _group_gone(proc.pid):
                break
        if proc.poll() is not None and _group_gone(proc.pid):
            break
    proc.wait()
    if not _group_gone(proc.pid):
        raise TeardownError(f"process group {proc.pid} still has members after SIGKILL")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def series_of(version_output: str) -> str:
    m = re.search(r"Blender (\d+)\.(\d+)", version_output)
    if not m:
        raise ValueError(f"cannot read a Blender version from {version_output[:60]!r}")
    return f"{m.group(1)}.{m.group(2)}"


def _blender_series(blender: str) -> str:
    out = subprocess.run(
        [blender, "--version"], capture_output=True, text=True, timeout=60, check=True
    ).stdout
    return series_of(out)


class StartupError(RuntimeError):
    pass


class BlenderSession:
    """A GUI Blender under Xvfb with the addon server on a free port."""

    def __init__(self, blender: str, out_dir: Path, scene: Path):
        self.blender = blender
        self.out_dir = out_dir
        self.scene = scene
        self.log_path = out_dir / "blender.log"
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.starts = 0

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        self.port = free_port()
        cmd = [
            "xvfb-run", "-a", "-s", f"-screen 0 {SCREEN}",
            self.blender, "--factory-startup", "--python", str(BOOT), "--",
            "--port", str(self.port), "--scene", str(self.scene),
        ]  # fmt: skip
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        with self.log_path.open("ab") as log:
            log.write(f"\n=== start {self.starts} port {self.port} ===\n".encode())
            log.flush()
            self.proc = subprocess.Popen(
                cmd, stdout=log, stderr=log, env=env, start_new_session=True
            )
        self.starts += 1
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if not self.alive():
                raise StartupError(f"Blender exited during startup, see {self.log_path}")
            if self.healthy():
                return
            time.sleep(0.5)
        raise StartupError(f"Blender did not answer ping in {STARTUP_TIMEOUT}s")

    def healthy(self) -> bool:
        if not self.alive():
            return False
        try:
            conn = Conn(self.port, Budget(PING_TIMEOUT))
        except OSError:
            return False
        try:
            return bool(conn.call("ping").get("pong"))
        except Exception:
            return False
        finally:
            conn.close()

    def alive_after_close(self, grace: float = 5.0) -> bool:
        """A closed socket usually means Blender is exiting; give the exit time to show."""
        deadline = time.monotonic() + grace
        while self.alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        return self.alive()

    def stop(self) -> None:
        if self.proc is not None:
            teardown(self.proc)

    def ensure_ready(self) -> bool:
        """Make sure a responsive Blender is up. Returns True if it had to (re)start."""
        if self.healthy():
            return False
        self.stop()
        self.start()
        return True

    def connect(self, budget: Budget) -> Conn:
        return Conn(self.port, budget)


# --- baseline -------------------------------------------------------------------


def merge_baseline(existing: dict, series: str, results: dict) -> dict:
    """Replace one series' entries and keep every other series."""
    merged = {k: dict(v) for k, v in existing.items()}
    merged[series] = dict(results)
    return merged


def diff_baseline(baseline: dict, series: str, results: dict) -> list[str]:
    return compare(baseline.get(series, {}), results)


def write_baseline(path: Path, series: str, results: dict) -> None:
    path = Path(path)
    existing = json.loads(path.read_text()) if path.exists() else {}
    merged = merge_baseline(existing, series, results)
    path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")


# --- checks ---------------------------------------------------------------------


@dataclass
class Ctx:
    conn: Conn
    out_dir: Path


MAKE_CUBE = """
import bmesh
def make(name, size, loc):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    bpy.context.scene.collection.objects.link(ob)
    return ob
"""


def _names(conn: Conn) -> list[str]:
    return [o["name"] for o in conn.call("object_list")["objects"]]


def check_object_create_listed(ctx: Ctx) -> str:
    before = ctx.conn.call("scene_info")["object_count"]
    ctx.conn.call("object_create", {"type": "cube", "name": "LaneCube"})
    after = ctx.conn.call("scene_info")["object_count"]
    names = _names(ctx.conn)
    if after != before + 1:
        raise CheckFailed(f"scene_info object_count {before} -> {after}, expected +1")
    if "LaneCube" not in names:
        raise CheckFailed("object_list does not list LaneCube")
    return "created object is counted and listed"


def check_mesh_knife_project_keeps_outside(ctx: Ctx) -> str:
    ctx.conn.exec(
        MAKE_CUBE + "make('LaneTarget', 2.0, (20, 0, 0))\nmake('LaneCutter', 0.5, (20, 0, 0))\n"
    )
    probe = (
        "ob = bpy.data.objects['LaneTarget']\n"
        "xs = [abs(v.co.x) for v in ob.data.vertices]\n"
        "result = {'verts': len(xs), 'max_x': max(xs) if xs else 0.0}\n"
    )
    before = ctx.conn.exec(probe)
    reply = ctx.conn.call(
        "mesh_knife_project", {"target_object": "LaneTarget", "cutter_object": "LaneCutter"}
    )
    after = ctx.conn.exec(probe)
    method = reply.get("method") if isinstance(reply, dict) else None
    if after["max_x"] < before["max_x"] - 1e-4 or after["verts"] < before["verts"]:
        raise CheckFailed(
            f"geometry outside the cut was lost: verts {before['verts']} -> {after['verts']}, "
            f"max |x| {before['max_x']:.2f} -> {after['max_x']:.2f} (reported method {method})"
        )
    return f"outer geometry kept (reported method {method})"


def check_render_image_writes_file(ctx: Ctx) -> str:
    out = ctx.out_dir / "render" / "lane_render.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    ctx.conn.exec(
        MAKE_CUBE + "make('LaneRenderCube', 2.0, (0, 0, 0))\n"
        "cam = bpy.data.objects.new('LaneCam', bpy.data.cameras.new('LaneCam'))\n"
        "cam.location = (0, -8, 0)\n"
        "cam.rotation_euler = (1.5707963, 0, 0)\n"
        "bpy.context.scene.collection.objects.link(cam)\n"
        "s = bpy.context.scene\n"
        "s.camera = cam\n"
        "s.render.engine = 'BLENDER_WORKBENCH'\n"
        "s.render.resolution_x = 64\n"
        "s.render.resolution_y = 64\n"
        "s.render.resolution_percentage = 100\n"
    )
    ctx.conn.call("render_image", {"output_path": str(out)})
    if not out.exists():
        raise CheckFailed("render_image replied but wrote no file")
    data = out.read_bytes()
    if not data:
        raise CheckFailed("render_image wrote an empty file")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CheckFailed(f"render_image output is not a PNG ({len(data)} bytes)")
    return f"wrote a {len(data)} byte PNG"


def check_undo_reverts(ctx: Ctx) -> str:
    ctx.conn.call("object_create", {"type": "cube", "name": "LaneUndoA"})
    ctx.conn.call("object_create", {"type": "cube", "name": "LaneUndoB"})
    if "LaneUndoB" not in _names(ctx.conn):
        raise CheckFailed("setup: LaneUndoB was not created")
    reply = ctx.conn.call("undo")
    if isinstance(reply, dict) and reply.get("success") is False:
        raise CheckFailed(f"undo reported failure: {reply.get('error')}")
    names = _names(ctx.conn)
    if "LaneUndoB" in names:
        raise CheckFailed("undo replied but LaneUndoB is still in the scene")
    if "LaneUndoA" not in names:
        raise CheckFailed("undo removed more than the last change (LaneUndoA is gone)")
    return "last change reverted, earlier change kept"


def check_execute_script_stdout(ctx: Ctx) -> str:
    token = "lane-token-7f3a"
    res = ctx.conn.call("execute_script", {"script": f"print('{token}')"})
    if not res.get("success"):
        raise CheckFailed(f"execute_script reported failure: {res.get('error')}")
    if token not in res.get("stdout", ""):
        raise CheckFailed(f"stdout {res.get('stdout')!r} does not contain the printed token")
    return "printed text came back in stdout"


def check_reply_16mb_complete(ctx: Ctx) -> str:
    unit = "abcdefghijklmnopqrstuvwxyz0123456789"
    expected = (unit * (BIG_REPLY_BYTES // len(unit) + 1))[:BIG_REPLY_BYTES]
    script = f"unit = {unit!r}\nn = {BIG_REPLY_BYTES}\nresult = (unit * (n // len(unit) + 1))[:n]\n"
    res = ctx.conn.call("execute_script", {"script": script})
    got = res.get("result")
    if not isinstance(got, str):
        raise CheckFailed(f"reply result is {type(got).__name__}, expected str")
    if len(got) != len(expected):
        raise CheckFailed(f"reply result is {len(got)} chars, expected {len(expected)}")
    if got != expected:
        raise CheckFailed("reply result has the right length but different content")
    return "16 MiB reply arrived complete and intact"


def check_malformed_json_error_reply(ctx: Ctx) -> str:
    ctx.conn.send_raw(b"{this is not json\n")
    reply = read_reply(ctx.conn.sock, ctx.conn.budget)
    if "error" not in reply:
        raise CheckFailed(f"malformed request got a non-error reply: {str(reply)[:80]}")
    code = reply["error"].get("code")
    if code != -32700:
        raise CheckFailed(f"error code {code}, expected -32700 (parse error)")
    if ctx.conn.call("ping").get("pong") is not True:
        raise CheckFailed("connection unusable after a malformed request")
    return "parse error reply, connection still usable"


# (name, function, seconds)
CHECKS: list[tuple[str, Callable[[Ctx], str], float]] = [
    ("object_create_listed", check_object_create_listed, CHECK_TIMEOUT),
    ("mesh_knife_project_keeps_outside", check_mesh_knife_project_keeps_outside, CHECK_TIMEOUT),
    ("render_image_writes_file", check_render_image_writes_file, 120.0),
    ("undo_reverts", check_undo_reverts, CHECK_TIMEOUT),
    ("execute_script_stdout", check_execute_script_stdout, CHECK_TIMEOUT),
    ("reply_16mb_complete", check_reply_16mb_complete, CHECK_TIMEOUT),
    ("malformed_json_error_reply", check_malformed_json_error_reply, CHECK_TIMEOUT),
]


def classify_failure(exc: Exception, blender_alive: bool) -> tuple[str, str]:
    """Map an exception raised by a check to (outcome, reason)."""
    if not blender_alive:
        return "CRASH", f"Blender died during the check ({type(exc).__name__}: {exc})"
    if isinstance(exc, ReplyTimeout) and exc.got == 0:
        return "HANG", str(exc)
    return "FAIL", f"{type(exc).__name__}: {exc}"


FAILURES = (CheckFailed, ReplyTimeout, ConnectionClosed, BadReply, OSError)


def run_check(session: BlenderSession, name: str, fn, seconds: float, out_dir: Path):
    """Run one check from a freshly reset scene. Returns (outcome, reason)."""
    budget = Budget(seconds)

    def classify(exc: Exception) -> tuple[str, str]:
        closed = isinstance(exc, (ConnectionClosed, ConnectionError))
        return classify_failure(exc, session.alive_after_close() if closed else session.alive())

    try:
        conn = session.connect(budget)
    except OSError as exc:
        return classify(exc)
    try:
        try:
            conn.call("harness_reset")
        except FAILURES as exc:
            outcome, reason = classify(exc)
            return outcome, f"scene reset failed: {reason}"
        try:
            reason = fn(Ctx(conn, out_dir))
            outcome = "PASS"
        except FAILURES as exc:
            outcome, reason = classify(exc)
    finally:
        conn.close()
    if outcome != "CRASH" and not session.alive():
        return "CRASH", f"Blender exited during the check (was {outcome}: {reason})"
    return outcome, reason


def run_lane(blender: str, out_dir: Path, checks=CHECKS) -> tuple[str, dict[str, str]]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    series = _blender_series(blender)
    scene = out_dir / "scene.blend"
    log = out_dir / "blender.log"
    log.write_bytes(b"")
    build = subprocess.Popen(
        [blender, "-b", "--factory-startup", "--python", str(BOOT), "--",
         "--build-scene", "--scene", str(scene)],
        stdout=log.open("ab"), stderr=subprocess.STDOUT, start_new_session=True,
    )  # fmt: skip
    try:
        build.wait(timeout=STARTUP_TIMEOUT)
    finally:
        teardown(build)
    if build.returncode != 0 or not scene.exists():
        raise StartupError(f"could not build the fixture scene, see {log}")

    session = BlenderSession(blender, out_dir, scene)
    results: dict[str, str] = {}
    try:
        for name, fn, seconds in checks:
            try:
                if session.ensure_ready():
                    print(f"# blender (re)started on port {session.port}", flush=True)
            except StartupError as exc:
                results[name] = "CRASH"
                print(f"{name} CRASH could not start Blender: {exc}", flush=True)
                continue
            outcome, reason = run_check(session, name, fn, seconds, out_dir)
            results[name] = outcome
            print(f"{name} {outcome} {reason}", flush=True)
    finally:
        session.stop()
    return series, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--write-baseline", type=Path, metavar="FILE")
    parser.add_argument("--check-baseline", type=Path, metavar="FILE")
    args = parser.parse_args(argv)
    if args.write_baseline and args.check_baseline:
        parser.error("--write-baseline and --check-baseline are mutually exclusive")

    series, results = run_lane(args.blender, args.out)
    (args.out / "results.json").write_text(
        json.dumps({series: results}, indent=2, sort_keys=True) + "\n"
    )
    print(f"# series {series}")
    if args.write_baseline:
        write_baseline(args.write_baseline, series, results)
    if args.check_baseline:
        diff = diff_baseline(json.loads(args.check_baseline.read_text()), series, results)
        for line in diff:
            print(line, file=sys.stderr)
        return 1 if diff else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
