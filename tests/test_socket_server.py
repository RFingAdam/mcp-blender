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


@pytest.fixture(autouse=True)
def _own_config_dir(monkeypatch, tmp_path):
    """Every test gets its own token file and no ambient MESHWIRE_TOKEN."""
    monkeypatch.delenv("MESHWIRE_TOKEN", raising=False)
    monkeypatch.setenv("MESHWIRE_CONFIG_DIR", str(tmp_path / "meshwire"))


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


_OPEN: list = []


@pytest.fixture(autouse=True)
def _close_peers():
    """Close every peer socket a test opened, so -W error::ResourceWarning passes."""
    yield
    while _OPEN:
        _OPEN.pop().close()


def connect(srv, auth=True):
    """Open a client socket. By default it also says hello and reads the good reply."""
    sock = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
    sock.setblocking(False)
    _OPEN.append(sock)
    if auth:
        sock.sendall(hello_line(srv))
        reply = read_line(srv, sock)
        assert reply["result"]["protocol"] == 1, reply
    return sock


def hello_line(srv, token=None, protocol=1, req_id=1):
    params = {"token": srv._token if token is None else token, "protocol": protocol}
    msg = {"jsonrpc": "2.0", "method": "hello", "params": params, "id": req_id}
    return json.dumps(msg).encode() + b"\n"


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
        except ConnectionResetError:
            # The server closed a socket that still held unread bytes. That is a close.
            data = b""
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
    ninth = connect(server, auth=False)
    data = read_all(server, ninth)
    reply = json.loads(data.split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_TOO_MANY
    ninth.close()
    pump(server, until=lambda: server.client_count == mod.MAX_CLIENTS)
    # The first eight are untouched.
    request(socks[0], "ping")
    assert read_line(server, socks[0])["result"] == {"echo": "ping"}
    assert server.client_count == mod.MAX_CLIENTS


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
    reply = json.loads(data)
    assert reply["error"]["code"] == mod.wire.E_PARSE and reply["id"] is None
    sock.close()
    pump(server, until=lambda: server.client_count == 0)
    fresh = connect(server)
    request(fresh, "ping")
    assert read_line(server, fresh)["result"] == {"echo": "ping"}


def test_deeply_nested_json_gets_parse_error_without_a_traceback(server, mod, capsys):
    sock = connect(server)
    sock.sendall(b"[" * 200_000 + b"\n")
    reply = json.loads(read_all(server, sock).split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_PARSE
    out = capsys.readouterr()
    assert "Error processing client" not in out.out and "Traceback" not in out.err


def test_line_of_exactly_max_line_is_accepted_and_one_more_is_not(server, mod, monkeypatch):
    monkeypatch.setattr(mod, "MAX_LINE", 200)
    body = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping", "pad": ""})
    pad = "x" * (200 - len(body))
    exact = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping", "pad": pad}).encode()
    assert len(exact) == 200
    ok = connect(server)
    ok.sendall(exact)  # the newline arrives in a later recv
    tick(server, 3)
    ok.sendall(b"\n")
    assert read_line(server, ok)["id"] == 3
    over = connect(server)
    over.sendall(exact[:-1] + b"xx}\n")  # 201 bytes before the newline
    reply = json.loads(read_all(server, over).split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_TOO_LARGE


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


def test_vanished_client_is_dropped_without_raising(server, capsys):
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
    out = capsys.readouterr()
    assert "Error processing client" not in out.out and "tick error" not in out.out
    assert "Traceback" not in out.err


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


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def with_clock(srv):
    clock = Clock()
    srv._now = clock
    return clock


class BlockedSock:
    """An accepted socket whose send never takes a byte."""

    def __init__(self, sock):
        self._sock = sock

    def send(self, data):
        raise BlockingIOError

    def __getattr__(self, name):
        return getattr(self._sock, name)


def test_closing_client_that_never_reads_is_dropped_after_grace(server, mod):
    clock = with_clock(server)
    sock = connect(server)
    tick(server)
    (client,) = server.clients.values()
    client.sock = BlockedSock(client.sock)
    sock.sendall(b"{nope\n")  # an error close whose reply can never leave
    tick(server, 3)
    assert client.closing and len(client.wbuf) > 0
    clock.t += mod.CLOSE_GRACE - 0.1
    tick(server)
    assert server.client_count == 1
    clock.t += 0.2
    tick(server)
    assert server.client_count == 0


def test_stalled_write_buffer_is_dropped(server, mod):
    clock = with_clock(server)
    server.handlers.size = 8 * MIB
    sock = connect(server)
    tick(server)
    (client,) = server.clients.values()
    client.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    request(sock, "big")
    tick(server, 3)
    assert client.wbuf and not client.closing
    clock.t += mod.WRITE_STALL - 1
    tick(server)
    assert server.client_count == 1
    clock.t += 2
    tick(server)
    assert server.client_count == 0
    sock.close()


def test_closing_clients_count_toward_the_cap(server, mod):
    with_clock(server)
    socks = []
    for _ in range(mod.MAX_CLIENTS - 1):
        socks.append(connect(server))
        tick(server)
    bad = connect(server)
    tick(server)
    bad.sendall(b"{nope\n")
    tick(server, 3)  # it is closing now, and still holds a slot
    assert server.client_count == mod.MAX_CLIENTS
    late = connect(server, auth=False)
    reply = json.loads(read_all(server, late).split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_TOO_MANY


def test_refusals_beyond_max_closing_close_without_reply(server, mod, monkeypatch):
    with_clock(server)
    monkeypatch.setattr(mod, "MAX_CLIENTS", 1)
    monkeypatch.setattr(mod, "MAX_CLOSING", 2)
    keeper = connect(server)
    tick(server)
    refused = []
    for _ in range(2):  # these two get a reply and fill the closing allowance
        refused.append(connect(server, auth=False))
        tick(server)
    assert sum(c.closing for c in server.clients.values()) == 2
    extra = connect(server, auth=False)
    tick(server)
    extra.setblocking(True)
    extra.settimeout(5)
    assert extra.recv(100) == b""  # closed with no reply
    assert server.client_count == 3
    keeper.close()


def test_half_closed_client_still_gets_its_reply(server):
    sock = connect(server)
    request(sock, "ping", req_id=4)
    sock.sendall(b'{"id": 5, "method": "ping"')  # a trailing partial line is dropped
    sock.shutdown(socket.SHUT_WR)
    data = read_all(server, sock)
    lines = data.split(b"\n")
    assert [json.loads(x)["id"] for x in lines if x] == [4]
    pump(server, until=lambda: server.client_count == 0)


def test_half_closed_client_with_pipelined_requests_gets_every_reply(server):
    sock = connect(server)
    for i in range(1, 6):
        request(sock, "ping", req_id=i)
    sock.shutdown(socket.SHUT_WR)
    data = read_all(server, sock)
    assert [json.loads(x)["id"] for x in data.split(b"\n") if x] == [1, 2, 3, 4, 5]


def test_never_reading_client_keeps_wbuf_within_the_cap(server, mod, monkeypatch):
    monkeypatch.setattr(mod, "MAX_WBUF", 10_000)
    sock = connect(server)
    tick(server)
    (client,) = server.clients.values()
    client.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    sock.settimeout(5)
    sock.setblocking(False)
    biggest = 0
    for _ in range(300):
        try:
            sock.send(b"{}\n" * 2000)
        except BlockingIOError:
            pass
        tick(server)
        biggest = max(biggest, len(client.wbuf))
    assert 0 < biggest <= 10_000
    assert client.dead is False or server.client_count == 0


def test_trickle_reader_keeps_wbuf_within_the_cap(server, mod, monkeypatch):
    monkeypatch.setattr(mod, "MAX_WBUF", 10_000)
    sock = connect(server)
    tick(server)
    (client,) = server.clients.values()
    client.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    biggest = 0
    for _ in range(300):
        try:
            sock.send(b"{}\n" * 500)
        except BlockingIOError:
            pass
        tick(server)
        biggest = max(biggest, len(client.wbuf))
        try:
            sock.recv(100)  # a trickle
        except BlockingIOError:
            pass
    assert 0 < biggest <= 10_000


def test_oversized_reply_and_error_that_cannot_fit_hang_up(server, mod, monkeypatch):
    server.handlers.size = 1000
    sock = connect(server)
    monkeypatch.setattr(mod, "MAX_WBUF", 50)  # smaller than any error reply
    request(sock, "big")
    assert read_all(server, sock) == b""
    assert len(next(iter(server.clients.values()), mod._Client(None)).wbuf) <= 50


def test_requests_pipelined_behind_a_large_reply_are_answered_in_order(server):
    server.handlers.size = 3 * MIB
    sock = connect(server)
    tick(server)
    (client,) = server.clients.values()
    client.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    request(sock, "big", req_id=1)
    for i in (2, 3, 4):
        request(sock, "ping", req_id=i)
    got = bytearray()
    ids = []
    for _ in range(100_000):
        tick(server)
        try:
            got.extend(sock.recv(1 << 20))
        except BlockingIOError:
            pass
        while b"\n" in got:
            line, _, rest = bytes(got).partition(b"\n")
            got = bytearray(rest)
            ids.append(json.loads(line)["id"])
        if len(ids) == 4:
            break
    assert ids == [1, 2, 3, 4]


def slow_handler(srv, clock, seconds):
    orig = srv.handlers.handle

    def slow(method, params):
        clock.t += seconds
        return orig(method, params)

    srv.handlers.handle = slow


def small_sndbuf(srv):
    tick(srv)
    (client,) = srv.clients.values()
    client.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    return client


def test_half_closed_slow_handler_big_reply_arrives_whole(server):
    clock = with_clock(server)
    server.handlers.size = 8 * MIB
    slow_handler(server, clock, 10)
    sock = connect(server)
    small_sndbuf(server)
    request(sock, "big")
    sock.shutdown(socket.SHUT_WR)
    data = read_all(server, sock)
    assert data.endswith(b"\n") and len(json.loads(data)["result"]) == 8 * MIB


def test_half_closed_pipelined_big_then_small_arrive_in_order(server):
    server.handlers.size = 2 * MIB
    sock = connect(server)
    small_sndbuf(server)
    request(sock, "big", req_id=1)
    request(sock, "ping", req_id=2)
    sock.shutdown(socket.SHUT_WR)
    data = read_all(server, sock)
    assert [json.loads(x)["id"] for x in data.split(b"\n") if x] == [1, 2]


def test_half_closed_client_that_never_reads_is_closed_after_write_stall(server, mod):
    clock = with_clock(server)
    server.handlers.size = 8 * MIB
    sock = connect(server)
    small_sndbuf(server)
    request(sock, "big")
    sock.shutdown(socket.SHUT_WR)
    tick(server, 3)
    assert server.client_count == 1
    clock.t += mod.CLOSE_GRACE + 5  # the error-close grace does not apply to it
    tick(server)
    assert server.client_count == 1
    clock.t += mod.WRITE_STALL
    tick(server)
    assert server.client_count == 0


# --- token and hello -------------------------------------------------------------


def only_client(srv):
    (client,) = srv.clients.values()
    return client


def test_start_creates_the_token(server, tmp_path):
    assert (tmp_path / "meshwire" / "token").read_text().strip() == server._token


def test_good_hello_reply_and_auth(server):
    sock = connect(server, auth=False)
    sock.sendall(hello_line(server, req_id=7))
    reply = read_line(server, sock)
    assert reply["id"] == 7
    assert reply["result"]["protocol"] == 1
    assert reply["result"]["port"] == server.port
    assert isinstance(reply["result"]["addon"], str)
    assert only_client(server).authed is True


def test_request_before_hello_is_refused(server, mod):
    sock = connect(server, auth=False)
    request(sock, "ping", req_id=5)
    data = read_all(server, sock)
    reply = json.loads(data.split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_PROTOCOL
    assert reply["id"] == 5
    assert data.count(b"\n") == 1


def test_http_request_closed_without_reply(server):
    sock = connect(server, auth=False)
    body = b'{"jsonrpc":"2.0","method":"ping","id":1}'
    sock.sendall(b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 39\r\n\r\n" + body + b"\n")
    assert read_all(server, sock) == b""
    pump(server, until=lambda: server.client_count == 0)


def test_garbage_first_line_closed_without_reply(server):
    sock = connect(server, auth=False)
    sock.sendall(b"[1, 2]\n")
    assert read_all(server, sock) == b""


def test_wrong_token_rejected_once_then_closed(server, mod):
    sock = connect(server, auth=False)
    sock.sendall(hello_line(server, token="nope", req_id=9) + b'{"method":"ping","id":2}\n')
    data = read_all(server, sock)
    lines = data.split(b"\n")
    assert len(lines) == 2 and lines[1] == b""  # one reply, then EOF
    reply = json.loads(lines[0])
    assert reply["error"]["code"] == mod.wire.E_UNAUTHORIZED
    assert reply["id"] == 9
    assert "nope" not in lines[0].decode() and server._token not in lines[0].decode()
    pump(server, until=lambda: server.client_count == 0)


def test_missing_token_is_unauthorized(server, mod):
    sock = connect(server, auth=False)
    msg = {"jsonrpc": "2.0", "method": "hello", "params": {"protocol": 1}, "id": 1}
    sock.sendall(json.dumps(msg).encode() + b"\n")
    reply = json.loads(read_all(server, sock).split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_UNAUTHORIZED


def test_old_client_told_to_update(server, mod):
    sock = connect(server, auth=False)
    request(sock, "scene_info", req_id=3)
    data = read_all(server, sock)
    reply = json.loads(data.split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_PROTOCOL
    assert reply["id"] == 3
    assert "needs a newer Meshwire server" in reply["error"]["message"]
    assert "uvx meshwire@latest" in reply["error"]["message"]


def test_protocol_mismatch_names_both_versions(server, mod):
    sock = connect(server, auth=False)
    sock.sendall(hello_line(server, protocol=2))
    reply = json.loads(read_all(server, sock).split(b"\n", 1)[0])
    assert reply["error"]["code"] == mod.wire.E_PROTOCOL
    message = reply["error"]["message"]
    assert "2" in message and "1" in message
    assert "add-on" in message  # the client is newer, so the add-on is the side to update
    assert only_client_gone(server)


def only_client_gone(srv):
    pump(srv, until=lambda: srv.client_count == 0)
    return True


def test_hello_over_4k_closed(server, mod):
    sock = connect(server, auth=False)
    pad = "x" * (mod.wire.HELLO_MAX + 10)
    msg = {"jsonrpc": "2.0", "method": "hello", "params": {"token": pad, "protocol": 1}, "id": 1}
    sock.sendall(json.dumps(msg).encode() + b"\n")
    assert read_all(server, sock) == b""


def test_4k_without_newline_closed(server, mod):
    sock = connect(server, auth=False)
    sock.sendall(b"x" * (mod.wire.HELLO_MAX + 1))
    assert read_all(server, sock) == b""


def test_hello_of_exactly_the_limit_is_accepted(server, mod):
    sock = connect(server, auth=False)
    base = hello_line(server)
    pad = mod.wire.HELLO_MAX - (len(base) - 1)
    msg = json.loads(base)
    msg["params"]["client"] = "c" * (pad - len(', "client": ""'))
    line = json.dumps(msg).encode()
    assert len(line) == mod.wire.HELLO_MAX
    sock.sendall(line + b"\n")
    assert read_line(server, sock)["result"]["protocol"] == 1


def test_hello_after_deadline_closed(server, mod):
    clock = with_clock(server)
    sock = connect(server, auth=False)
    tick(server)  # accept at t0
    clock.t += mod.wire.HELLO_SECONDS + 0.01
    sock.sendall(hello_line(server))
    assert read_all(server, sock) == b""


def test_hello_just_before_deadline_is_accepted(server, mod):
    clock = with_clock(server)
    sock = connect(server, auth=False)
    tick(server)
    clock.t += mod.wire.HELLO_SECONDS - 0.01
    sock.sendall(hello_line(server))
    assert read_line(server, sock)["result"]["protocol"] == 1


def test_silent_client_closed_at_deadline(server, mod):
    clock = with_clock(server)
    sock = connect(server, auth=False)
    tick(server)
    clock.t += mod.wire.HELLO_SECONDS + 0.01
    assert read_all(server, sock) == b""


def test_dripping_client_closed_at_deadline(server, mod):
    clock = with_clock(server)
    sock = connect(server, auth=False)
    tick(server)
    for _ in range(4):
        sock.sendall(b"{")
        clock.t += 0.6
        tick(server)
    assert read_all(server, sock) == b""


def test_half_closed_before_hello_is_closed(server, mod):
    clock = with_clock(server)
    sock = connect(server, auth=False)
    sock.sendall(b'{"jsonrpc":"2.0","method":"hello"')  # no newline
    sock.shutdown(socket.SHUT_WR)
    tick(server, 3)
    clock.t += mod.wire.HELLO_SECONDS + 0.01
    assert read_all(server, sock) == b""


def test_wrong_token_client_that_never_reads_leaves_by_the_deadline(server, mod):
    clock = with_clock(server)
    sock = connect(server, auth=False)
    tick(server)
    sock.sendall(hello_line(server, token="bad"))
    tick(server, 3)
    clock.t += mod.wire.HELLO_SECONDS + 0.01
    tick(server, 3)
    assert server.client_count == 0
    assert sock  # never read a byte


def test_deadline_applies_only_before_hello(server, mod):
    """A handler that runs for 10 s must not cost the client its connection."""
    clock = with_clock(server)
    sock = connect(server)
    clock.t += 10.0
    tick(server, 3)
    assert server.client_count == 1
    request(sock, "ping", req_id=4)
    assert read_line(server, sock)["id"] == 4
    clock.t += 3600.0
    tick(server, 3)
    request(sock, "ping", req_id=5)
    assert read_line(server, sock)["id"] == 5


def test_deadline_counts_from_accept_not_from_connect(server, mod):
    clock = with_clock(server)
    sock = connect(server, auth=False)
    clock.t += 5.0  # the client connected but the server had not run a tick yet
    sock.sendall(hello_line(server))
    tick(server)  # accept stamps t0 + 5; the hello arrives inside its own 2 s
    assert read_line(server, sock)["result"]["protocol"] == 1
