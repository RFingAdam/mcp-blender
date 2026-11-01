"""Unit tests for the socket lane's Blender-free parts."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from tests.harness import socket_lane as lane


def test_encode_request_is_one_newline_terminated_json_line():
    raw = lane.encode_request(7, "ping", {"a": "x\ny"})
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1
    assert json.loads(raw) == {"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {"a": "x\ny"}}


def test_series_of_version_output():
    assert lane.series_of("Blender 4.5.15 LTS\n\tbuild date: x") == "4.5"
    assert lane.series_of("Blender 5.2.3\n") == "5.2"
    with pytest.raises(ValueError):
        lane.series_of("not blender")


def pair():
    a, b = socket.socketpair()
    return a, b


def test_read_reply_reassembles_split_chunks():
    a, b = pair()
    body = json.dumps({"id": 1, "result": "z" * 300_000}).encode()

    def feed():
        for i in range(0, len(body), 70_000):
            b.sendall(body[i : i + 70_000])
            time.sleep(0.01)
        b.sendall(b"\n")

    threading.Thread(target=feed).start()
    reply = lane.read_reply(a, lane.Budget(5))
    assert reply["result"] == "z" * 300_000


def test_read_reply_times_out_with_no_bytes():
    a, _b = pair()
    with pytest.raises(lane.ReplyTimeout) as exc:
        lane.read_reply(a, lane.Budget(0.2))
    assert exc.value.got == 0


def test_read_reply_times_out_with_partial_reply():
    a, b = pair()
    b.sendall(b'{"id": 1, "res')
    with pytest.raises(lane.ReplyTimeout) as exc:
        lane.read_reply(a, lane.Budget(0.2))
    assert exc.value.got == 14


def test_read_reply_reports_close_before_newline():
    a, b = pair()
    b.sendall(b'{"id": 1')
    b.close()
    with pytest.raises(lane.ConnectionClosed) as exc:
        lane.read_reply(a, lane.Budget(2))
    assert exc.value.got == 8


def test_read_reply_rejects_non_json_line():
    a, b = pair()
    b.sendall(b"garbage\n")
    with pytest.raises(lane.BadReply):
        lane.read_reply(a, lane.Budget(2))


def test_budget_is_shared_across_reads():
    budget = lane.Budget(0.3)
    time.sleep(0.35)
    a, _b = pair()
    with pytest.raises(lane.ReplyTimeout):
        lane.read_reply(a, budget)


def test_merge_baseline_keeps_other_series():
    old = {"4.5": {"a": "PASS"}, "5.2": {"a": "FAIL", "b": "PASS"}}
    merged = lane.merge_baseline(old, "5.2", {"a": "PASS", "c": "CRASH"})
    assert merged == {"4.5": {"a": "PASS"}, "5.2": {"a": "PASS", "c": "CRASH"}}
    assert old["5.2"] == {"a": "FAIL", "b": "PASS"}


def test_diff_baseline_checks_only_the_ran_series():
    base = {"4.5": {"a": "PASS"}, "5.2": {"a": "FAIL"}}
    assert lane.diff_baseline(base, "4.5", {"a": "PASS"}) == []
    assert lane.diff_baseline(base, "5.2", {"a": "PASS"}) == ["improved: a FAIL -> PASS"]
    assert lane.diff_baseline(base, "4.5", {"a": "HANG"}) == ["worse: a PASS -> HANG"]
    assert lane.diff_baseline(base, "4.5", {"a": "FAIL"}) == ["worse: a PASS -> FAIL"]
    assert lane.diff_baseline(base, "6.0", {"a": "PASS"}) == ["added: a PASS"]


def test_free_port_is_bindable():
    port = lane.free_port()
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


GROUP = textwrap.dedent(
    """\
    import subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    open(sys.argv[1], "w").write(str(child.pid))
    time.sleep(60)
    """
)


def test_teardown_kills_whole_process_group(tmp_path):
    pidfile = tmp_path / "child.pid"
    proc = subprocess.Popen([sys.executable, "-c", GROUP, str(pidfile)], start_new_session=True)
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text():
            break
        time.sleep(0.05)
    child = int(pidfile.read_text())
    lane.teardown(proc, grace=1.0)
    assert proc.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(proc.pid, 0)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


def test_teardown_escalates_past_ignored_sigterm(tmp_path):
    code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    proc = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    time.sleep(0.3)
    lane.teardown(proc, grace=0.3)
    assert proc.poll() is not None


def test_teardown_of_already_dead_process_is_a_no_op():
    proc = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    proc.wait()
    lane.teardown(proc, grace=0.2)


# --- fix round 1 ---------------------------------------------------------------


class FakeConn:
    def __init__(self, replies):
        self.replies = replies
        self.sock = None
        self.budget = lane.Budget(5)

    def call(self, method, params=None):
        reply = self.replies[method]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def exec(self, code):
        return self.call("harness_exec", {"code": code})

    def close(self):
        pass


class FakeSession:
    def __init__(self, conn, alive=True):
        self.conn = conn
        self._alive = alive
        self.port = 1
        self.stopped = False

    def ensure_ready(self):
        return False

    def alive(self):
        return self._alive

    def alive_after_close(self, grace=5.0):
        return self._alive

    def connect(self, budget):
        return self.conn

    def stop(self):
        self.stopped = True


def test_classify_failure_crash_hang_and_fail():
    assert lane.classify_failure(lane.ReplyTimeout(0), False)[0] == "CRASH"
    assert lane.classify_failure(lane.ConnectionClosed(0), False)[0] == "CRASH"
    assert lane.classify_failure(lane.ReplyTimeout(0), True)[0] == "HANG"
    assert lane.classify_failure(lane.ReplyTimeout(10), True)[0] == "FAIL"
    assert lane.classify_failure(lane.CheckFailed("x"), True)[0] == "FAIL"
    assert lane.classify_failure(socket.timeout("connect"), True)[0] == "HANG"


def test_unexpected_reply_shape_is_a_fail_and_other_checks_still_run(tmp_path):
    conn = FakeConn({"harness_reset": {}, "ping": {"pong": True}})

    def bad(ctx):
        return ctx.conn.call("ping")["no_such_key"]

    def good(ctx):
        return "fine"

    session = FakeSession(conn)
    results = lane.run_checks(
        session, [("bad", bad, 5), ("good", good, 5), ("bad2", bad, 5)], tmp_path
    )
    assert results == {"bad": "FAIL", "good": "PASS", "bad2": "FAIL"}


def test_run_check_does_not_swallow_keyboard_interrupt(tmp_path):
    def interrupted(ctx):
        raise KeyboardInterrupt

    session = FakeSession(FakeConn({"harness_reset": {}}))
    with pytest.raises(KeyboardInterrupt):
        lane.run_check(session, "x", interrupted, 5, tmp_path)


def test_dead_blender_after_check_is_crash(tmp_path):
    session = FakeSession(FakeConn({"harness_reset": {}}), alive=False)
    outcome, _ = lane.run_check(session, "x", lambda ctx: "ok", 5, tmp_path)
    assert outcome == "CRASH"


class FakeProc:
    def __init__(self, returncode):
        self.returncode = returncode
        self.pid = 0

    def poll(self):
        return self.returncode


class RetrySession(lane.BlenderSession):
    """Spawns fake processes: the first exits with the bind-failure code."""

    def __init__(self, tmp_path, exit_codes):
        super().__init__("blender", tmp_path, tmp_path / "s.blend")
        self.exit_codes = list(exit_codes)
        self.ports = []
        self.stopped = 0

    def _spawn(self):
        self.ports.append(self.port)
        self.proc = FakeProc(self.exit_codes.pop(0))

    def healthy(self):
        return self.proc.returncode is None

    def stop(self):
        self.stopped += 1


def test_start_retries_with_new_port_on_bind_failure(tmp_path):
    s = RetrySession(tmp_path, [lane.BIND_FAILED_EXIT, lane.BIND_FAILED_EXIT, None])
    s.start()
    assert len(s.ports) == 3 and s.alive()


def test_start_gives_up_after_three_bind_failures(tmp_path):
    s = RetrySession(tmp_path, [lane.BIND_FAILED_EXIT] * 3)
    with pytest.raises(lane.StartupError):
        s.start()
    assert len(s.ports) == 3


def test_start_does_not_retry_other_exit_codes(tmp_path):
    s = RetrySession(tmp_path, [1, None])
    with pytest.raises(lane.StartupError):
        s.start()
    assert len(s.ports) == 1


def test_png_width_reads_ihdr():
    import struct

    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 64, 32)
    assert lane.png_size(png + b"\0" * 20) == (64, 32)
    with pytest.raises(ValueError):
        lane.png_size(b"nope")


def test_zombie_only_group_counts_as_gone():
    proc = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    for _ in range(100):
        time.sleep(0.05)
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            break
        if lane._group_gone(proc.pid):
            break
    try:
        os.killpg(proc.pid, 0)  # the unreaped zombie is still visible to killpg
    except ProcessLookupError:
        pytest.skip("zombie already reaped")
    assert lane._group_gone(proc.pid)
    proc.wait()


def test_sigterm_handler_raises_system_exit():
    import signal

    before = signal.getsignal(signal.SIGTERM)
    with lane.sigterm_as_exit():
        with pytest.raises(SystemExit):
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(1)
    assert signal.getsignal(signal.SIGTERM) == before
