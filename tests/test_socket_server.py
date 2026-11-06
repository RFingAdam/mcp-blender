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
        self.calls = []

    def handle(self, method, params):
        self.calls.append(method)
        if method == "big":
            return "x" * self.size
        if method == "boom":
            raise ValueError("handler failed")
        return {"echo": method}


class Throttled:
    """Stands in for an accepted socket: ``send`` takes at most ``limit`` bytes a call.

    A limit of 0 means nothing fits, as with a peer that never reads. This does not lean
    on the kernel's buffer sizes, which differ between Linux, macOS and Windows. Set
    ``limit`` at any time.
    """

    def __init__(self, sock, limit):
        self._sock = sock
        self.limit = limit

    def send(self, data):
        if self.limit <= 0:
            raise BlockingIOError
        return self._sock.send(data[: self.limit])

    def __getattr__(self, name):
        return getattr(self._sock, name)


class Budgeted:
    """Stands in for an accepted socket with a byte budget the test refills.

    ``send`` takes bytes until the budget is spent, then raises BlockingIOError, as a
    socket whose peer has stopped reading does. How much the real kernel would buffer
    cannot change what a test sees. The bytes taken go on to the real socket.
    """

    def __init__(self, sock, budget=0):
        self._sock = sock
        self.budget = budget

    def send(self, data):
        if self.budget <= 0:
            raise BlockingIOError
        sent = self._sock.send(data[: self.budget])
        self.budget -= sent
        return sent

    def __getattr__(self, name):
        return getattr(self._sock, name)


class Chunked:
    """Stands in for an accepted socket that delivers ``total`` bytes, at most ``per_call`` a recv.

    It records the size each ``recv`` asked for. Then how the kernel splits or delays
    delivery cannot change what a test sees. Everything else goes to the real socket.
    """

    def __init__(self, sock, total, per_call=1 << 20):
        self._sock = sock
        self.left = total
        self.per_call = per_call
        self.wanted = []

    @property
    def calls(self):
        return len(self.wanted)

    def recv(self, n):
        self.wanted.append(n)
        if self.left <= 0:
            raise BlockingIOError
        take = min(n, self.left, self.per_call)
        self.left -= take
        return b"x" * take

    def __getattr__(self, name):
        return getattr(self._sock, name)


def budget(client, amount=0):
    client.sock = Budgeted(client.sock, amount)
    return client.sock


def throttle(client, limit):
    client.sock = Throttled(client.sock, limit)
    return client.sock


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


def free_port():
    """A port the OS just handed out, so no test touches the real range 9876 to 9885."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def server(mod):
    srv = mod.MCPSocketServer("127.0.0.1", free_port())
    assert srv.start()
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
    """Open a client socket. By default it also runs the whole handshake."""
    sock = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
    sock.setblocking(False)
    _OPEN.append(sock)
    if auth:
        handshake(srv, sock)
    return sock


def jline(obj):
    return json.dumps(obj).encode() + b"\n"


def hello_line(nonce=None, protocol=1, req_id=1, **params):
    body = {"protocol": protocol, "client": "test", "nonce": nonce or WIRE.new_nonce()}
    body.update(params)
    return jline({"jsonrpc": "2.0", "method": "hello", "params": body, "id": req_id})


def proof_line(value, req_id=2, method="hello_proof"):
    return jline({"jsonrpc": "2.0", "method": method, "params": {"proof": value}, "id": req_id})


class _Wire:
    """The add-on's wire module, loaded without Blender."""

    def __getattr__(self, name):
        return getattr(sys.modules[f"{ROOT}.wire"], name)


WIRE = _Wire()


def handshake(srv, sock, token=None, nonce=None):
    """Run hello and hello_proof as a client holding the token. Returns the hello result."""
    token = srv.token if token is None else token
    nc = nonce or WIRE.new_nonce()
    sock.sendall(hello_line(nc))
    result = read_line(srv, sock)["result"]
    assert result["protocol"] == 1, result
    assert result["proof"] == WIRE.proof(
        token, WIRE.ADDON_LABEL, nc, result["nonce"], result["seen"]
    )
    sock.sendall(proof_line(WIRE.proof(token, WIRE.CLIENT_LABEL, result["nonce"], nc)))
    assert read_line(srv, sock)["result"] == {"ok": True}
    return result


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
    # The socket takes 128 KiB a tick, whatever the platform's buffers would hold.
    gate = Budgeted(client.sock, 128 * 1024)
    counter = CountingSock(gate)
    client.sock = counter
    request(sock, "big")
    tick(server)
    assert len(client.wbuf) > 0, "a 32 MiB reply must not leave in one tick"

    got = bytearray()
    ticks = 0
    while b"\n" not in got:
        gate.budget = 128 * 1024
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
    gate = budget(client, 4096)
    request(gone, "big")
    pump(server, until=lambda: len(client.wbuf) > 0)
    gone.close()
    gate.budget = 1 << 40  # the socket takes bytes again, so the dead peer shows up as an error
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


def test_start_raises_when_port_is_taken(mod, server):
    other = mod.MCPSocketServer("127.0.0.1", server.port)
    with pytest.raises(mod.BindError):
        other.start()


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def with_clock(srv):
    clock = Clock()
    srv._now = clock
    return clock


def test_closing_client_that_never_reads_is_dropped_after_grace(server, mod):
    clock = with_clock(server)
    sock = connect(server)
    tick(server)
    (client,) = server.clients.values()
    throttle(client, 0)
    sock.sendall(b"{nope\n")  # an error close whose reply can never leave
    pump(server, until=lambda: client.closing and len(client.wbuf) > 0)
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
    throttle(client, 0)
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
    throttle(client, 0)
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
    gate = budget(client)  # the peer takes a trickle: 100 bytes a tick
    biggest = 0
    for _ in range(300):
        try:
            sock.send(b"{}\n" * 500)
        except BlockingIOError:
            pass
        gate.budget = 100
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
    throttle(client, 64 * 1024)
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


def small_sndbuf(srv, limit=64 * 1024):
    """Accept the client and let each send take at most ``limit`` bytes (0: none)."""
    tick(srv)
    (client,) = srv.clients.values()
    throttle(client, limit)
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
    tick(server)
    (client,) = server.clients.values()
    budget(client, 0)  # nothing can leave, whatever the kernel would buffer
    request(sock, "big")
    sock.shutdown(socket.SHUT_WR)
    pump(server, until=lambda: len(client.wbuf) > 0)  # the stall clock starts here
    assert server.client_count == 1
    clock.t += mod.CLOSE_GRACE + 5  # the error-close grace does not apply to it
    tick(server)
    assert server.client_count == 1
    clock.t += mod.WRITE_STALL
    tick(server)
    assert server.client_count == 0


# --- token and handshake ---------------------------------------------------------


def only_client(srv):
    (client,) = srv.clients.values()
    return client


def hello_only(srv, sock, **kw):
    """Send a good hello and return (nc, hello result)."""
    nc = WIRE.new_nonce()
    sock.sendall(hello_line(nc, **kw))
    return nc, read_line(srv, sock)["result"]


def error_of(srv, sock):
    """Read to EOF and return the single error reply's (code, message, id)."""
    data = read_all(srv, sock)
    lines = [line for line in data.split(b"\n") if line]
    assert len(lines) == 1, data
    reply = json.loads(lines[0])
    return reply["error"]["code"], reply["error"]["message"], reply["id"]


def test_start_creates_the_token(server, tmp_path):
    assert (tmp_path / "meshwire" / "token").read_text().strip() == server.token


def test_good_handshake_authenticates(server):
    sock = connect(server, auth=False)
    nc = WIRE.new_nonce()
    sock.sendall(hello_line(nc, req_id=7))
    reply = read_line(server, sock)
    assert reply["id"] == 7
    result = reply["result"]
    assert result["protocol"] == 1 and result["port"] == server.port
    assert isinstance(result["addon"], str)
    assert only_client(server).authed is False  # not until the client proves itself
    assert result["proof"] == WIRE.proof(
        server.token, WIRE.ADDON_LABEL, nc, result["nonce"], result["seen"]
    )
    assert result["seen"] == f"127.0.0.1:{server.port}"
    assert len(result["nonce"]) >= 16
    sock.sendall(proof_line(WIRE.proof(server.token, WIRE.CLIENT_LABEL, result["nonce"], nc), 8))
    reply = read_line(server, sock)
    assert reply == {"jsonrpc": "2.0", "result": {"ok": True}, "id": 8}
    assert only_client(server).authed is True
    request(sock, "ping", req_id=9)
    assert read_line(server, sock)["result"] == {"echo": "ping"}


def test_token_never_leaves_the_addon(server):
    sock = connect(server, auth=False)
    _, result = hello_only(server, sock)
    assert server.token not in json.dumps(result)


def test_each_connection_gets_a_fresh_server_nonce(server):
    first = hello_only(server, connect(server, auth=False))[1]
    second = hello_only(server, connect(server, auth=False))[1]
    assert first["nonce"] != second["nonce"]


def test_request_before_hello_is_refused(server, mod):
    sock = connect(server, auth=False)
    request(sock, "ping", req_id=5)
    code, message, msg_id = error_of(server, sock)
    assert code == mod.wire.E_PROTOCOL and msg_id == 5
    assert "needs a newer Meshwire server" in message
    assert "uvx meshwire@latest" in message
    assert "ping" not in server.handlers.calls


def test_http_request_closed_without_reply(server):
    sock = connect(server, auth=False)
    body = b'{"jsonrpc":"2.0","method":"ping","id":1}'
    sock.sendall(b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 39\r\n\r\n" + body + b"\n")
    assert read_all(server, sock) == b""
    pump(server, until=lambda: server.client_count == 0)
    assert server.handlers.calls == []


def test_garbage_first_line_closed_without_reply(server):
    sock = connect(server, auth=False)
    sock.sendall(b"[1, 2]\n")
    assert read_all(server, sock) == b""


def test_bad_client_proof_rejected_then_closed(server, mod):
    sock = connect(server, auth=False)
    nc, result = hello_only(server, sock)
    sock.sendall(proof_line("0" * 64, 9) + jline({"method": "ping", "id": 3}))
    code, message, msg_id = error_of(server, sock)
    assert code == mod.wire.E_UNAUTHORIZED and msg_id == 9
    assert server.token not in message
    assert server.handlers.calls == []
    pump(server, until=lambda: server.client_count == 0)


def test_right_proof_for_the_wrong_token_is_rejected(server, mod):
    sock = connect(server, auth=False)
    nc, result = hello_only(server, sock)
    sock.sendall(proof_line(WIRE.proof("some-other-token", WIRE.CLIENT_LABEL, result["nonce"], nc)))
    assert error_of(server, sock)[0] == mod.wire.E_UNAUTHORIZED


def test_the_addons_own_proof_cannot_be_replayed_as_the_clients(server, mod):
    sock = connect(server, auth=False)
    nc, result = hello_only(server, sock)
    sock.sendall(proof_line(result["proof"]))
    assert error_of(server, sock)[0] == mod.wire.E_UNAUTHORIZED


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
        " " + "a" * 63,
        "\ud800" * 64,
        "\ud800",
        123,
        None,
        True,
        ["a" * 64],
        {"proof": "a" * 64},
    ],
)
def test_proof_must_be_64_hex(server, mod, capsys, value):
    sock = connect(server, auth=False)
    hello_only(server, sock)
    sock.sendall(proof_line(value))
    assert error_of(server, sock)[0] == mod.wire.E_UNAUTHORIZED
    out = capsys.readouterr()
    assert "Traceback" not in out.out + out.err


def test_uppercase_form_of_the_right_proof_is_rejected(server, mod):
    sock = connect(server, auth=False)
    nc, result = hello_only(server, sock)
    good = WIRE.proof(server.token, WIRE.CLIENT_LABEL, result["nonce"], nc)
    sock.sendall(proof_line(good.upper()))
    assert error_of(server, sock)[0] == mod.wire.E_UNAUTHORIZED


def test_missing_proof_param_is_unauthorized(server, mod):
    sock = connect(server, auth=False)
    hello_only(server, sock)
    sock.sendall(jline({"jsonrpc": "2.0", "method": "hello_proof", "params": [], "id": 4}))
    assert error_of(server, sock)[0] == mod.wire.E_UNAUTHORIZED


@pytest.mark.parametrize("method", ["ping", "hello", "scene_info", "hello_proof2"])
def test_second_line_must_be_hello_proof(server, mod, method):
    sock = connect(server, auth=False)
    nc, result = hello_only(server, sock)
    good = WIRE.proof(server.token, WIRE.CLIENT_LABEL, result["nonce"], nc)
    sock.sendall(proof_line(good, method=method))  # right proof, wrong method
    code, _, _ = error_of(server, sock)
    assert code == mod.wire.E_UNAUTHORIZED
    assert server.handlers.calls == []


def test_non_json_second_line_is_unauthorized_then_closed(server, mod):
    sock = connect(server, auth=False)
    hello_only(server, sock)
    sock.sendall(b"not json\n")
    assert error_of(server, sock)[0] == mod.wire.E_UNAUTHORIZED


def test_request_pipelined_behind_hello_never_runs(server, mod):
    sock = connect(server, auth=False)
    sock.sendall(hello_line() + jline({"jsonrpc": "2.0", "method": "ping", "id": 2}))
    data = read_all(server, sock)
    lines = [json.loads(line) for line in data.split(b"\n") if line]
    assert "result" in lines[0] and lines[1]["error"]["code"] == mod.wire.E_UNAUTHORIZED
    assert len(lines) == 2
    assert server.handlers.calls == []


@pytest.mark.parametrize(
    "nonce",
    [
        "short",
        "a" * 15,
        "a" * 129,
        "a" * 15 + "!",
        "a" * 16 + " ",
        12345,
        None,
        ["a" * 20],
        "\ud800" * 20,
    ],
)
def test_nonce_must_be_urlsafe_16_to_128(server, mod, nonce):
    sock = connect(server, auth=False)
    sock.sendall(
        jline(
            {
                "jsonrpc": "2.0",
                "method": "hello",
                "params": {"protocol": 1, "client": "t", "nonce": nonce},
                "id": 1,
            }
        )
    )
    assert error_of(server, sock)[0] == mod.wire.E_PROTOCOL


@pytest.mark.parametrize("nonce", ["a" * 16, "a" * 128, "A-_" * 10 + "9"])
def test_nonce_bounds_are_inclusive(server, nonce):
    sock = connect(server, auth=False)
    sock.sendall(hello_line(nonce))
    assert read_line(server, sock)["result"]["protocol"] == 1


def test_hello_without_a_nonce_is_refused(server, mod):
    sock = connect(server, auth=False)
    msg = {"jsonrpc": "2.0", "method": "hello", "params": {"protocol": 1}, "id": 1}
    sock.sendall(jline(msg))
    assert error_of(server, sock)[0] == mod.wire.E_PROTOCOL


def test_protocol_mismatch_names_the_side_to_update(server, mod):
    newer = connect(server, auth=False)
    newer.sendall(hello_line(protocol=2))
    code, message, _ = error_of(server, newer)
    assert code == mod.wire.E_PROTOCOL
    assert "protocol 1" in message and "2" in message
    assert message.endswith("Update the Meshwire add-on in Blender.")
    older = connect(server, auth=False)
    older.sendall(hello_line(protocol=0))
    code, message, _ = error_of(server, older)
    assert code == mod.wire.E_PROTOCOL
    assert message.endswith("Update the Meshwire server.")


@pytest.mark.parametrize("value", [True, 1.0, "1", None, [1]])
def test_protocol_must_be_the_int_one(server, mod, value):
    sock = connect(server, auth=False)
    sock.sendall(hello_line(protocol=value))
    assert error_of(server, sock)[0] == mod.wire.E_PROTOCOL


def test_hello_over_4k_closed(server, mod):
    sock = connect(server, auth=False)
    sock.sendall(hello_line(pad="x" * (mod.wire.HELLO_MAX + 10)))
    assert read_all(server, sock) == b""


def test_4k_without_newline_closed(server, mod):
    sock = connect(server, auth=False)
    sock.sendall(b"x" * (mod.wire.HELLO_MAX + 1))
    assert read_all(server, sock) == b""


def test_proof_line_over_4k_closed(server, mod):
    sock = connect(server, auth=False)
    hello_only(server, sock)
    sock.sendall(proof_line("a" * (mod.wire.HELLO_MAX + 10)))
    assert read_all(server, sock) == b""


def test_hello_of_exactly_the_limit_is_accepted(server, mod):
    sock = connect(server, auth=False)
    base = hello_line("n" * 20)
    msg = json.loads(base)
    msg["params"]["client"] = ""
    room = mod.wire.HELLO_MAX - len(json.dumps(msg).encode())
    msg["params"]["client"] = "c" * room
    line = json.dumps(msg).encode()
    assert len(line) == mod.wire.HELLO_MAX
    sock.sendall(line + b"\n")
    assert read_line(server, sock)["result"]["protocol"] == 1


def test_a_pre_auth_client_is_read_only_up_to_the_hello_limit(server, mod):
    connect(server, auth=False)
    tick(server)
    client = only_client(server)
    stub = client.sock = Chunked(client.sock, 2 * MIB)
    pump(server, until=lambda: client not in server.clients.values())  # over the limit: closed
    sizes = stub.wanted
    assert sizes
    assert max(sizes) <= mod.wire.HELLO_MAX + 1
    assert sum(sizes) <= mod.wire.HELLO_MAX + 1 + len(sizes)  # at most one short read per tick


def test_hello_after_deadline_closed(server, mod):
    clock = with_clock(server)
    sock = connect(server, auth=False)
    tick(server)
    clock.t += mod.wire.HELLO_SECONDS + 0.01
    sock.sendall(hello_line())
    assert read_all(server, sock) == b""


def test_proof_after_deadline_closed(server, mod):
    """The deadline covers both lines: a slow second step is closed too."""
    clock = with_clock(server)
    sock = connect(server, auth=False)
    tick(server)
    nc, result = hello_only(server, sock)
    clock.t += mod.wire.HELLO_SECONDS + 0.01
    sock.sendall(proof_line(WIRE.proof(server.token, WIRE.CLIENT_LABEL, result["nonce"], nc)))
    assert read_all(server, sock) == b""
    assert server.client_count == 0


def test_hello_just_before_deadline_is_accepted(server, mod):
    clock = with_clock(server)
    sock = connect(server, auth=False)
    tick(server)
    clock.t += mod.wire.HELLO_SECONDS - 0.01
    handshake(server, sock)
    assert only_client(server).authed


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
    sock.sendall(b'{"jsonrpc":"2.0","method":"hello"')
    sock.shutdown(socket.SHUT_WR)
    tick(server, 3)
    clock.t += mod.wire.HELLO_SECONDS + 0.01
    assert read_all(server, sock) == b""


def test_wrong_proof_client_that_never_reads_leaves_by_the_deadline(server, mod):
    clock = with_clock(server)
    sock = connect(server, auth=False)
    tick(server)
    hello_only(server, sock)
    sock.sendall(proof_line("0" * 64))
    tick(server, 3)
    clock.t += mod.wire.HELLO_SECONDS + 0.01
    tick(server, 3)
    assert server.client_count == 0
    assert sock


def test_deadline_applies_only_before_hello(server, mod):
    """A 10 s handler, run after auth, costs the client nothing."""
    clock = with_clock(server)
    sock = connect(server)
    real = server.handlers.handle

    def slow(method, params):
        if method == "slow":
            clock.t += 10.0  # the handler "runs" for 10 s on the injected clock
            return {"done": True}
        return real(method, params)

    server.handlers.handle = slow
    request(sock, "slow", req_id=4)
    reply = read_line(server, sock)
    assert reply["id"] == 4 and reply["result"] == {"done": True}
    assert server.client_count == 1 and only_client(server).authed
    clock.t += 3600.0
    tick(server, 3)
    request(sock, "ping", req_id=5)
    assert read_line(server, sock)["id"] == 5


def test_deadline_counts_from_accept_not_from_connect(server, mod):
    clock = with_clock(server)
    sock = connect(server, auth=False)
    clock.t += 5.0
    sock.sendall(hello_line())
    tick(server)
    assert read_line(server, sock)["result"]["protocol"] == 1


# --- pools -----------------------------------------------------------------------


def test_idle_pre_auth_sockets_do_not_lock_out_the_real_client(server, mod):
    idle = []
    for _ in range(mod.MAX_PENDING):
        idle.append(connect(server, auth=False))
        tick(server)  # accept, so the listen backlog never fills
    assert server.client_count == mod.MAX_PENDING
    real = connect(server)  # evicts the oldest idle socket, then authenticates
    request(real, "ping")
    assert read_line(server, real)["result"] == {"echo": "ping"}
    assert idle  # still referenced


def test_a_full_pending_pool_evicts_the_oldest(server, mod, monkeypatch):
    monkeypatch.setattr(mod, "MAX_PENDING", 3)
    first = connect(server, auth=False)
    tick(server)
    others = []
    for _ in range(3):
        others.append(connect(server, auth=False))
        tick(server)
    assert server.client_count == 3
    assert read_all(server, first) == b""  # the oldest was dropped, not answered
    assert others


def test_ninth_authenticated_client_gets_too_many_after_proof(server, mod):
    socks = [connect(server) for _ in range(mod.MAX_CLIENTS)]
    ninth = connect(server, auth=False)
    nc, result = hello_only(server, ninth)
    ninth.sendall(proof_line(WIRE.proof(server.token, WIRE.CLIENT_LABEL, result["nonce"], nc), 6))
    code, _, msg_id = error_of(server, ninth)
    assert code == mod.wire.E_TOO_MANY and msg_id == 6
    pump(server, until=lambda: server.client_count == mod.MAX_CLIENTS)
    request(socks[0], "ping")
    assert read_line(server, socks[0])["result"] == {"echo": "ping"}


def test_http_noise_is_not_told_the_server_is_full(server, mod):
    socks = [connect(server) for _ in range(mod.MAX_CLIENTS)]
    noise = connect(server, auth=False)
    noise.sendall(b"GET / HTTP/1.1\r\n\r\n")
    assert read_all(server, noise) == b""
    assert socks


def test_closing_authenticated_clients_still_count_toward_the_cap(server, mod):
    with_clock(server)
    socks = [connect(server) for _ in range(mod.MAX_CLIENTS - 1)]
    bad = connect(server)
    bad.sendall(b"{nope\n")
    pump(
        server, until=lambda: any(c.closing for c in server.clients.values())
    )  # still holds a slot
    late = connect(server, auth=False)
    nc, result = hello_only(server, late)
    late.sendall(proof_line(WIRE.proof(server.token, WIRE.CLIENT_LABEL, result["nonce"], nc)))
    assert error_of(server, late)[0] == mod.wire.E_TOO_MANY
    assert socks


def test_refusals_beyond_max_closing_close_without_reply(server, mod, monkeypatch):
    with_clock(server)
    monkeypatch.setattr(mod, "MAX_CLIENTS", 1)
    monkeypatch.setattr(mod, "MAX_CLOSING", 2)
    keeper = connect(server)
    refused = []
    for _ in range(2):  # these two get a reply and fill the closing allowance
        sock = connect(server, auth=False)
        nc, result = hello_only(server, sock)
        refusing = list(server.clients.values())[-1]
        throttle(refusing, 0)  # its refusal stays unsent: closing
        sock.sendall(proof_line(WIRE.proof(server.token, WIRE.CLIENT_LABEL, result["nonce"], nc)))
        pump(server, until=lambda: refusing.closing)
        refused.append(sock)
    assert sum(c.closing for c in server.clients.values()) == 2
    extra = connect(server, auth=False)
    nc, result = hello_only(server, extra)
    dropped = list(server.clients.values())[-1]
    extra.sendall(proof_line(WIRE.proof(server.token, WIRE.CLIENT_LABEL, result["nonce"], nc)))
    pump(server, until=lambda: dropped not in server.clients.values())
    extra.setblocking(True)
    extra.settimeout(5)
    assert extra.recv(100) == b""  # closed with no reply
    assert keeper


# --- token guards ----------------------------------------------------------------


def test_server_refuses_to_serve_with_a_short_token(mod, monkeypatch):
    monkeypatch.setattr(mod.wire, "ensure_token", lambda: "short")
    srv = mod.MCPSocketServer("127.0.0.1", free_port())
    with pytest.raises(mod.TokenError, match="too short"):
        srv.start()
    assert not srv.is_running and srv.socket is None


def test_token_file_failure_has_its_own_error(mod, monkeypatch, tmp_path):
    def boom():
        raise OSError("permission denied")

    monkeypatch.setattr(mod.wire, "ensure_token", boom)
    srv = mod.MCPSocketServer("127.0.0.1", free_port())
    with pytest.raises(mod.TokenError) as info:
        srv.start()
    text = str(info.value)
    assert text.startswith("Could not read or create the Meshwire token at ")
    assert str(mod.wire.token_path()) in text and "permission denied" in text
    assert not srv.is_running and srv.socket is None  # nothing was bound


def test_empty_server_token_never_authenticates(server, mod):
    server._token = ""
    sock = connect(server, auth=False)
    sock.sendall(hello_line())
    assert read_all(server, sock) == b""


# --- the proof is tied to the address the bytes arrived at ------------------------


def test_seen_is_the_sockets_own_local_address(server):
    sock = connect(server, auth=False)
    result = hello_only(server, sock)[1]
    assert result["seen"] == WIRE.endpoint("127.0.0.1", server.port)


def test_seen_is_inside_the_proof(server):
    """A relay that rewrites ``seen`` breaks Pa, because Pa covers it."""
    sock = connect(server, auth=False)
    nc, result = hello_only(server, sock)
    good = WIRE.proof(server.token, WIRE.ADDON_LABEL, nc, result["nonce"], result["seen"])
    assert result["proof"] == good
    forged = WIRE.proof(server.token, WIRE.ADDON_LABEL, nc, result["nonce"], "127.0.0.1:1")
    assert forged != result["proof"]
    assert WIRE.proof(server.token, WIRE.ADDON_LABEL, nc, result["nonce"]) != result["proof"]


# --- ids are echoed only when they are safe to ---------------------------------


def _parses_from_a_deep_stack(document, frames=40):
    """Can json parse ``document`` with about as much stack under it as a server tick has?

    The recursion limit differs between Python versions, so a depth near it parses on
    some and not on others.
    """
    if frames:
        return _parses_from_a_deep_stack(document, frames - 1)
    try:
        json.loads(document)
    except RecursionError:
        return False
    return True


@pytest.mark.parametrize("depth", [1, 5, 940, 945, 950])
def test_nested_list_id_gets_an_error_with_null_id(server, mod, capsys, depth):
    nested = "[" * depth + "]" * depth
    document = '{"jsonrpc":"2.0","method":"hello","id":' + nested + "}"
    if not _parses_from_a_deep_stack(document):
        # Where json itself gives up, the server closes the line unanswered, as designed.
        pytest.skip("this interpreter's recursion limit cannot parse that deep")
    sock = connect(server, auth=False)
    sock.sendall((document + "\n").encode())
    code, _, msg_id = error_of(server, sock)
    assert code == -32600 and msg_id is None
    out = capsys.readouterr()
    assert "Traceback" not in out.out + out.err


@pytest.mark.parametrize("bad", ["1.5", "true", "false", "[]", '{"a": 1}', "[[1]]", "1e3"])
def test_only_str_int_or_null_ids_are_accepted(server, bad):
    sock = connect(server, auth=False)
    sock.sendall(('{"jsonrpc":"2.0","method":"hello","id":' + bad + "}\n").encode())
    code, _, msg_id = error_of(server, sock)
    assert code == -32600 and msg_id is None


def test_a_bad_id_after_auth_is_refused_too(server):
    sock = connect(server)
    sock.sendall(b'{"jsonrpc":"2.0","method":"ping","id":[[1]]}\n')
    code, _, msg_id = error_of(server, sock)
    assert code == -32600 and msg_id is None
    assert server.handlers.calls == []


@pytest.mark.parametrize("good", ['"abc"', "7", "null", "-3", "0"])
def test_str_int_and_null_ids_still_work(server, good):
    sock = connect(server)
    sock.sendall(('{"jsonrpc":"2.0","method":"ping","id":' + good + "}\n").encode())
    assert read_line(server, sock)["id"] == json.loads(good)


def test_a_bad_id_in_the_proof_line_is_refused(server):
    sock = connect(server, auth=False)
    hello_only(server, sock)
    sock.sendall(b'{"jsonrpc":"2.0","method":"hello_proof","params":{"proof":"a"},"id":[1]}\n')
    code, _, msg_id = error_of(server, sock)
    assert code == -32600 and msg_id is None


# --- a closing pre-auth client is read in normal chunks ---------------------------


def test_a_closing_pre_auth_client_is_not_read_in_tiny_chunks(server, mod):
    sock = connect(server, auth=False)
    hello_only(server, sock)
    sock.sendall(proof_line("0" * 64))
    client = only_client(server)
    pump(server, until=lambda: client.closing)  # the bad proof closes it
    assert not client.authed
    stub = client.sock = Chunked(client.sock, 2 * MIB)
    pump(server, until=lambda: stub.calls >= 1)
    assert max(stub.wanted) > 64 * 1024


def test_protocol_mismatch_carries_the_addons_protocol_as_data(server, mod):
    sock = connect(server, auth=False)
    sock.sendall(hello_line(protocol=2))
    data = read_all(server, sock)
    assert json.loads(data.split(b"\n", 1)[0])["error"]["data"] == {"protocol": 1}
