"""Blender-free tests for the add-on socket server, on real loopback sockets.

The module is imported under a stub ``bpy`` whose ``app.timers.register`` records the
tick callback. Nothing runs on a timer: each test calls ``_tick`` by hand.
"""

import importlib
import json
import socket
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ADDON = Path(__file__).resolve().parent.parent / "addon" / "blender_mcp_addon"
ROOT = "_socket_addon"
MIB = 1024 * 1024


class StubHandlers:
    """Stands in for CommandHandlers: ``big`` returns a large string, others echo."""

    def __init__(self):
        self.size = 0

    def handle(self, method, params):
        if method == "big":
            return "x" * self.size
        if method == "boom":
            raise ValueError("handler failed")
        return {"echo": method}


class CountingSock:
    """Wraps an accepted socket and records how each ``send`` went."""

    def __init__(self, sock):
        self._sock = sock
        self.calls = 0
        self.partial = 0

    def send(self, data):
        n = self._sock.send(data)
        self.calls += 1
        if n < len(data):
            self.partial += 1
        return n

    def __getattr__(self, name):
        return getattr(self._sock, name)


@pytest.fixture
def mod(monkeypatch):
    bpy = MagicMock()
    registered = []
    bpy.app.timers.register.side_effect = lambda fn, **kw: registered.append(fn)
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    for name in [m for m in sys.modules if m == ROOT or m.startswith(ROOT + ".")]:
        monkeypatch.delitem(sys.modules, name)
    package = types.ModuleType(ROOT)
    package.__path__ = [str(ADDON)]
    handlers = types.ModuleType(f"{ROOT}.handlers")
    handlers.CommandHandlers = StubHandlers
    monkeypatch.setitem(sys.modules, ROOT, package)
    monkeypatch.setitem(sys.modules, f"{ROOT}.handlers", handlers)
    module = importlib.import_module(f"{ROOT}.socket_server")
    module.registered = registered
    return module


@pytest.fixture
def server(mod):
    srv = mod.MCPSocketServer("127.0.0.1", 0)
    assert srv.start()
    srv.port = srv.socket.getsockname()[1]
    yield srv
    srv.stop()


def tick(srv, n=1):
    for _ in range(n):
        assert srv._tick() == 0.01


def connect(srv):
    sock = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
    sock.setblocking(False)
    return sock


def pump(srv, sock=None, until=None, seconds=10.0):
    """Tick until ``until()`` is true. Fails the test on timeout."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        tick(srv)
        if until():
            return
    pytest.fail("condition not reached while ticking")


def read_all(srv, sock, seconds=10.0):
    """Tick and read until EOF; return every byte received."""
    got = bytearray()
    state = {"eof": False}

    def step():
        try:
            data = sock.recv(1 << 20)
        except BlockingIOError:
            return False
        if not data:
            state["eof"] = True
        got.extend(data)
        return state["eof"]

    pump(srv, until=step, seconds=seconds)
    return bytes(got)


def read_line(srv, sock, seconds=10.0):
    got = bytearray()

    def step():
        try:
            got.extend(sock.recv(1 << 20))
        except BlockingIOError:
            pass
        return b"\n" in got

    pump(srv, until=step, seconds=seconds)
    return json.loads(bytes(got).split(b"\n", 1)[0])


def request(sock, method, req_id=1):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": {}}
    sock.sendall(json.dumps(msg).encode() + b"\n")


def test_ping_round_trip(server):
    sock = connect(server)
    request(sock, "ping")
    reply = read_line(server, sock)
    assert reply["id"] == 1 and reply["result"] == {"echo": "ping"}
    assert server.client_count == 1


def test_client_defaults_for_auth(mod):
    client = mod._Client(MagicMock())
    assert client.authed is False and client.deadline == 0.0
    assert client.closing is False and not client.rbuf and not client.wbuf


def test_reply_larger_than_socket_buffers_arrives_whole(server):
    size = 32 * MIB
    server.handlers.size = size
    sock = connect(server)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024)
    tick(server)  # accept
    (client,) = server.clients.values()
    # A small send buffer forces ``send`` to take a slice of the reply at a time.
    client.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    counter = CountingSock(client.sock)
    client.sock = counter
    request(sock, "big")
    tick(server)
    assert len(client.wbuf) > 0, "a 32 MiB reply must not leave in one tick"

    got = bytearray()
    ticks = 0
    while b"\n" not in got:
        tick(server)
        ticks += 1
        assert ticks < 200_000, "reply never completed"
        try:
            got.extend(sock.recv(256 * 1024))  # read slowly: 256 KiB per tick
        except BlockingIOError:
            pass
    line = bytes(got).split(b"\n", 1)[0]
    assert len(json.loads(line)["result"]) == size
    assert counter.partial > 100
    assert ticks > 10


def test_line_over_cap_gets_error_then_close(server, mod, monkeypatch):
    monkeypatch.setattr(mod, "MAX_LINE", 1024)
    sock = connect(server)
    sock.sendall(b"x" * 4096)  # no newline, already past the cap
    data = read_all(server, sock)
    reply = json.loads(data.split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_TOO_LARGE
    assert data.endswith(b"\n")
    sock.close()
    pump(server, until=lambda: server.client_count == 0)


def test_complete_line_over_cap_gets_error_then_close(server, mod, monkeypatch):
    monkeypatch.setattr(mod, "MAX_LINE", 1024)
    sock = connect(server)
    sock.sendall(b'{"method": "' + b"x" * 4096 + b'"}\n')
    reply = json.loads(read_all(server, sock).split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_TOO_LARGE


def test_ninth_client_gets_error_then_close(server, mod):
    socks = []
    for _ in range(mod.MAX_CLIENTS):
        socks.append(connect(server))
        tick(server)
    assert server.client_count == mod.MAX_CLIENTS
    ninth = connect(server)
    data = read_all(server, ninth)
    reply = json.loads(data.split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_TOO_MANY
    ninth.close()
    pump(server, until=lambda: server.client_count == mod.MAX_CLIENTS)
    # The first eight are untouched.
    request(socks[0], "ping")
    assert read_line(server, socks[0])["result"] == {"echo": "ping"}
    assert server.client_count == mod.MAX_CLIENTS


@pytest.mark.parametrize(
    "payload",
    [b"\xff\xfe not utf8\n", b"[1, 2, 3]\n", b"{this is not json\n"],
    ids=["non_utf8", "non_object", "malformed"],
)
def test_bad_line_gets_parse_error_then_close(server, mod, payload):
    sock = connect(server)
    sock.sendall(payload)
    reply = json.loads(read_all(server, sock).split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_PARSE
    assert reply["id"] is None
    # A fresh connection still works.
    fresh = connect(server)
    request(fresh, "ping")
    assert read_line(server, fresh)["result"] == {"echo": "ping"}


def test_non_utf8_line_gets_parse_error_then_close(server, mod):
    sock = connect(server)
    sock.sendall(b"\xff\xfe\n")
    reply = json.loads(read_all(server, sock).split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_PARSE


def test_non_object_json_gets_parse_error_then_close(server, mod):
    sock = connect(server)
    sock.sendall(b'"just a string"\n')
    reply = json.loads(read_all(server, sock).split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_PARSE


def test_malformed_json_gets_parse_error_then_close(server, mod):
    sock = connect(server)
    sock.sendall(b"{nope\n")
    data = read_all(server, sock)
    assert json.loads(data)["error"]["code"] == mod.wire.E_PARSE
    sock.close()
    pump(server, until=lambda: server.client_count == 0)


def test_handler_error_keeps_the_connection(server):
    sock = connect(server)
    request(sock, "boom", req_id=7)
    reply = read_line(server, sock)
    assert reply["id"] == 7 and reply["error"]["code"] == -32603
    request(sock, "ping", req_id=8)
    assert read_line(server, sock)["id"] == 8


def test_reply_over_wbuf_cap_becomes_error_reply(server, mod, monkeypatch):
    monkeypatch.setattr(mod, "MAX_WBUF", 100_000)
    server.handlers.size = 200_000
    sock = connect(server)
    request(sock, "big", req_id=5)
    reply = read_line(server, sock)
    assert reply["id"] == 5
    assert reply["error"]["code"] == mod.wire.E_REPLY_TOO_LARGE
    # Not fatal: the same connection keeps working.
    request(sock, "ping", req_id=6)
    assert read_line(server, sock)["result"] == {"echo": "ping"}


def test_vanished_client_is_dropped_without_raising(server):
    server.handlers.size = 8 * MIB
    gone = connect(server)
    tick(server)
    (client,) = server.clients.values()
    client.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    request(gone, "big")
    tick(server, 3)
    assert len(client.wbuf) > 0
    gone.close()
    pump(server, until=lambda: server.client_count == 0)
    assert not client.wbuf
    other = connect(server)
    request(other, "ping")
    assert read_line(server, other)["result"] == {"echo": "ping"}


def test_stop_closes_everything(server):
    sock = connect(server)
    tick(server)
    server.stop()
    assert server.client_count == 0 and not server.is_running
    sock.setblocking(True)
    sock.settimeout(5)
    assert sock.recv(10) == b""


def test_start_returns_false_when_port_is_taken(mod, server):
    other = mod.MCPSocketServer("127.0.0.1", server.port)
    assert other.start() is False


def test_closing_client_that_never_reads_is_dropped_after_the_grace(server, mod, monkeypatch):
    monkeypatch.setattr(mod, "CLOSE_GRACE", 0.05)
    sock = connect(server)
    sock.sendall(b"{nope\n")
    pump(server, until=lambda: server.client_count == 0)
    sock.close()
