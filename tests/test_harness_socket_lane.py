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
