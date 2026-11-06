"""Drive a real GUI Blender through the real addon socket and check postconditions.

Stdlib only: the lane speaks the newline-delimited JSON protocol itself, so it fails
if the protocol breaks. A tool that reports success without doing the work is caught
by checking the scene (or the reply) afterwards, not by trusting the reply's status.

Outcomes: PASS, FAIL, CRASH (Blender died) or HANG (no reply at all in time).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .driver import DIFF_HINT, compare
from .env import blender_env

HERE = Path(__file__).resolve().parent
BOOT = HERE / "socket_boot.py"
STARTUP_TIMEOUT = 120.0
PING_TIMEOUT = 10.0
CHECK_TIMEOUT = 60.0
KILL_GRACE = 3.0
BIND_FAILED_EXIT = 4  # socket_boot.py exit code when the port was taken
START_ATTEMPTS = 3
RENDER_SIZE = 64
SCREEN = "1280x800x24"
BIG_REPLY_BYTES = 32 * 1024 * 1024


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


def proof(token: str, label: str, a: str, b: str) -> str:
    """Same HMAC as wire.proof, spelled out so the lane checks the protocol, not the module."""
    return hmac.new(token.encode(), f"{label}\n{a}\n{b}".encode(), hashlib.sha256).hexdigest()


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

    def __init__(self, port: int, budget: Budget, token: str | None = None):
        """Connect. With a token the connection also says hello; without one it is raw."""
        self.budget = budget
        self.port = port
        self.token = token
        self._next_id = 0
        left = max(budget.remaining(), 0.1)
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=left)
        if token is not None:
            try:
                self.handshake(token)
            except BaseException:
                self.close()
                raise

    def hello(self) -> tuple[str, dict]:
        """Send hello with a fresh nonce; return (nonce, the add-on's result)."""
        nonce = secrets.token_urlsafe(32)
        result = self.call("hello", {"protocol": 1, "client": "socket-lane", "nonce": nonce})
        return nonce, result

    def handshake(self, token: str) -> None:
        """The whole mutual handshake. The token is only ever an HMAC key here."""
        nonce_c, result = self.hello()
        ns = result["nonce"]
        if not hmac.compare_digest(result["proof"], proof(token, "meshwire-addon", nonce_c, ns)):
            raise BadReply("the add-on's proof did not verify")
        got = self.call("hello_proof", {"proof": proof(token, "meshwire-client", ns, nonce_c)})
        if got != {"ok": True}:
            raise BadReply(f"hello_proof was not accepted: {got!r}")

    def fresh(self, authed: bool = True) -> "Conn":
        """Another connection to the same server, with or without hello."""
        return Conn(self.port, self.budget, self.token if authed else None)

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
    """True when no live (non-zombie) process remains in the group.

    killpg(pgid, 0) still succeeds for a zombie, and in a container without an init
    nobody reaps orphans, so read the process state from /proc.
    """
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            text = stat.read_text()
        except OSError:
            continue
        # "pid (comm) state ppid pgrp ...": comm may contain spaces and parens.
        fields = text[text.rindex(")") + 2 :].split()
        if int(fields[2]) == pgid and fields[0] != "Z":
            return False
    return True


@contextlib.contextmanager
def sigterm_as_exit():
    """Turn SIGTERM into SystemExit so finally-blocks tear Blender down on a CI cancel."""

    def handler(signum, frame):
        raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


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

    @property
    def config_dir(self) -> Path:
        """This run's own Meshwire config folder, so the lane never touches the user's."""
        return self.out_dir / "config"

    def token(self) -> str:
        """The token the add-on wrote for this run. Never printed or logged."""
        return (self.config_dir / "token").read_text(encoding="utf-8").strip()

    @property
    def env(self) -> dict[str, str]:
        env = blender_env(self.out_dir / "tmp")
        env.pop("MESHWIRE_TOKEN", None)
        env["MESHWIRE_CONFIG_DIR"] = str(self.config_dir)
        return env

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _spawn(self) -> None:
        cmd = [
            "xvfb-run", "-a", "-s", f"-screen 0 {SCREEN}",
            self.blender, "--factory-startup", "--python", str(BOOT), "--",
            "--port", str(self.port), "--scene", str(self.scene),
        ]  # fmt: skip
        env = self.env
        with self.log_path.open("ab") as log:
            log.write(f"\n=== start {self.starts} port {self.port} ===\n".encode())
            log.flush()
            self.proc = subprocess.Popen(
                cmd, stdout=log, stderr=log, env=env, start_new_session=True
            )
        self.starts += 1

    def start(self) -> None:
        """Start Blender; if another process grabbed the port first, retry on a new one."""
        for attempt in range(START_ATTEMPTS):
            self.port = free_port()
            self._spawn()
            deadline = time.monotonic() + STARTUP_TIMEOUT
            while time.monotonic() < deadline:
                if not self.alive():
                    break
                if self.healthy():
                    return
                time.sleep(0.5)
            else:
                raise StartupError(f"Blender did not answer ping in {STARTUP_TIMEOUT}s")
            code = self.proc.poll()
            self.stop()
            if code != BIND_FAILED_EXIT:
                raise StartupError(
                    f"Blender exited with {code} during startup, see {self.log_path}"
                )
        raise StartupError(f"port was taken {START_ATTEMPTS} times in a row")

    def healthy(self) -> bool:
        if not self.alive():
            return False
        try:
            conn = Conn(self.port, Budget(PING_TIMEOUT), self.token())
        except (OSError, CheckFailed, ConnectionClosed, ReplyTimeout, BadReply):
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
        return Conn(self.port, budget, self.token())


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


def png_size(data: bytes) -> tuple[int, int]:
    """Width and height from the IHDR chunk of a PNG."""
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    return struct.unpack(">II", data[16:24])


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
    # knife_project needs a cutter with wire or boundary edges, which a closed cube lacks,
    # so the cutter is a single quad. The viewport is left as the GUI opened it: the tool
    # must frame the objects along its view axis (TOP by default) itself.
    ctx.conn.exec(
        MAKE_CUBE
        + "make('LaneTarget', 2.0, (20, 0, 0))\n"
        + "me = bpy.data.meshes.new('LaneCutter')\n"
        + "bm = bmesh.new()\n"
        + "bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.25)\n"
        + "bm.to_mesh(me)\n"
        + "bm.free()\n"
        + "cutter = bpy.data.objects.new('LaneCutter', me)\n"
        + "cutter.location = (20, 0, 2)\n"
        + "bpy.context.scene.collection.objects.link(cutter)\n"
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
    if not (isinstance(reply, dict) and reply.get("success") is True):
        raise CheckFailed(f"knife project did not report success: {str(reply)[:120]}")
    if after["max_x"] < before["max_x"] - 1e-4 or after["verts"] < before["verts"]:
        raise CheckFailed(
            f"geometry outside the cut was lost: verts {before['verts']} -> {after['verts']}, "
            f"max |x| {before['max_x']:.2f} -> {after['max_x']:.2f} (reported method {method})"
        )
    if after["verts"] <= before["verts"]:
        raise CheckFailed(
            f"no cut was made: verts {before['verts']} -> {after['verts']} (reported method {method})"
        )
    return f"outer geometry kept and cut added ({before['verts']} -> {after['verts']} verts)"


def check_mesh_knife_project_reports_no_cut(ctx: Ctx) -> str:
    # A cutter that sits beside the target does not overlap it in the top view, so the
    # operator cuts nothing and raises nothing. The reply must say so.
    ctx.conn.exec(
        MAKE_CUBE
        + "make('LaneMissTarget', 2.0, (80, 0, 0))\n"
        + "me = bpy.data.meshes.new('LaneMissCutter')\n"
        + "bm = bmesh.new()\n"
        + "bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.25)\n"
        + "bm.to_mesh(me)\n"
        + "bm.free()\n"
        + "cutter = bpy.data.objects.new('LaneMissCutter', me)\n"
        + "cutter.location = (95, 0, 2)\n"
        + "bpy.context.scene.collection.objects.link(cutter)\n"
    )
    probe = (
        "me = bpy.data.objects['LaneMissTarget'].data\n"
        "result = [len(me.vertices), len(me.edges), len(me.polygons)]\n"
    )
    before = ctx.conn.exec(probe)
    reply = ctx.conn.call(
        "mesh_knife_project",
        {"target_object": "LaneMissTarget", "cutter_object": "LaneMissCutter"},
    )
    after = ctx.conn.exec(probe)
    if not (isinstance(reply, dict) and reply.get("success") is False):
        raise CheckFailed(f"a cut that changed nothing did not report failure: {str(reply)[:160]}")
    if "does not overlap" not in str(reply.get("error", "")):
        raise CheckFailed(f"the failure does not say why: {str(reply)[:160]}")
    if before != after:
        raise CheckFailed(f"the mesh changed although no cut was reported: {before} -> {after}")
    return "no-overlap cut reported as a failure, mesh unchanged"


def check_mesh_knife_project_uses_view_axis(ctx: Ctx) -> str:
    # The cutter stands upright in front of the target (an XZ-plane square at y = -3).
    # Seen from the top it is a line outside the target, so TOP cuts nothing. Seen
    # from the front it covers part of the target's front face, so FRONT cuts.
    ctx.conn.exec(
        MAKE_CUBE
        + "make('LaneAxisTarget', 2.0, (110, 0, 0))\n"
        + "me = bpy.data.meshes.new('LaneAxisCutter')\n"
        + "bm = bmesh.new()\n"
        + "bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.25)\n"
        + "bm.to_mesh(me)\n"
        + "bm.free()\n"
        + "cutter = bpy.data.objects.new('LaneAxisCutter', me)\n"
        + "cutter.location = (110, -3, 0)\n"
        + "cutter.rotation_euler = (1.5707963, 0, 0)\n"
        + "bpy.context.scene.collection.objects.link(cutter)\n"
    )
    probe = (
        "me = bpy.data.objects['LaneAxisTarget'].data\n"
        "area = next(a for w in bpy.context.window_manager.windows\n"
        "            for a in w.screen.areas if a.type == 'VIEW_3D')\n"
        "rv3d = area.spaces.active.region_3d\n"
        "front = sum(1 for v in me.vertices if abs(v.co.y + 1.0) < 1e-4)\n"
        "result = [len(me.vertices), front, [round(v, 4) for v in rv3d.view_rotation],"
        " [round(v, 4) for v in rv3d.view_location], round(rv3d.view_distance, 4),"
        " rv3d.view_perspective]\n"
    )
    args = {"target_object": "LaneAxisTarget", "cutter_object": "LaneAxisCutter"}
    before = ctx.conn.exec(probe)
    top = ctx.conn.call("mesh_knife_project", {**args, "view_axis": "TOP"})
    if not (isinstance(top, dict) and top.get("success") is False):
        raise CheckFailed(f"TOP should cut nothing here: {str(top)[:160]}")
    front = ctx.conn.call("mesh_knife_project", {**args, "view_axis": "FRONT"})
    after = ctx.conn.exec(probe)
    if not (isinstance(front, dict) and front.get("success") and front.get("view_axis") == "FRONT"):
        raise CheckFailed(f"FRONT should cut and report its axis: {str(front)[:160]}")
    if after[1] - before[1] != after[0] - before[0] or after[0] <= before[0]:
        raise CheckFailed(
            f"FRONT should add vertices on the front face only: verts {before[0]} -> {after[0]},"
            f" front-face verts {before[1]} -> {after[1]}"
        )
    if after[2:] != before[2:]:
        raise CheckFailed(f"the view was not restored: {before[2:]} -> {after[2:]}")
    return f"TOP cut nothing, FRONT cut the front face ({before[0]} -> {after[0]} verts), view restored"


def check_mesh_loop_cut_adds_edges(ctx: Ctx) -> str:
    ctx.conn.exec(MAKE_CUBE + "make('LaneLoopCube', 2.0, (60, 0, 0))\n")
    probe = "result = len(bpy.data.objects['LaneLoopCube'].data.edges)\n"
    before = ctx.conn.exec(probe)
    reply = ctx.conn.call(
        "mesh_loop_cut", {"object_name": "LaneLoopCube", "edge_index": 0, "cuts": 1}
    )
    after = ctx.conn.exec(probe)
    if not (isinstance(reply, dict) and reply.get("success") is True):
        raise CheckFailed(f"loop cut did not report success: {str(reply)[:160]}")
    if after <= before:
        raise CheckFailed(f"edge count did not grow: {before} -> {after}")
    return f"edges {before} -> {after}"


def check_mesh_select_criteria_intersect(ctx: Ctx) -> str:
    # Two criteria must both hold (#38). On a cube, normal +Z matches only the
    # top face and "x within 0.5 of the centre" matches every face but +X, so a union would give
    # five faces and an intersection gives the top face alone.
    ctx.conn.exec(MAKE_CUBE + "make('LaneSelectCube', 2.0, (80, 0, 0))\n")
    reply = ctx.conn.call(
        "mesh_select",
        {
            "object_name": "LaneSelectCube",
            "mode": "FACE",
            "normal_direction": [0, 0, 1],
            "normal_threshold": 0.9,
            "position_max": [80.5, 5, 5],
        },
    )
    if not (isinstance(reply, dict) and reply.get("success") is True):
        raise CheckFailed(f"mesh_select did not report success: {str(reply)[:160]}")
    picked = reply.get("selected_indices")
    if not isinstance(picked, list) or len(picked) != 1:
        raise CheckFailed(f"expected only the top face, got {picked}")
    probe = f"result = bpy.data.objects['LaneSelectCube'].data.polygons[{picked[0]}].normal.z\n"
    if ctx.conn.exec(probe) < 0.9:
        raise CheckFailed(f"face {picked[0]} is not the +Z face")
    return "two criteria selected only the face matching both"


def check_mesh_edge_slide_moves_edge(ctx: Ctx) -> str:
    # An interior edge of a flat grid slides along the faces next to it.
    ctx.conn.exec(
        "import bmesh\n"
        "me = bpy.data.meshes.new('LaneSlideMesh')\n"
        "bm = bmesh.new()\n"
        "bmesh.ops.create_grid(bm, x_segments=4, y_segments=4, size=1.0)\n"
        "bm.to_mesh(me)\n"
        "bm.free()\n"
        "ob = bpy.data.objects.new('LaneSlide', me)\n"
        "ob.location = (90, 0, 0)\n"
        "bpy.context.scene.collection.objects.link(ob)\n"
    )
    pick = (
        "me = bpy.data.objects['LaneSlide'].data\n"
        "xs = sorted({round(v.co.x, 4) for v in me.vertices})\n"
        "ys = sorted({round(v.co.y, 4) for v in me.vertices})\n"
        "ids = [e.index for e in me.edges if all(abs(me.vertices[v].co.x - xs[1]) < 1e-4 and ys[0] < me.vertices[v].co.y < ys[-1] + 1e-4 for v in e.vertices)]\n"
        "result = ids\n"
    )
    edges = ctx.conn.exec(pick)
    if not edges:
        raise CheckFailed("setup: no interior edge found")
    probe = (
        "me = bpy.data.objects['LaneSlide'].data\n"
        f"result = sorted(round(me.vertices[v].co.x, 4) for v in me.edges[{edges[0]}].vertices)\n"
    )
    before = ctx.conn.exec(probe)
    reply = ctx.conn.call(
        "mesh_edge_slide", {"object_name": "LaneSlide", "edge_indices": [edges[0]], "factor": 0.5}
    )
    after = ctx.conn.exec(probe)
    if not (isinstance(reply, dict) and reply.get("success") is True):
        raise CheckFailed(f"edge slide did not report success: {str(reply)[:160]}")
    if before == after:
        raise CheckFailed(f"edge did not move: x stayed {before}")
    return f"edge x {before} -> {after}"


SCULPT_FILTER_TYPES = [
    "SMOOTH",
    "SHARPEN",
    "ENHANCE_DETAIL",
    "SURFACE_NOISE",
    "INFLATE",
    "SPHERE",
    "RELAX",
    "RELAX_FACE_SETS",
    "ERASE_DISPLACEMENT",
]


def check_sculpt_mesh_filter_moves_vertices(ctx: Ctx) -> str:
    # A subdivided, bumpy sphere: every filter has something to change, including
    # ERASE_DISPLACEMENT, which needs a displacement to erase.
    ctx.conn.exec(
        "import bmesh, random\n"
        "me = bpy.data.meshes.new('LaneSculptMesh')\n"
        "bm = bmesh.new()\n"
        "bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=1.0)\n"
        "bm.to_mesh(me)\n"
        "bm.free()\n"
        "ob = bpy.data.objects.new('LaneSculpt', me)\n"
        "ob.location = (70, 0, 0)\n"
        "bpy.context.scene.collection.objects.link(ob)\n"
    )
    reset = (
        "import random\n"
        "random.seed(3)\n"
        "me = bpy.data.objects['LaneSculpt'].data\n"
        "for v in me.vertices:\n"
        "    v.co = v.co.normalized() * (1.0 + random.uniform(-0.2, 0.2))\n"
        "me.update()\n"
    )
    # ERASE_DISPLACEMENT only acts on a Multires displacement, so it gets a Multires
    # object that a RANDOM filter has displaced first; positions come from the evaluated mesh.
    ctx.conn.exec(
        "ob2 = bpy.data.objects.new('LaneSculptMulti', bpy.data.meshes.new_from_object(bpy.data.objects['LaneSculpt']))\n"
        "ob2.location = (75, 0, 0)\n"
        "bpy.context.scene.collection.objects.link(ob2)\n"
        "ob2.modifiers.new('Multires', 'MULTIRES')\n"
        "bpy.context.view_layer.objects.active = ob2\n"
        "bpy.ops.object.multires_subdivide(modifier='Multires', mode='CATMULL_CLARK')\n"
    )
    probe = (
        "bpy.ops.object.mode_set(mode='OBJECT')\n"
        "result = [tuple(v.co) for v in bpy.data.objects['LaneSculpt'].data.vertices]\n"
    )
    probe_multi = (
        "ob = bpy.data.objects['LaneSculptMulti']\n"
        "bpy.ops.object.mode_set(mode='OBJECT')\n"
        "ob.data.update()\n"
        "bpy.context.view_layer.update()\n"
        "result = [tuple(v.co) for v in ob.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices]\n"
    )

    def moved_count(before, after):
        return sum(1 for a, b in zip(before, after) if max(abs(x - y) for x, y in zip(a, b)) > 1e-6)

    done = []
    for filter_type in SCULPT_FILTER_TYPES:
        name, read = "LaneSculpt", probe
        if filter_type == "ERASE_DISPLACEMENT":
            name, read = "LaneSculptMulti", probe_multi
            reply = ctx.conn.call(
                "sculpt_mesh_filter",
                {"object_name": name, "filter_type": "SURFACE_NOISE", "strength": 1.0},
            )
            if not (isinstance(reply, dict) and reply.get("success") is True):
                raise CheckFailed(f"displacing the Multires object: {str(reply)[:160]}")
        else:
            ctx.conn.exec(
                "if bpy.context.mode != 'OBJECT':\n    bpy.ops.object.mode_set(mode='OBJECT')\n"
                + reset
            )
        before = ctx.conn.exec(read)
        reply = ctx.conn.call(
            "sculpt_mesh_filter",
            {"object_name": name, "filter_type": filter_type, "strength": 1.0},
        )
        if not (isinstance(reply, dict) and reply.get("success") is True):
            raise CheckFailed(f"{filter_type}: {str(reply)[:160]}")
        # Sculpt-mode edits reach the mesh data once the mode is left
        after = ctx.conn.exec(read)
        moved = moved_count(before, after)
        if not moved:
            raise CheckFailed(f"{filter_type}: replied success but no vertex moved")
        done.append(f"{filter_type}={moved}")
    return "vertices moved for " + ", ".join(done)


def check_sculpt_mask_by_topology_sets_mask(ctx: Ctx) -> str:
    # A smooth sphere with a dent: CAVITY finds the dent, and RANDOM gives distinct values.
    # CAVITY reads a constant on a noisy mesh, so the dent is deliberately smooth.
    ctx.conn.exec(
        "import bmesh\n"
        "me = bpy.data.meshes.new('LaneMaskMesh')\n"
        "bm = bmesh.new()\n"
        "bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=1.0)\n"
        "for v in bm.verts:\n"
        "    n = v.co.normalized()\n"
        "    v.co = n * (1.0 - 0.9 * max(0.0, n.z - 0.7))\n"
        "bm.to_mesh(me)\n"
        "bm.free()\n"
        "ob = bpy.data.objects.new('LaneMaskCube', me)\n"
        "ob.location = (80, 0, 0)\n"
        "bpy.context.scene.collection.objects.link(ob)\n"
    )
    probe = (
        "ob = bpy.data.objects['LaneMaskCube']\n"
        "bpy.ops.object.mode_set(mode='OBJECT')\n"
        "attr = ob.data.attributes.get('.sculpt_mask')\n"
        "result = sorted({round(d.value, 3) for d in attr.data}) if attr else []\n"
    )
    got = {}
    for mask_type in ("ALL", "NONE", "CAVITY", "RANDOM"):
        # NONE after ALL has a mask to clear; CAVITY and RANDOM start from a clean one
        reply = ctx.conn.call(
            "sculpt_mask_by_topology", {"object_name": "LaneMaskCube", "mask_type": mask_type}
        )
        if not (isinstance(reply, dict) and reply.get("success") is True):
            raise CheckFailed(f"{mask_type}: {str(reply)[:160]}")
        values = ctx.conn.exec(probe)
        if mask_type == "ALL" and values != [1.0]:
            raise CheckFailed(f"ALL: mask values {values}, expected [1.0]")
        # NONE may drop the mask layer altogether
        if mask_type == "NONE" and values and values != [0.0]:
            raise CheckFailed(f"NONE: mask values {values}, expected [0.0]")
        if mask_type == "CAVITY" and len(values) < 2:
            raise CheckFailed(f"CAVITY: mask values {values}, expected a gradient")
        if mask_type == "RANDOM" and len(values) < 8:
            raise CheckFailed(f"RANDOM: mask values {values}, expected many distinct values")
        got[mask_type] = len(values)
    # Blur and invert go through the same operators
    reply = ctx.conn.call(
        "sculpt_mask_by_topology",
        {
            "object_name": "LaneMaskCube",
            "mask_type": "RANDOM",
            "invert": True,
            "blur_iterations": 2,
        },
    )
    if not (isinstance(reply, dict) and reply.get("success") is True):
        raise CheckFailed(f"RANDOM with invert and blur: {str(reply)[:160]}")
    return f"distinct mask values per type {got}; invert and blur succeed"


def check_sculpt_face_set_create_makes_sets(ctx: Ctx) -> str:
    # Two loose cubes with a material each: LINKED and MATERIAL both find two sets.
    ctx.conn.exec(
        MAKE_CUBE + "ob = make('LaneFaceSets', 2.0, (85, 0, 0))\n"
        "other = make('LaneFaceSetsB', 2.0, (85, 0, 0))\n"
        "bpy.ops.object.select_all(action='DESELECT')\n"
        "bpy.context.view_layer.objects.active = ob\n"
        "for o in (ob, other):\n"
        "    o.select_set(True)\n"
        "bpy.ops.object.join()\n"
        "ob = bpy.context.view_layer.objects.active\n"
        "ob.name = 'LaneFaceSets'\n"
        "for i in range(2):\n"
        "    ob.data.materials.append(bpy.data.materials.new(f'LaneFaceSetMat{i}'))\n"
        "for p in ob.data.polygons:\n"
        "    p.material_index = 1 if p.index >= 6 else 0\n"
    )
    probe = (
        "ob = bpy.data.objects['LaneFaceSets']\n"
        "bpy.ops.object.mode_set(mode='OBJECT')\n"
        "attr = ob.data.attributes.get('.sculpt_face_set')\n"
        "result = len({d.value for d in attr.data}) if attr else 0\n"
    )
    counts = {}
    for criteria in ("LINKED", "MATERIAL", "NORMAL", "SHARP_EDGES", "UV_ISLAND"):
        reply = ctx.conn.call(
            "sculpt_face_set_create", {"object_name": "LaneFaceSets", "criteria": criteria}
        )
        if not (isinstance(reply, dict) and reply.get("success") is True):
            raise CheckFailed(f"{criteria}: {str(reply)[:160]}")
        counts[criteria] = ctx.conn.exec(probe)
        if counts[criteria] < 1:
            raise CheckFailed(f"{criteria}: replied success but wrote no face sets")
    for criteria in ("LINKED", "MATERIAL"):
        if counts[criteria] != 2:
            raise CheckFailed(f"{criteria}: expected 2 face sets, got {counts[criteria]}")
    return f"face sets per criteria {counts}"


def check_sculpt_extract_mask_needs_a_mask(ctx: Ctx) -> str:
    ctx.conn.exec(
        MAKE_CUBE
        + "make('LaneNoMask', 2.0, (87, 0, 0))\n"
        + "if bpy.context.mode != 'OBJECT':\n    bpy.ops.object.mode_set(mode='OBJECT')\n"
    )
    try:
        reply = ctx.conn.call("sculpt_extract_mask", {"object_name": "LaneNoMask"})
    except RpcError as e:
        raise CheckFailed(f"raised instead of replying with an error: {str(e)[:160]}") from None
    if not (isinstance(reply, dict) and "error" in reply):
        raise CheckFailed(f"expected an error, got {str(reply)[:160]}")
    if "mask" not in str(reply["error"]).lower() or "attribute" in str(reply["error"]).lower():
        raise CheckFailed(f"error does not explain the missing mask: {reply['error']}")
    # With a masked half, the same tool extracts it
    ctx.conn.exec(
        "bpy.ops.mesh.primitive_uv_sphere_add(location=(87, 4, 0))\n"
        "ob = bpy.context.active_object\n"
        "ob.name = 'LaneMasked'\n"
        "mask = ob.data.attributes.new('.sculpt_mask', 'FLOAT', 'POINT')\n"
        "for v in ob.data.vertices:\n"
        "    mask.data[v.index].value = 1.0 if v.co.z > 0 else 0.0\n"
    )
    reply = ctx.conn.call("sculpt_extract_mask", {"object_name": "LaneMasked"})
    if not (isinstance(reply, dict) and reply.get("success") is True) or not reply.get(
        "polygon_count"
    ):
        raise CheckFailed(f"extracting a masked half: {str(reply)[:160]}")
    return f"an unmasked mesh gives a clear error; a masked half extracts {reply['polygon_count']} faces"


def check_sculpt_failure_leaves_object_mode(ctx: Ctx) -> str:
    # The decorator the sculpt tools use: an error reply after entering Sculpt mode must
    # leave Object mode, and a successful reply keeps the mode it ended in.
    ctx.conn.exec(
        MAKE_CUBE
        + "make('LaneSculptMode', 2.0, (88, 0, 0))\n"
        + "if bpy.context.mode != 'OBJECT':\n    bpy.ops.object.mode_set(mode='OBJECT')\n"
        "bpy.ops.object.select_all(action='DESELECT')\n"
        "bpy.context.view_layer.objects.active = bpy.data.objects['LaneSculptMode']\n"
    )
    probe = (
        "from blender_mcp_addon.handlers._helpers import restores_object_mode\n"
        "def enter_sculpt(reply):\n"
        "    @restores_object_mode(error_replies=True)\n"
        "    def handler(self, params):\n"
        "        bpy.ops.object.mode_set(mode='SCULPT')\n"
        "        return reply\n"
        "    handler(None, {})\n"
        "    mode = bpy.context.mode\n"
        "    bpy.ops.object.mode_set(mode='OBJECT')\n"
        "    return mode\n"
        "result = {\n"
        "    'error': enter_sculpt({'error': 'boom'}),\n"
        "    'false': enter_sculpt({'success': False}),\n"
        "    'ok': enter_sculpt({'success': True}),\n"
        "}\n"
    )
    modes = ctx.conn.exec(probe)
    if modes["error"] != "OBJECT" or modes["false"] != "OBJECT":
        raise CheckFailed(f"an error reply left the mode at {modes}")
    if modes["ok"] != "SCULPT":
        raise CheckFailed(f"a successful reply should keep Sculpt mode, got {modes}")
    # A real tool: a mesh with masked vertices and no faces cannot be extracted
    ctx.conn.exec(
        "me = bpy.data.meshes.new('LaneSculptNoFaces')\n"
        "me.vertices.add(3)\n"
        "me.vertices.foreach_set('co', [0, 0, 0, 1, 0, 0, 0, 1, 0])\n"
        "me.update()\n"
        "mask = me.attributes.new('.sculpt_mask', 'FLOAT', 'POINT')\n"
        "for d in mask.data:\n"
        "    d.value = 1.0\n"
        "ob = bpy.data.objects.new('LaneSculptNoFaces', me)\n"
        "bpy.context.scene.collection.objects.link(ob)\n"
    )
    try:
        reply = ctx.conn.call("sculpt_extract_mask", {"object_name": "LaneSculptNoFaces"})
    except RpcError:
        reply = None
    mode = ctx.conn.exec("result = bpy.context.mode\n")
    failed = reply is None or (
        isinstance(reply, dict) and (reply.get("success") is False or "error" in reply)
    )
    if failed and mode != "OBJECT":
        raise CheckFailed(f"sculpt_extract_mask failed ({str(reply)[:100]}) and left {mode} mode")
    return "error replies leave Object mode, a successful reply keeps Sculpt mode" + (
        "; sculpt_extract_mask failed cleanly" if failed else ""
    )


def check_render_screenshot_writes_file(ctx: Ctx) -> str:
    out = ctx.out_dir / "screenshot" / "lane_screenshot.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    reply = ctx.conn.call("render_screenshot", {"output_path": str(out)})
    if isinstance(reply, dict) and "error" in reply:
        raise CheckFailed(f"render_screenshot failed: {str(reply['error'])[:160]}")
    if not out.exists():
        raise CheckFailed("render_screenshot replied but wrote no file")
    try:
        width, height = png_size(out.read_bytes())
    except ValueError:
        raise CheckFailed("render_screenshot output is not a PNG") from None
    return f"wrote a {width}x{height} PNG"


def check_mode_restored_after_failure(ctx: Ctx) -> str:
    # mesh_separate_selected enters Edit mode and then mesh.separate raises, because an
    # empty face list leaves nothing selected.
    ctx.conn.exec(
        MAKE_CUBE
        + "make('LaneModeCube', 2.0, (90, 0, 0))\n"
        + "if bpy.context.mode != 'OBJECT':\n    bpy.ops.object.mode_set(mode='OBJECT')\n"
    )
    try:
        reply = ctx.conn.call(
            "mesh_separate_selected",
            {"object_name": "LaneModeCube", "face_indices": []},
        )
    except RpcError:
        reply = None
    failed = reply is None or (
        isinstance(reply, dict) and (reply.get("success") is False or "error" in reply)
    )
    if not failed:
        raise CheckFailed(f"mesh_separate_selected was expected to fail, got {str(reply)[:160]}")
    mode = ctx.conn.exec("result = bpy.context.mode\n")
    if mode != "OBJECT":
        raise CheckFailed(f"mode is {mode} after the failed tool, expected OBJECT")
    return "failed tool left the scene in Object mode"


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
        f"s.render.resolution_x = {RENDER_SIZE}\n"
        f"s.render.resolution_y = {RENDER_SIZE}\n"
        "s.render.resolution_percentage = 100\n"
    )
    ctx.conn.call("render_image", {"output_path": str(out)})
    if not out.exists():
        raise CheckFailed("render_image replied but wrote no file")
    data = out.read_bytes()
    if not data:
        raise CheckFailed("render_image wrote an empty file")
    try:
        width, height = png_size(data)
    except ValueError:
        raise CheckFailed(f"render_image output is not a PNG ({len(data)} bytes)") from None
    if width != RENDER_SIZE:
        raise CheckFailed(f"PNG is {width}x{height}, scene was set to {RENDER_SIZE} px wide")
    return f"wrote a {len(data)} byte {width}x{height} PNG"


def check_msfs_uv_layout_writes_file(ctx: Ctx) -> str:
    out = ctx.out_dir / "uv" / "lane_uv_layout.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    ctx.conn.exec(
        MAKE_CUBE
        + "ob = make('LaneUvCube', 2.0, (30, 0, 0))\nob.data.uv_layers.new(name='UVMap')\n"
    )
    reply = ctx.conn.call(
        "msfs_livery_export_uv_layout",
        {"object_name": "LaneUvCube", "output_path": str(out), "resolution": [64, 64]},
    )
    if isinstance(reply, dict) and "error" in reply:
        raise CheckFailed(f"export_uv_layout failed: {str(reply['error'])[:160]}")
    if not out.exists():
        raise CheckFailed("export_uv_layout replied but wrote no file")
    try:
        width, height = png_size(out.read_bytes())
    except ValueError:
        raise CheckFailed("export_uv_layout output is not a PNG") from None
    if width != 64:
        raise CheckFailed(f"PNG is {width}x{height}, asked for 64 px wide")
    return f"wrote a {width}x{height} PNG"


def check_msfs_paint_brush_after_setup(ctx: Ctx) -> str:
    ctx.conn.exec(
        MAKE_CUBE
        + "ob = make('LanePaintCube', 2.0, (40, 0, 0))\nob.data.uv_layers.new(name='UVMap')\n"
    )
    probe = (
        "b = bpy.context.tool_settings.image_paint.brush\n"
        "result = {'mode': bpy.context.mode, 'size': b.size, 'strength': b.strength,"
        " 'color': list(b.color)} if b else {'mode': bpy.context.mode}\n"
    )
    try:
        setup = ctx.conn.call(
            "msfs_livery_setup_paint_mode",
            {"object_name": "LanePaintCube", "texture_resolution": [64, 64]},
        )
        if isinstance(setup, dict) and "error" in setup:
            raise CheckFailed(f"setup_paint_mode failed: {str(setup['error'])[:160]}")
        reply = ctx.conn.call(
            "msfs_livery_set_paint_brush",
            {"size": 37, "strength": 0.42, "color": [0.1, 0.2, 0.3]},
        )
        if isinstance(reply, dict) and "error" in reply:
            raise CheckFailed(f"set_paint_brush failed: {str(reply['error'])[:160]}")
        got = ctx.conn.exec(probe)
        if got.get("size") != 37 or abs(got.get("strength", -1) - 0.42) > 1e-4:
            raise CheckFailed(f"brush did not change: {got}")
        if [round(c, 3) for c in got["color"]] != [0.1, 0.2, 0.3]:
            raise CheckFailed(f"brush colour did not change: {got}")
    finally:
        ctx.conn.exec("bpy.ops.object.mode_set(mode='OBJECT')\n")
    return "brush size, strength and colour read back as set"


def check_annotation_add_draws_or_says_why(ctx: Ctx) -> str:
    # Some series offer no Python call that creates an annotation stroke. There the tool must
    # say so and leave no empty layer behind; elsewhere the stroke must really exist, and
    # annotation_clear must remove it.
    count_code = (
        "sc = bpy.context.scene\n"
        "d = sc.annotation if hasattr(sc, 'annotation') else sc.grease_pencil\n"
        "layers = list(d.layers) if d else []\n"
        "result = [len(layers), sum(len(f.strokes) for l in layers for f in l.frames)]\n"
    )
    reply = ctx.conn.call(
        "annotation_add", {"points": [[0, 0, 0], [1, 1, 1], [2, 0, 1]], "layer_name": "LaneNote"}
    )
    layers, strokes = ctx.conn.exec(count_code)
    if reply.get("success") is True:
        if strokes != 1:
            raise CheckFailed(f"annotation_add reported success but {strokes} strokes exist")
        ctx.conn.call("annotation_clear", {})
        layers, strokes = ctx.conn.exec(count_code)
        if layers != 0:
            raise CheckFailed(f"annotation_clear left {layers} layers")
        return "annotation stroke was drawn and cleared"
    if not reply.get("error"):
        raise CheckFailed(f"annotation_add failed without an error: {str(reply)[:160]}")
    if layers != 0:
        raise CheckFailed(f"annotation_add failed but left {layers} layers behind")
    return "annotation_add explained why it cannot draw and left no layer"


PASS_SETUP = (
    MAKE_CUBE
    + """
import bmesh, numpy as np
from blender_mcp_addon import compat
from blender_mcp_addon.handlers import CommandHandlers

def make_sphere(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1.0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob

def load_rgba(path):
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    flat = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(flat)
    bpy.data.images.remove(img)
    return flat.reshape(h, w, 4)[::-1]  # row 0 is the top

def compositor_state(sc):
    tree = sc.compositing_node_group if hasattr(sc, 'compositing_node_group') else sc.node_tree
    return {
        'use_nodes': sc.use_nodes if hasattr(sc, 'use_nodes') else None,
        'has_tree': tree is not None,
        'nodes': sorted(n.name for n in tree.nodes) if tree else [],
        'z': sc.view_layers[0].use_pass_z,
        'normal': sc.view_layers[0].use_pass_normal,
        'engine': sc.render.engine,
        'film': sc.render.film_transparent,
        'res': [sc.render.resolution_x, sc.render.resolution_y],
        'filepath': sc.render.filepath,
        'scenes': len(bpy.data.scenes),
        'groups': len(bpy.data.node_groups),
        'objects': sorted(o.name for o in bpy.data.objects),
        'cameras': len(bpy.data.cameras),
    }
"""
)


def check_ai_texture_passes_are_real(ctx: Ctx) -> str:
    out = ctx.out_dir / "passes"
    out.mkdir(parents=True, exist_ok=True)
    got = ctx.conn.exec(
        PASS_SETUP
        + f"""
sc = bpy.context.scene
make_sphere('LanePass')
tree = compat.get_compositor_tree(sc)
tree.nodes.new('CompositorNodeBlur').name = 'LaneKeep'
before = compositor_state(sc)
h = CommandHandlers()
depth_path = h._render_control_image('LanePass', 'depth', 128)
normal_path = h._render_control_image('LanePass', 'normal', 128)
after = compositor_state(sc)
depth = load_rgba(depth_path)
normal = load_rgba(normal_path)
sc.render.resolution_x = sc.render.resolution_y = 128
sc.render.filepath = {str(out / "combined.png")!r}
sc.render.image_settings.file_format = 'PNG'
sc.render.use_compositing = False
bpy.ops.render.render(write_still=True)
combined = load_rgba({str(out / "combined.png")!r})
inside = depth[..., 3] > 0.5
d = depth[..., 0][inside]
n = normal[inside][:, :3]
result = {{
    'unchanged': before == after,
    'before': before, 'after': after,
    'keep_node': 'LaneKeep' in after['nodes'],
    'size': list(depth.shape[:2]),
    'covered': float(inside.mean()),
    'depth_grey': bool(np.allclose(depth[..., 0], depth[..., 1], atol=0.01) and np.allclose(depth[..., 0], depth[..., 2], atol=0.01)),
    'depth_distinct': int(len(np.unique(np.round(d, 2)))),
    'depth_min': float(d.min()), 'depth_max': float(d.max()),
    'background_clear': bool((depth[[0, 0, -1, -1], [0, -1, 0, -1]] == 0).all() and depth[..., :3][depth[..., 3] == 0].max() == 0),
    'depth_vs_combined': float(np.abs(depth[..., :3] - combined[..., :3]).mean()),
    'normal_vs_combined': float(np.abs(normal[..., :3] - combined[..., :3]).mean()),
    'normal_distinct': int(len(np.unique(np.round(n, 2), axis=0))),
    'normal_std': [float(x) for x in n.std(axis=0)],
    'normal_in_range': bool(n.min() >= 0.0 and n.max() <= 1.0),
    'normal_coloured': bool(np.abs(n[:, 0] - n[:, 2]).mean() > 0.02),
}}
import os
os.unlink(depth_path)
os.unlink(normal_path)
"""
    )
    if not got["unchanged"]:
        raise CheckFailed(f"the render changed scene state: {got['before']} -> {got['after']}")
    if not got["keep_node"]:
        raise CheckFailed("the existing compositor node did not survive")
    if got["size"] != [128, 128] or got["covered"] < 0.05:
        raise CheckFailed(
            f"object barely visible in the control image: {got['size']} {got['covered']}"
        )
    if (
        not got["depth_grey"]
        or got["depth_distinct"] < 20
        or got["depth_max"] - got["depth_min"] < 0.2
    ):
        raise CheckFailed(f"depth image has no gradient across the object: {got}")
    if got["depth_max"] < 0.5:
        raise CheckFailed(f"nearest surface is not light: {got['depth_max']}")
    if not got["background_clear"]:
        raise CheckFailed("depth background is not black and transparent")
    if got["depth_vs_combined"] < 0.05 or got["normal_vs_combined"] < 0.05:
        raise CheckFailed(f"pass images look like a Combined render: {got}")
    if got["normal_distinct"] < 50 or min(got["normal_std"]) < 0.03 or not got["normal_in_range"]:
        raise CheckFailed(f"normal image has no distinct colours per direction: {got}")
    if not got["normal_coloured"]:
        raise CheckFailed("normal image is grey, so it is not an RGB normal map")
    reply = ctx.conn.call(
        "ai_texture_from_render", {"object_name": "NoSuchLaneObject", "prompt": "x"}
    )
    if reply.get("success") is not False or "NoSuchLaneObject" not in str(reply.get("error")):
        raise CheckFailed(f"missing object did not give a clear error: {str(reply)[:200]}")
    return (
        f"depth {got['depth_distinct']} levels in {got['depth_min']:.2f}-{got['depth_max']:.2f}, "
        f"normal {got['normal_distinct']} colours, scene and compositor untouched"
    )


def check_grease_pencil_markup_draws_pixels(ctx: Ctx) -> str:
    out = ctx.out_dir / "markup"
    out.mkdir(parents=True, exist_ok=True)
    src, dst, text_dst = out / "src.png", out / "marked.png", out / "text_only.png"
    dst.unlink(missing_ok=True)
    text_dst.unlink(missing_ok=True)
    ctx.conn.exec(
        PASS_SETUP
        + f"""
yy, xx = np.mgrid[0:64, 0:64]
base = np.zeros((64, 64, 4), dtype=np.float32)
base[..., 0] = (xx * 3 + 20) / 255.0
base[..., 1] = (yy * 3 + 20) / 255.0
base[..., 2] = 100 / 255.0
base[..., 3] = 1.0
img = bpy.data.images.new('lane_src', 64, 64, alpha=True)
img.pixels.foreach_set(base[::-1].reshape(-1))
img.filepath_raw = {str(src)!r}
img.file_format = 'PNG'
img.save()
bpy.data.images.remove(img)
"""
    )
    annotations = [
        {"type": "rectangle", "start": [10, 10], "end": [30, 25], "color": "red", "thickness": 2},
        {"type": "circle", "center": [45, 45], "radius": 10, "color": "#0000ff", "thickness": 3},
        {"type": "arrow", "start": [5, 55], "end": [50, 58], "color": "lime", "thickness": 2},
        {"type": "text", "text": "note", "position": [4, 4]},
    ]
    reply = ctx.conn.call(
        "grease_pencil_markup",
        {"render_path": str(src), "annotations": annotations, "output_path": str(dst)},
    )
    if reply.get("success") is not True or reply.get("annotations_drawn") != 3:
        raise CheckFailed(f"expected 3 shapes drawn: {str(reply)[:300]}")
    if [item.get("type") for item in reply.get("skipped", [])] != ["text"]:
        raise CheckFailed(f"text was neither drawn nor reported as skipped: {str(reply)[:300]}")
    got = ctx.conn.exec(
        PASS_SETUP
        + f"""
before = load_rgba({str(src)!r})
after = load_rgba({str(dst)!r})
changed = np.abs(after - before).max(axis=2) > 0.003
def at(x, y):
    return [round(float(v), 2) for v in after[y, x, :3]]
boxes = [(6, 7, 34, 29), (32, 32, 58, 58), (2, 44, 63, 63)]
allowed = np.zeros_like(changed)
for x0, y0, x1, y1 in boxes:
    allowed[y0:y1 + 1, x0:x1 + 1] = True
result = {{
    'size': list(after.shape[:2]),
    'rect_edge': at(20, 10), 'rect_inside': bool(not changed[12:24, 12:29].any()),
    'circle_top': at(45, 35), 'circle_centre_same': bool(not changed[40:51, 40:51].any()),
    'arrow_mid': at(27, 56),
    'outside_changed': int(changed[~allowed].sum()),
    'per_box': [int(changed[y0:y1 + 1, x0:x1 + 1].sum()) for x0, y0, x1, y1 in boxes],
}}
"""
    )
    if got["size"] != [64, 64]:
        raise CheckFailed(f"output size changed: {got['size']}")
    if (
        got["rect_edge"][:2] != [1.0, 0.0]
        or got["circle_top"][2] != 1.0
        or got["arrow_mid"][1] != 1.0
    ):
        raise CheckFailed(f"shapes not where top-left coordinates put them: {got}")
    if not got["rect_inside"] or not got["circle_centre_same"]:
        raise CheckFailed("pixels inside the outlines changed")
    if got["outside_changed"] or min(got["per_box"]) == 0:
        raise CheckFailed(f"pixels changed away from the shapes, or a shape is missing: {got}")
    only_text = ctx.conn.call(
        "grease_pencil_markup",
        {
            "render_path": str(src),
            "annotations": [{"type": "text", "text": "x", "position": [1, 1]}],
            "output_path": str(text_dst),
        },
    )
    if only_text.get("success") is not False or only_text.get("annotations_drawn") != 0:
        raise CheckFailed(f"a text-only call must report failure: {str(only_text)[:300]}")
    if text_dst.exists():
        raise CheckFailed("a call that drew nothing still wrote an output file")
    try:
        ctx.conn.call(
            "grease_pencil_markup",
            {"render_path": str(src), "annotations": annotations[:1], "output_path": ""},
        )
    except RpcError:
        pass
    else:
        raise CheckFailed("an empty output_path was accepted")
    return f"3 shapes drawn in place ({got['per_box']} pixels changed), none outside, text reported skipped"


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


def check_failed_call_adds_no_undo_step(ctx: Ctx) -> str:
    # Count steps by effect: one undo must revert the last good change. If the
    # failed call had pushed a step of its own, that undo would only consume it.
    ctx.conn.call("object_create", {"type": "cube", "name": "LaneFailA"})
    ctx.conn.call("object_create", {"type": "cube", "name": "LaneFailB"})
    try:
        reply = ctx.conn.call("object_delete", {"name": "LaneNoSuchObject"})
    except RpcError:
        pass  # the expected failure
    else:
        raise CheckFailed(f"setup: deleting a missing object did not fail: {reply}")
    undo = ctx.conn.call("undo")
    if isinstance(undo, dict) and undo.get("success") is False:
        raise CheckFailed(f"undo reported failure: {undo.get('error')}")
    names = _names(ctx.conn)
    if "LaneFailB" in names:
        raise CheckFailed("the failed call added an undo step: one undo did not revert LaneFailB")
    if "LaneFailA" not in names:
        raise CheckFailed("undo removed more than the last change (LaneFailA is gone)")
    return "failed call left the undo stack alone"


def check_execute_script_stdout(ctx: Ctx) -> str:
    # The expected text is computed inside Blender, so echoing the source cannot pass.
    expected = "lane-" + str(6 * 7 * 1000 + 1)
    res = ctx.conn.call("execute_script", {"script": "print('lane-' + str(6 * 7 * 1000 + 1))"})
    if not res.get("success"):
        raise CheckFailed(f"execute_script reported failure: {res.get('error')}")
    stdout = res.get("stdout", "").strip()
    if stdout != expected:
        raise CheckFailed(f"stdout {stdout!r}, expected {expected!r}")
    return "computed text came back in stdout"


def check_execute_script_refused_when_off(ctx: Ctx) -> str:
    # The expected text and the switch both come from the add-on's own security module.
    set_flag = (
        "from blender_mcp_addon import security\n"
        "security.set_python_allowed({on})\n"
        "result = security.PYTHON_OFF_ERROR\n"
    )
    script = "import bpy\nbpy.data.objects.new('LaneRefused', None)\n"
    try:
        expected = ctx.conn.exec(set_flag.format(on=False))
        before = ctx.conn.call("scene_info")["object_count"]
        res = ctx.conn.call("execute_script", {"script": script})
        after = ctx.conn.call("scene_info")["object_count"]
    finally:
        ctx.conn.exec(set_flag.format(on=True))
    if res.get("success") is not False:
        raise CheckFailed(f"execute_script ran with Python off: {str(res)[:120]}")
    if res.get("error") != expected:
        raise CheckFailed(f"error {res.get('error')!r}, expected {expected!r}")
    if after != before or "LaneRefused" in _names(ctx.conn):
        raise CheckFailed("the refused script still created an object")
    ok = ctx.conn.call("execute_script", {"script": "result = 1 + 1"})
    if not ok.get("success") or ok.get("result") != 2:
        raise CheckFailed(f"execute_script did not run after the switch came back on: {ok}")
    return "refused with the exact text and no object, ran again once the switch was on"


BIG_UNIT = "abcdefghijklmnopqrstuvwxyz0123456789"
BIG_SCRIPT = (
    f"unit = {BIG_UNIT!r}\nn = {BIG_REPLY_BYTES}\nresult = (unit * (n // len(unit) + 1))[:n]\n"
)


def check_reply_32mb_complete(ctx: Ctx) -> str:
    expected = (BIG_UNIT * (BIG_REPLY_BYTES // len(BIG_UNIT) + 1))[:BIG_REPLY_BYTES]
    res = ctx.conn.call("execute_script", {"script": BIG_SCRIPT})
    got = res.get("result")
    if not isinstance(got, str):
        raise CheckFailed(f"reply result is {type(got).__name__}, expected str")
    if len(got) != len(expected):
        raise CheckFailed(f"reply result is {len(got)} chars, expected {len(expected)}")
    if got != expected:
        raise CheckFailed("reply result has the right length but different content")
    return "32 MiB reply arrived complete and intact"


def _expect_eof(sock: socket.socket, budget: Budget) -> None:
    """Read until the peer closes. Anything but a clean close fails the check."""
    while True:
        left = budget.remaining()
        if left <= 0:
            raise CheckFailed("the connection stayed open after the error reply")
        sock.settimeout(left)
        try:
            data = sock.recv(65536)
        except (socket.timeout, TimeoutError):
            raise CheckFailed("the connection stayed open after the error reply") from None
        except OSError as exc:
            raise CheckFailed(f"the connection broke instead of closing cleanly: {exc}") from exc
        if not data:
            return


def check_malformed_json_error_reply(ctx: Ctx) -> str:
    ctx.conn.send_raw(b"{this is not json\n")
    reply = read_reply(ctx.conn.sock, ctx.conn.budget)
    if "error" not in reply:
        raise CheckFailed(f"malformed request got a non-error reply: {str(reply)[:80]}")
    code = reply["error"].get("code")
    if code != -32700:
        raise CheckFailed(f"error code {code}, expected -32700 (parse error)")
    _expect_eof(ctx.conn.sock, ctx.conn.budget)
    fresh = ctx.conn.fresh()
    try:
        if fresh.call("ping").get("pong") is not True:
            raise CheckFailed("fresh connection unusable after a malformed request")
    finally:
        fresh.close()
    return "parse error reply, then close; a fresh connection works"


def check_client_vanishes_mid_reply(ctx: Ctx) -> str:
    gone = ctx.conn.fresh()
    try:
        gone.send_raw(encode_request(1, "execute_script", {"script": BIG_SCRIPT}))
        gone.sock.settimeout(max(ctx.conn.budget.remaining(), 0.1))
        if not gone.sock.recv(4096):
            raise CheckFailed("the server closed before sending any of the reply")
        # Reset the connection while most of the reply is still queued in Blender.
        gone.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    finally:
        gone.close()
    if ctx.conn.call("ping").get("pong") is not True:
        raise CheckFailed("the surviving connection stopped answering")
    fresh = ctx.conn.fresh()
    try:
        res = fresh.call("execute_script", {"script": "result = 6 * 7"})
    finally:
        fresh.close()
    if res.get("result") != 42:
        raise CheckFailed(f"a new client got {res!r} after one vanished mid-reply")
    return "client reset mid-reply; the server kept running and served the next client"


def _read_until_closed(sock: socket.socket, budget: Budget, what: str) -> bytes:
    """Read until the peer closes and return every byte it sent first.

    A reset counts as a close: the add-on drops a connection that still has unread
    bytes in its receive queue, and the kernel then sends RST instead of FIN.
    """
    got = bytearray()
    while True:
        left = budget.remaining()
        if left <= 0:
            raise CheckFailed(f"the connection stayed open: {what}")
        sock.settimeout(left)
        try:
            data = sock.recv(65536)
        except (socket.timeout, TimeoutError):
            raise CheckFailed(f"the connection stayed open: {what}") from None
        except ConnectionResetError:
            return bytes(got)
        if not data:
            return bytes(got)
        got += data


def _object_exists(ctx: Ctx, name: str) -> bool:
    return bool(ctx.conn.exec(f"result = {name!r} in bpy.data.objects"))


def check_http_post_rejected(ctx: Ctx) -> str:
    """A web page can POST to a local port. The add-on must close and run nothing."""
    name = "HttpPostCube"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "object_create",
            "params": {"type": "cube", "name": name},
        }
    ).encode("utf-8")
    request = (
        b"POST / HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: text/plain\r\n"
        + b"Content-Length: %d\r\n\r\n" % len(body)
        + body
        + b"\n"
    )
    raw = ctx.conn.fresh(authed=False)
    try:
        raw.send_raw(request)
        sent = _read_until_closed(raw.sock, raw.budget, "after an HTTP POST")
    finally:
        raw.close()
    if _object_exists(ctx, name):
        raise CheckFailed("the HTTP POST created an object")
    if sent:
        raise CheckFailed(f"the add-on answered an HTTP POST with {len(sent)} bytes: {sent[:80]!r}")
    return "HTTP POST closed with no reply and no object created"


def check_unauthenticated_call_refused(ctx: Ctx) -> str:
    name = "NoHelloCube"
    raw = ctx.conn.fresh(authed=False)
    try:
        raw.send_raw(encode_request(1, "object_create", {"type": "cube", "name": name}))
        sent = _read_until_closed(raw.sock, raw.budget, "after a call with no hello")
    finally:
        raw.close()
    if _object_exists(ctx, name):
        raise CheckFailed("a call with no hello created an object")
    if b"-32002" not in sent:
        raise CheckFailed(f"expected the E_PROTOCOL reply, got {sent[:80]!r}")
    return "a call with no hello ran nothing and was told to update"


def check_wrong_token_rejected(ctx: Ctx) -> str:
    raw = ctx.conn.fresh(authed=False)
    try:
        nonce_c, result = raw.hello()
        wrong = proof("not-the-token", "meshwire-client", result["nonce"], nonce_c)
        raw.send_raw(
            encode_request(7, "hello_proof", {"proof": wrong}) + encode_request(8, "ping", {})
        )
        data = _read_until_closed(raw.sock, raw.budget, "after a wrong proof")
    finally:
        raw.close()
    lines = [json.loads(line) for line in data.split(b"\n") if line.strip()]
    if len(lines) != 1:
        raise CheckFailed(f"expected exactly one reply, got {len(lines)}")
    error = lines[0].get("error") or {}
    if error.get("code") != -32001 or lines[0].get("id") != 7:
        raise CheckFailed(f"expected E_UNAUTHORIZED for id 7, got {lines[0]!r}")
    if ctx.conn.call("ping").get("pong") is not True:
        raise CheckFailed("the authenticated connection stopped answering")
    return "wrong token got one -32001 reply, then a close; the real client kept working"


def check_old_client_told_to_update(ctx: Ctx) -> str:
    raw = ctx.conn.fresh(authed=False)
    try:
        raw.send_raw(encode_request(3, "ping", {}))
        data = _read_until_closed(raw.sock, raw.budget, "after a request with no hello")
    finally:
        raw.close()
    lines = [json.loads(line) for line in data.split(b"\n") if line.strip()]
    if len(lines) != 1:
        raise CheckFailed(f"expected exactly one reply, got {len(lines)}")
    error = lines[0].get("error") or {}
    if error.get("code") != -32002 or lines[0].get("id") != 3:
        raise CheckFailed(f"expected E_PROTOCOL for id 3, got {lines[0]!r}")
    if "newer Meshwire server" not in error.get("message", ""):
        raise CheckFailed(f"the message does not say to update the server: {error!r}")
    return "a client that never says hello was told to update the server, then closed"


def check_hello_timeout_closes(ctx: Ctx) -> str:
    started = time.monotonic()
    silent = ctx.conn.fresh(authed=False)
    try:
        sent = _read_until_closed(silent.sock, Budget(6.0), "with no hello sent")
    finally:
        silent.close()
    waited = time.monotonic() - started
    if sent:
        raise CheckFailed(f"a silent client was sent {sent[:80]!r}")
    if not 1.5 <= waited <= 5.0:
        raise CheckFailed(f"closed after {waited:.1f}s, expected about 2s")
    # The deadline covers both lines: a hello with no hello_proof is closed too.
    started = time.monotonic()
    half = ctx.conn.fresh(authed=False)
    try:
        half.hello()
        sent = _read_until_closed(half.sock, Budget(6.0), "after hello with no proof")
    finally:
        half.close()
    if sent:
        raise CheckFailed(f"a client that stalled after hello was sent {sent[:80]!r}")
    if time.monotonic() - started > 5.0:
        raise CheckFailed("a client that stalled after hello was held past the deadline")
    # The deadline is for the handshake only: an authenticated client idle past it stays.
    if ctx.conn.call("ping").get("pong") is not True:
        raise CheckFailed("the authenticated connection was dropped")
    return f"a silent client was closed after {waited:.1f}s; the authenticated one stayed"


def check_copy_token_matches_running_server(ctx: Ctx) -> str:
    """With the token file gone, Copy token must still give the token the server accepts."""
    path = ctx.out_dir / "config" / "token"  # the run's own folder (BlenderSession)
    saved = path.read_bytes()
    path.unlink()
    try:
        copied = ctx.conn.exec(
            "bpy.context.window_manager.clipboard = ''\n"
            "r = bpy.ops.meshwire.copy_token()\n"
            "result = [list(r), bpy.context.window_manager.clipboard]"
        )
        if copied[0] != ["FINISHED"] or not copied[1]:
            raise CheckFailed(f"copy_token did not put a token on the clipboard: {copied[0]!r}")
        if path.exists():
            raise CheckFailed("copy_token wrote a new token file under a running server")
        try:
            Conn(ctx.conn.port, ctx.conn.budget, copied[1]).close()
        except (CheckFailed, ConnectionClosed, BadReply, ReplyTimeout, OSError) as exc:
            raise CheckFailed(
                f"the server does not accept the copied token ({type(exc).__name__})"
            ) from None
    finally:
        path.write_bytes(saved)
        path.chmod(0o600)
    return "Copy token yields the token the running server accepts, even with the file gone"


BAKE_SIZE = 32
BAKE_ARGS = {"resolution": BAKE_SIZE, "samples": 1, "margin": 2}

# Shared Blender-side helpers for the bake checks. ``snapshot`` records everything a
# bake could disturb in a material: node set, link endpoints, every socket default,
# selection, the active node and active output, plus slots and face material indices.
BAKE_SETUP = """
import bmesh

def _val(v):
    try:
        return round(float(v), 5)
    except (TypeError, ValueError):
        pass
    try:
        return [round(float(x), 5) for x in v]
    except (TypeError, ValueError):
        return None

def principled(tree):
    return next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')

def _plain(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, set):
        return sorted(v)
    try:
        return [_plain(x) for x in v]
    except TypeError:
        return str(v)

def scene_state():
    sc = bpy.context.scene
    state = {}
    owners = [
        ('render', sc.render, lambda n: n == 'engine' or 'bake' in n),
        ('bake', sc.render.bake, lambda n: True),
        ('cycles', sc.cycles, lambda n: n == 'samples'),
    ]
    for label, owner, pick in owners:
        for prop in owner.bl_rna.properties:
            if prop.type == 'POINTER' or prop.identifier == 'rna_type' or not pick(prop.identifier):
                continue
            state[label + '.' + prop.identifier] = _plain(getattr(owner, prop.identifier))
    layer = bpy.context.view_layer
    state['selected'] = sorted(o.name for o in layer.objects if o.select_get())
    state['active'] = layer.objects.active.name if layer.objects.active else None
    return state

def make_material(name, metallic_linked=False, displacement=False, cycles_output=False):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    t = mat.node_tree
    bsdf = principled(t)
    out = next(n for n in t.nodes if n.type == 'OUTPUT_MATERIAL')
    chk = t.nodes.new('ShaderNodeTexChecker')
    chk.inputs['Color1'].default_value = (1, 0, 0, 1)
    chk.inputs['Color2'].default_value = (0, 1, 0, 1)
    chk.inputs['Scale'].default_value = 2.0
    t.links.new(chk.outputs['Color'], bsdf.inputs['Base Color'])
    bsdf.inputs['Metallic'].default_value = 0.8
    if metallic_linked:
        val = t.nodes.new('ShaderNodeValue')
        val.outputs[0].default_value = 0.8
        t.links.new(val.outputs[0], bsdf.inputs['Metallic'])
        bsdf.inputs['Metallic'].default_value = 0.1
    if displacement:
        val = t.nodes.new('ShaderNodeValue')
        val.outputs[0].default_value = 0.9
        disp = t.nodes.new('ShaderNodeDisplacement')
        t.links.new(val.outputs[0], disp.inputs['Height'])
        t.links.new(disp.outputs['Displacement'], out.inputs['Displacement'])
    if cycles_output:
        # A Cycles-only output that wins over the default one, feeding a plain diffuse.
        alt = t.nodes.new('ShaderNodeOutputMaterial')
        alt.target = 'CYCLES'
        diff = t.nodes.new('ShaderNodeBsdfDiffuse')
        t.links.new(diff.outputs[0], alt.inputs['Surface'])
        alt.is_active_output = True
    return mat

def make_grid(name, loc, mats=(), uvs=True):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=3, y_subdivisions=3, size=2,
                                    location=loc, calc_uvs=uvs)
    ob = bpy.context.active_object
    ob.name = name
    if not uvs:
        while ob.data.uv_layers:
            ob.data.uv_layers.remove(ob.data.uv_layers[0])
    for m in mats:
        ob.data.materials.append(m)
    if len(mats) > 1:
        for i, poly in enumerate(ob.data.polygons):
            poly.material_index = i % len(mats)
    return ob

def snapshot(names):
    out = {}
    for name in names:
        ob = bpy.data.objects[name]
        out['obj:' + name] = {
            'slots': [(s.link, s.material.name if s.material else None) for s in ob.material_slots],
            'data_mats': [m.name if m else None for m in ob.data.materials],
            'indices': [p.material_index for p in ob.data.polygons],
        }
    for mat in bpy.data.materials:
        t = mat.node_tree
        if t is None:
            out['mat:' + mat.name] = None
            continue
        nodes = {}
        for n in t.nodes:
            nodes[n.name] = {
                'type': n.bl_idname, 'loc': _val(n.location), 'select': n.select, 'mute': n.mute,
                'active_output': getattr(n, 'is_active_output', None),
                'inputs': {s.identifier: _val(getattr(s, 'default_value', None)) for s in n.inputs},
            }
        links = sorted(
            (l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier,
             l.is_muted) for l in t.links)
        out['mat:' + mat.name] = {
            'nodes': nodes, 'links': links,
            'active': t.nodes.active.name if t.nodes.active else None,
        }
    out['images'] = sorted(i.name for i in bpy.data.images)
    out['scene'] = scene_state()
    return out

def image_mean(path):
    img = bpy.data.images.load(path, check_existing=False)
    px = list(img.pixels)
    bpy.data.images.remove(img)
    rgb = [px[i] for i in range(len(px)) if i % 4 != 3]
    pixels = {tuple(round(px[i + k], 2) for k in range(3)) for i in range(0, len(px), 4)}
    return {'mean': sum(rgb) / len(rgb), 'distinct': len(pixels)}
"""


def _diff_snapshots(before: dict, after: dict) -> str | None:
    """Name the first thing that differs between two bake snapshots, or None."""
    for key in sorted(set(before) | set(after)):
        if before.get(key) == after.get(key):
            continue
        b, a = before.get(key), after.get(key)
        if isinstance(b, dict) and isinstance(a, dict):
            for sub in sorted(set(b) | set(a)):
                if b.get(sub) != a.get(sub):
                    return f"{key}/{sub}: {str(b.get(sub))[:140]} -> {str(a.get(sub))[:140]}"
        return f"{key}: {str(b)[:140]} -> {str(a)[:140]}"
    return None


def _bake_dir(ctx: Ctx, name: str) -> Path:
    path = ctx.out_dir / "bake" / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


def check_bake_pbr_writes_image(ctx: Ctx) -> str:
    out = _bake_dir(ctx, "pbr")
    ctx.conn.exec(
        BAKE_SETUP + "make_grid('LaneBake', (50, 0, 0), [make_material('LaneBakeMat')])\n"
    )
    reply = ctx.conn.call(
        "bake_pbr_batch",
        {"object_name": "LaneBake", "output_dir": str(out), "channels": ["DIFFUSE"], **BAKE_ARGS},
    )
    if "error" in reply or reply.get("errors"):
        raise CheckFailed(f"bake_pbr_batch failed: {str(reply)[:200]}")
    path = Path(reply.get("baked_files", {}).get("DIFFUSE", ""))
    if not path.is_file():
        raise CheckFailed(f"bake replied {str(reply)[:160]} but wrote no DIFFUSE file")
    got = ctx.conn.exec(BAKE_SETUP + f"result = image_mean({str(path)!r})\n")
    if got["distinct"] < 2 or got["mean"] < 0.01:
        raise CheckFailed(f"baked image is uniform ({got})")
    return f"wrote {path.name}, {got['distinct']} distinct values"


def check_bake_leaves_material_clean(ctx: Ctx) -> str:
    out = _bake_dir(ctx, "clean")
    ctx.conn.exec(
        BAKE_SETUP + "make_grid('LaneClean', (50, 0, 0), [make_material('LaneCleanMat')])\n"
    )
    probe = BAKE_SETUP + "result = snapshot(['LaneClean'])\n"
    (out / "blocked_DIFFUSE.png").mkdir()
    before = ctx.conn.exec(probe)
    ran = []
    # A directory where the output file should go makes the save fail after the image
    # node is added; a bogus normal space
    # raises inside the bake setup. Both must leave the material as found.
    for label, extra in (
        ("unwritable path", {"channels": ["DIFFUSE"], "output_prefix": "blocked"}),
        ("raising bake", {"channels": ["NORMAL"], "normal_space": "BOGUS"}),
        ("no channels", {"channels": []}),
    ):
        reply = ctx.conn.call(
            "bake_pbr_batch",
            {"object_name": "LaneClean", "output_dir": str(out), **BAKE_ARGS, **extra},
        )
        if "error" not in reply or reply.get("success"):
            raise CheckFailed(f"{label}: expected an error reply, got {str(reply)[:160]}")
        if any(p.is_file() for p in out.iterdir()):
            raise CheckFailed(f"{label}: files were written")
        moved = _diff_snapshots(before, ctx.conn.exec(probe))
        if moved:
            raise CheckFailed(f"{label}: material changed: {moved}")
        ran.append(label)
    reply = ctx.conn.call(
        "bake_pbr_batch",
        {"object_name": "LaneClean", "output_dir": str(out), "channels": ["DIFFUSE"], **BAKE_ARGS},
    )
    if "error" in reply or reply.get("errors"):
        raise CheckFailed(f"successful bake failed: {str(reply)[:160]}")
    moved = _diff_snapshots(before, ctx.conn.exec(probe))
    if moved:
        raise CheckFailed(f"material changed after a successful bake: {moved}")
    return (
        "nodes, links, defaults, selection and images unchanged after "
        + ", ".join(ran)
        + ", success"
    )


def check_bake_tricks_leave_material_clean(ctx: Ctx) -> str:
    out = _bake_dir(ctx, "tricks")
    ctx.conn.exec(
        BAKE_SETUP
        + "make_grid('LaneMetLink', (50, 0, 0), [make_material('LaneMetLinkMat', metallic_linked=True)])\n"
        "make_grid('LaneMetDef', (52, 0, 0), [make_material('LaneMetDefMat')])\n"
        "make_grid('LaneDispLink', (54, 0, 0), [make_material('LaneDispLinkMat', displacement=True)])\n"
        "make_grid('LaneDispNone', (56, 0, 0), [make_material('LaneDispNoneMat')])\n"
        "make_grid('LaneMetCycles', (58, 0, 0), [make_material('LaneMetCyclesMat', cycles_output=True)])\n"
    )
    names = ["LaneMetLink", "LaneMetDef", "LaneDispLink", "LaneDispNone", "LaneMetCycles"]
    probe = BAKE_SETUP + f"result = snapshot({names!r})\n"
    before = ctx.conn.exec(probe)
    # (object, channel, expected mean of the baked map)
    cases = [
        ("LaneMetLink", "METALLIC", 0.8),
        ("LaneMetDef", "METALLIC", 0.8),
        ("LaneMetCycles", "METALLIC", 0.8),
        ("LaneDispLink", "DISPLACEMENT", 0.9),
        ("LaneDispNone", "DISPLACEMENT", 0.5),
    ]
    for obj, channel, want in cases:
        (out / f"blocked_{channel}.png").mkdir(exist_ok=True)
        bad = ctx.conn.call(
            "bake_pbr_batch",
            {
                "object_name": obj,
                "output_dir": str(out),
                "channels": [channel],
                "output_prefix": "blocked",
                **BAKE_ARGS,
            },
        )
        if "error" not in bad:
            raise CheckFailed(f"{obj} {channel}: unwritable path gave no error: {str(bad)[:140]}")
        moved = _diff_snapshots(before, ctx.conn.exec(probe))
        if moved:
            raise CheckFailed(f"{obj} {channel}: material changed after a failed bake: {moved}")
        good = ctx.conn.call(
            "bake_pbr_batch",
            {
                "object_name": obj,
                "output_dir": str(out),
                "channels": [channel],
                "output_prefix": obj,
                **BAKE_ARGS,
            },
        )
        path = good.get("baked_files", {}).get(channel) if isinstance(good, dict) else None
        if not path or not Path(path).is_file():
            raise CheckFailed(f"{obj} {channel}: no file written: {str(good)[:160]}")
        moved = _diff_snapshots(before, ctx.conn.exec(probe))
        if moved:
            raise CheckFailed(f"{obj} {channel}: material changed after a good bake: {moved}")
        mean = ctx.conn.exec(BAKE_SETUP + f"result = image_mean({path!r})\n")["mean"]
        if abs(mean - want) > 0.03:
            raise CheckFailed(f"{obj} {channel}: baked mean {mean:.3f}, expected {want}")
    return (
        "metallic and displacement tricks baked the right value, also past a Cycles-only "
        "output, and left linked and default sockets as found"
    )


def check_bake_odd_materials(ctx: Ctx) -> str:
    out = _bake_dir(ctx, "odd")
    ctx.conn.exec(
        BAKE_SETUP + "shared = make_material('LaneShared')\n"
        "other = make_material('LaneOther')\n"
        "make_grid('LaneShareA', (50, 0, 0), [shared, None, other])\n"
        "make_grid('LaneShareB', (52, 0, 0), [shared])\n"
        "make_grid('LaneNoMat', (54, 0, 0))\n"
        "make_grid('LaneEmptySlot', (56, 0, 0), [None])\n"
        "make_grid('LaneHigh', (58, 0, 0))\n"
    )
    names = ["LaneShareA", "LaneShareB", "LaneNoMat", "LaneEmptySlot", "LaneHigh"]
    probe = BAKE_SETUP + f"result = snapshot({names!r})\n"
    before = ctx.conn.exec(probe)

    def pbr(obj):
        return ctx.conn.call(
            "bake_pbr_batch",
            {
                "object_name": obj,
                "output_dir": str(out),
                "channels": ["DIFFUSE"],
                "output_prefix": obj,
                **BAKE_ARGS,
            },
        )

    for obj in ("LaneNoMat", "LaneEmptySlot"):
        reply = pbr(obj)
        if "error" not in reply or "material" not in str(reply["error"]).lower():
            raise CheckFailed(f"{obj}: expected a clear material error, got {str(reply)[:160]}")
    reply = pbr("LaneShareA")
    if "error" in reply or reply.get("errors"):
        raise CheckFailed(f"shared/multi-slot bake failed: {str(reply)[:160]}")
    if "[1]" not in " ".join(reply.get("warnings", [])):
        raise CheckFailed(f"empty slot 1 was not named in warnings: {str(reply)[:200]}")
    reply = ctx.conn.call(
        "bake_highpoly_to_lowpoly",
        {
            "lowpoly_name": "LaneNoMat",
            "highpoly_name": "LaneHigh",
            "output_dir": str(out),
            "channels": ["NORMAL"],
            "cage_extrusion": 0.5,
            **BAKE_ARGS,
        },
    )
    if "error" in reply or reply.get("errors"):
        raise CheckFailed(f"highpoly to lowpoly with no material failed: {str(reply)[:200]}")
    reply = ctx.conn.call(
        "bake_highpoly_to_lowpoly",
        {
            "lowpoly_name": "LaneShareB",
            "highpoly_name": "LaneHigh",
            "output_dir": str(out),
            "channels": ["METALLIC"],
            "cage_extrusion": 0.5,
            **BAKE_ARGS,
        },
    )
    if "error" not in reply or "material" not in str(reply).lower():
        raise CheckFailed(
            f"a metallic bake from a highpoly with no material gave: {str(reply)[:200]}"
        )
    moved = _diff_snapshots(before, ctx.conn.exec(probe))
    if moved:
        raise CheckFailed(f"scene changed: {moved}")
    return (
        "no/empty material gives an error; shared, multi-slot and no-material bakes leave the "
        "scene as found; an empty slot is named in warnings"
    )


def check_bake_id_map_restores_slots(ctx: Ctx) -> str:
    out = _bake_dir(ctx, "idmap")
    ctx.conn.exec(
        BAKE_SETUP
        + "make_grid('LaneIds', (50, 0, 0), [make_material('LaneIdA'), make_material('LaneIdB')])\n"
        "make_grid('LaneIdsBare', (52, 0, 0))\n"
    )
    probe = BAKE_SETUP + "result = snapshot(['LaneIds', 'LaneIdsBare'])\n"
    before = ctx.conn.exec(probe)
    for obj in ("LaneIds", "LaneIdsBare"):
        for mode in ("PER_MATERIAL", "PER_OBJECT", "PER_FACE_SET"):
            path = out / f"{obj}_{mode}.png"
            reply = ctx.conn.call(
                "bake_id_map",
                {
                    "object_name": obj,
                    "output_path": str(path),
                    "resolution": BAKE_SIZE,
                    "color_mode": mode,
                },
            )
            if "error" in reply or not path.is_file():
                raise CheckFailed(f"{obj} {mode}: bake_id_map failed: {str(reply)[:160]}")
            moved = _diff_snapshots(before, ctx.conn.exec(probe))
            if moved:
                raise CheckFailed(f"{obj} {mode}: slots, indices or materials changed: {moved}")
    blocked = out / "blocked.png"
    blocked.mkdir()
    bad = ctx.conn.call(
        "bake_id_map",
        {
            "object_name": "LaneIds",
            "output_path": str(blocked),
            "resolution": BAKE_SIZE,
            "color_mode": "PER_OBJECT",
        },
    )
    if "error" not in bad:
        raise CheckFailed(f"unwritable id map path gave no error: {str(bad)[:140]}")
    moved = _diff_snapshots(before, ctx.conn.exec(probe))
    if moved:
        raise CheckFailed(f"after a failed id map ({str(bad)[:80]}): {moved}")
    return "all colour modes, and a failure, restored slots, face indices and materials"


def check_bake_multires_writes_image(ctx: Ctx) -> str:
    out = _bake_dir(ctx, "multires")
    # A sphere whose top multires level is reshaped to a perturbed copy, so the top
    # level really differs from the lower ones. An unsculpted multires has no
    # displacement, and a level baked to itself carries nothing.
    ctx.conn.exec(
        BAKE_SETUP + "import random\n"
        "bpy.ops.mesh.primitive_uv_sphere_add(segments=8, ring_count=6, location=(60, 0, 0))\n"
        "ob = bpy.context.active_object\n"
        "ob.name = 'LaneMultires'\n"
        "src = ob.copy()\n"
        "src.data = ob.data.copy()\n"
        "bpy.context.collection.objects.link(src)\n"
        "sub = src.modifiers.new('Sub', 'SUBSURF')\n"
        "sub.levels = 2\n"
        "bpy.context.view_layer.objects.active = src\n"
        "bpy.ops.object.modifier_apply(modifier='Sub')\n"
        "random.seed(1)\n"
        "for v in src.data.vertices:\n"
        "    v.co = v.co + v.normal * random.uniform(-0.15, 0.15)\n"
        "mod = ob.modifiers.new('Multires', 'MULTIRES')\n"
        "bpy.context.view_layer.objects.active = ob\n"
        "for _ in range(2):\n"
        "    bpy.ops.object.multires_subdivide(modifier=mod.name, mode='CATMULL_CLARK')\n"
        "bpy.ops.object.select_all(action='DESELECT')\n"
        "src.select_set(True)\n"
        "ob.select_set(True)\n"
        "bpy.context.view_layer.objects.active = ob\n"
        "bpy.ops.object.multires_reshape(modifier=mod.name)\n"
        "bpy.data.objects.remove(src)\n"
        "ob.select_set(True)\n"
        "bpy.context.view_layer.objects.active = ob\n"
    )
    probe = (
        BAKE_SETUP + "ob = bpy.data.objects['LaneMultires']\n"
        "mod = ob.modifiers['Multires']\n"
        "result = {'snapshot': snapshot(['LaneMultires']), 'levels': mod.levels,"
        " 'total': mod.total_levels}\n"
    )
    before = ctx.conn.exec(probe)
    if before["total"] != 2:
        raise CheckFailed(f"setup: expected 2 multires levels, got {before['total']}")
    done = []
    # At the top level the tool bakes to level 0; below it, to the user's level.
    for start_level, want_level in ((2, 0), (1, 1)):
        ctx.conn.exec(
            f"bpy.data.objects['LaneMultires'].modifiers['Multires'].levels = {start_level}\n"
        )
        before = ctx.conn.exec(probe)
        for map_type in ("NORMALS", "DISPLACEMENT"):
            path = out / f"{map_type}_{start_level}.png"
            reply = ctx.conn.call(
                "bake_from_multires",
                {
                    "object_name": "LaneMultires",
                    "output_path": str(path),
                    "map_type": map_type,
                    "resolution": BAKE_SIZE,
                    "margin": 2,
                },
            )
            if "error" in reply or not path.is_file():
                raise CheckFailed(f"{map_type} from level {start_level}: {str(reply)[:200]}")
            if reply.get("bake_level") != want_level:
                raise CheckFailed(
                    f"{map_type}: baked to level {reply.get('bake_level')}, want {want_level}"
                )
            after = ctx.conn.exec(probe)
            moved = _diff_snapshots(before["snapshot"], after["snapshot"])
            if moved or after["levels"] != before["levels"]:
                raise CheckFailed(
                    f"{map_type} from level {start_level}: state changed: {moved}, "
                    f"levels {before['levels']} -> {after['levels']}"
                )
            got = ctx.conn.exec(BAKE_SETUP + f"result = image_mean({str(path)!r})\n")
            if got["distinct"] < 8:
                raise CheckFailed(f"{map_type} from level {start_level}: flat map ({got})")
            done.append(f"{map_type[:4]}@{start_level}={got['distinct']}")
    # A failing bake. At the top level the tool drops to level 0 before it bakes, and
    # the save fails afterwards: the output path is an existing directory, so the
    # parent exists and nothing fails before the level has been changed.
    ctx.conn.exec("bpy.data.objects['LaneMultires'].modifiers['Multires'].levels = 2\n")
    before = ctx.conn.exec(probe)
    reply = ctx.conn.call(
        "bake_from_multires",
        {
            "object_name": "LaneMultires",
            "output_path": str(out),
            "map_type": "NORMALS",
            "resolution": BAKE_SIZE,
            "margin": 2,
        },
    )
    if not (isinstance(reply, dict) and "error" in reply):
        raise CheckFailed(f"unwritable output_path: expected an error, got {str(reply)[:160]}")
    after = ctx.conn.exec(probe)
    moved = _diff_snapshots(before["snapshot"], after["snapshot"])
    if after["levels"] != 2 or moved:
        raise CheckFailed(
            f"failed bake left state changed: levels {before['levels']} -> {after['levels']}, {moved}"
        )
    return (
        "multires maps carry detail (distinct pixels "
        + ", ".join(done)
        + "); level, scene and material restored, also after a failed bake"
    )


def check_bake_without_uvs_errors(ctx: Ctx) -> str:
    out = _bake_dir(ctx, "nouv")
    ctx.conn.exec(
        BAKE_SETUP
        + "make_grid('LaneNoUv', (50, 0, 0), [make_material('LaneNoUvMat')], uvs=False)\n"
    )
    reply = ctx.conn.call(
        "bake_pbr_batch", {"object_name": "LaneNoUv", "output_dir": str(out), **BAKE_ARGS}
    )
    if not (isinstance(reply, dict) and "error" in reply):
        raise CheckFailed(f"expected an error, got {str(reply)[:160]}")
    if "uv" not in str(reply["error"]).lower():
        raise CheckFailed(f"error does not mention the missing UV map: {reply['error']}")
    if any(out.iterdir()):
        raise CheckFailed("files were written for a mesh with no UVs")
    return "clear UV error, nothing written"


# (name, function, seconds)
CHECKS: list[tuple[str, Callable[[Ctx], str], float]] = [
    ("object_create_listed", check_object_create_listed, CHECK_TIMEOUT),
    ("mesh_knife_project_keeps_outside", check_mesh_knife_project_keeps_outside, CHECK_TIMEOUT),
    ("mesh_knife_project_reports_no_cut", check_mesh_knife_project_reports_no_cut, CHECK_TIMEOUT),
    ("mesh_knife_project_uses_view_axis", check_mesh_knife_project_uses_view_axis, CHECK_TIMEOUT),
    ("mesh_loop_cut_adds_edges", check_mesh_loop_cut_adds_edges, CHECK_TIMEOUT),
    ("mesh_select_criteria_intersect", check_mesh_select_criteria_intersect, CHECK_TIMEOUT),
    ("mesh_edge_slide_moves_edge", check_mesh_edge_slide_moves_edge, CHECK_TIMEOUT),
    ("sculpt_mesh_filter_moves_vertices", check_sculpt_mesh_filter_moves_vertices, 90.0),
    ("sculpt_mask_by_topology_sets_mask", check_sculpt_mask_by_topology_sets_mask, 90.0),
    ("sculpt_face_set_create_makes_sets", check_sculpt_face_set_create_makes_sets, 90.0),
    ("sculpt_extract_mask_needs_a_mask", check_sculpt_extract_mask_needs_a_mask, CHECK_TIMEOUT),
    ("sculpt_failure_leaves_object_mode", check_sculpt_failure_leaves_object_mode, CHECK_TIMEOUT),
    ("render_screenshot_writes_file", check_render_screenshot_writes_file, 60.0),
    ("mode_restored_after_failure", check_mode_restored_after_failure, CHECK_TIMEOUT),
    ("render_image_writes_file", check_render_image_writes_file, 120.0),
    ("msfs_uv_layout_writes_file", check_msfs_uv_layout_writes_file, 60.0),
    ("msfs_paint_brush_after_setup", check_msfs_paint_brush_after_setup, 60.0),
    ("annotation_add_draws_or_says_why", check_annotation_add_draws_or_says_why, CHECK_TIMEOUT),
    ("ai_texture_passes_are_real", check_ai_texture_passes_are_real, 120.0),
    ("grease_pencil_markup_draws_pixels", check_grease_pencil_markup_draws_pixels, 60.0),
    ("undo_reverts", check_undo_reverts, CHECK_TIMEOUT),
    ("failed_call_adds_no_undo_step", check_failed_call_adds_no_undo_step, CHECK_TIMEOUT),
    ("execute_script_stdout", check_execute_script_stdout, CHECK_TIMEOUT),
    ("execute_script_refused_when_off", check_execute_script_refused_when_off, CHECK_TIMEOUT),
    ("reply_32mb_complete", check_reply_32mb_complete, CHECK_TIMEOUT),
    ("malformed_json_error_reply", check_malformed_json_error_reply, CHECK_TIMEOUT),
    ("client_vanishes_mid_reply", check_client_vanishes_mid_reply, CHECK_TIMEOUT),
    ("http_post_rejected", check_http_post_rejected, CHECK_TIMEOUT),
    ("unauthenticated_call_refused", check_unauthenticated_call_refused, CHECK_TIMEOUT),
    ("wrong_token_rejected", check_wrong_token_rejected, CHECK_TIMEOUT),
    ("old_client_told_to_update", check_old_client_told_to_update, CHECK_TIMEOUT),
    ("hello_timeout_closes", check_hello_timeout_closes, CHECK_TIMEOUT),
    ("copy_token_matches_running_server", check_copy_token_matches_running_server, CHECK_TIMEOUT),
    ("bake_pbr_writes_image", check_bake_pbr_writes_image, 120.0),
    ("bake_leaves_material_clean", check_bake_leaves_material_clean, 150.0),
    ("bake_tricks_leave_material_clean", check_bake_tricks_leave_material_clean, 180.0),
    ("bake_odd_materials", check_bake_odd_materials, 150.0),
    ("bake_id_map_restores_slots", check_bake_id_map_restores_slots, 150.0),
    ("bake_multires_writes_image", check_bake_multires_writes_image, 90.0),
    ("bake_without_uvs_errors", check_bake_without_uvs_errors, 60.0),
]


def classify_failure(exc: Exception, blender_alive: bool) -> tuple[str, str]:
    """Map an exception raised by a check to (outcome, reason)."""
    if not blender_alive:
        return "CRASH", f"Blender died during the check ({type(exc).__name__}: {exc})"
    if (isinstance(exc, ReplyTimeout) and exc.got == 0) or isinstance(exc, TimeoutError):
        return "HANG", f"{type(exc).__name__}: {exc}"
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
        except Exception as exc:  # e.g. a reply of unexpected shape: report, keep going
            outcome, reason = "FAIL", f"{type(exc).__name__}: {exc}"
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
    with log.open("ab") as build_log:
        build = subprocess.Popen(
            [blender, "-b", "--factory-startup", "--python", str(BOOT), "--",
             "--build-scene", "--scene", str(scene)],
            stdout=build_log, stderr=subprocess.STDOUT, start_new_session=True,
            env=blender_env(out_dir / "tmp"),
        )  # fmt: skip
        try:
            build.wait(timeout=STARTUP_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise StartupError(f"fixture scene build timed out, see {log}") from None
        finally:
            teardown(build)
    if build.returncode != 0 or not scene.exists():
        raise StartupError(f"could not build the fixture scene, see {log}")

    session = BlenderSession(blender, out_dir, scene)
    try:
        results = run_checks(session, checks, out_dir)
    finally:
        session.stop()
    return series, results


def run_checks(session, checks, out_dir: Path) -> dict[str, str]:
    results: dict[str, str] = {}
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
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--write-baseline", type=Path, metavar="FILE")
    parser.add_argument("--check-baseline", type=Path, metavar="FILE")
    args = parser.parse_args(argv)
    if args.write_baseline and args.check_baseline:
        parser.error("--write-baseline and --check-baseline are mutually exclusive")

    with sigterm_as_exit():
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
        if diff:
            print(DIFF_HINT, file=sys.stderr)
        return 1 if diff else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
