"""Several Blenders at once: port binding, instance files and how the server finds one.

The add-on half runs Blender-free on real loopback sockets, through the fixtures of
tests/test_socket_server.py. The server half uses the server's own wire.py.
"""

import asyncio
import errno
import json
import logging
import os
import socket
import stat
import sys
import time
from contextlib import closing

import pytest

from mcp_blender import server as server_module
from mcp_blender import wire
from mcp_blender.blender_client import BlenderClient, BlenderConnectionError, _NotMeshwire
from tests.test_client import V040_UNKNOWN_METHOD, MockBlenderServer
from tests.test_socket_server import ROOT, _own_config_dir, mod  # noqa: F401

POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="Windows socket options")


def free_pair() -> int:
    """A port p such that p and p + 1 were both free a moment ago."""
    for _ in range(50):
        with closing(socket.socket()) as probe:
            probe.bind(("127.0.0.1", 0))
            first = probe.getsockname()[1]
        if first >= 65000:
            continue
        try:
            with closing(socket.socket()) as probe:
                probe.bind(("127.0.0.1", first + 1))
        except OSError:
            continue
        return first
    pytest.skip("no two adjacent free ports")


def hold(port: int) -> socket.socket:
    sock = socket.socket()
    if sys.platform != "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(5)
    return sock


def listener() -> socket.socket:
    sock = hold(0)
    return sock


def info(**over) -> dict:
    base = {"addon": "0.5.0", "blender": "4.5.15", "blend": "/work/a.blend"}
    base.update(over)
    return base


@pytest.fixture
def held():
    socks = []
    yield socks
    for sock in socks:
        sock.close()


@pytest.fixture
def narrow_range(mod, monkeypatch):  # noqa: F811
    """The add-on scans two ports, both free at the start of the test."""
    first = free_pair()
    addon_wire = sys.modules[f"{ROOT}.wire"]
    monkeypatch.setattr(addon_wire, "PORT_FIRST", first)
    monkeypatch.setattr(addon_wire, "PORT_LAST", first + 1)
    return first


# --- binding -------------------------------------------------------------------


def test_port_range_lives_in_wire():
    assert (wire.PORT_FIRST, wire.PORT_LAST) == (9876, 9885)


def test_auto_port_takes_first_free_in_range(mod, narrow_range, held):  # noqa: F811
    held.append(hold(narrow_range))
    srv = mod.MCPSocketServer("127.0.0.1", 0)
    assert srv.start()
    try:
        assert srv.port == narrow_range + 1
        assert srv.socket.getsockname()[1] == narrow_range + 1
    finally:
        srv.stop()


def test_auto_port_prefers_the_first_port_when_free(mod, narrow_range):  # noqa: F811
    srv = mod.MCPSocketServer("127.0.0.1", 0)
    assert srv.start()
    try:
        assert srv.port == narrow_range
    finally:
        srv.stop()


def test_range_exhausted_reports_error(mod, narrow_range, held):  # noqa: F811
    held.append(hold(narrow_range))
    held.append(hold(narrow_range + 1))
    srv = mod.MCPSocketServer("127.0.0.1", 0)
    with pytest.raises(mod.BindError) as raised:
        srv.start()
    text = str(raised.value)
    assert str(narrow_range) in text and str(narrow_range + 1) in text
    assert "in use" in text
    assert not srv.is_running and srv.socket is None


def test_explicit_port_in_use_names_that_port(mod, narrow_range, held):  # noqa: F811
    held.append(hold(narrow_range))
    srv = mod.MCPSocketServer("127.0.0.1", narrow_range)
    with pytest.raises(mod.BindError) as raised:
        srv.start()
    assert str(narrow_range) in str(raised.value)
    # Exactly that port: the free neighbour is not used instead.
    assert srv.socket is None


def test_explicit_port_out_of_range_is_refused(mod):  # noqa: F811
    for bad in (80, 70000, -5):
        with pytest.raises(mod.BindError) as raised:
            mod.MCPSocketServer("127.0.0.1", bad).start()
        assert "1024" in str(raised.value)


def test_windows_uses_exclusive_bind(mod, monkeypatch):  # noqa: F811
    calls = []

    class Fake:
        def setsockopt(self, level, name, value):
            calls.append((name, value))

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod.socket, "SO_EXCLUSIVEADDRUSE", -5, raising=False)
    mod._configure_listener(Fake())
    names = [name for name, _ in calls]
    assert -5 in names
    assert socket.SO_REUSEADDR not in names


def test_posix_keeps_reuseaddr(mod, monkeypatch):  # noqa: F811
    calls = []

    class Fake:
        def setsockopt(self, level, name, value):
            calls.append((name, value))

    monkeypatch.setattr(mod.sys, "platform", "linux")
    mod._configure_listener(Fake())
    assert (socket.SO_REUSEADDR, 1) in calls


def test_windows_error_codes_count_as_a_taken_port(mod):  # noqa: F811
    class Winerror(OSError):
        def __init__(self, code):
            super().__init__(0, "fake")
            self.winerror = code
            self.errno = None

    assert mod._port_taken(Winerror(10048))
    assert mod._port_taken(Winerror(10013))
    assert not mod._port_taken(Winerror(10049))
    assert mod._port_taken(OSError(errno.EADDRINUSE, "in use"))
    assert mod._port_taken(OSError(errno.EACCES, "denied"))
    assert not mod._port_taken(OSError(errno.EADDRNOTAVAIL, "bad address"))


def test_auto_scan_moves_past_a_windows_access_denied(mod, narrow_range, held, monkeypatch):  # noqa: F811
    real = mod.socket.socket
    calls = []

    class Denying:
        """The first port refuses the way an exclusive bind does on Windows."""

        def __init__(self, *args):
            self._sock = real(*args)

        def bind(self, address):
            calls.append(address[1])
            if address[1] == narrow_range:
                err = OSError(0, "denied")
                err.winerror, err.errno = 10013, None
                raise err
            return self._sock.bind(address)

        def __getattr__(self, name):
            return getattr(self._sock, name)

    monkeypatch.setattr(mod.socket, "socket", Denying)
    srv = mod.MCPSocketServer("127.0.0.1", 0)
    assert srv.start()
    try:
        assert srv.port == narrow_range + 1 and calls == [narrow_range, narrow_range + 1]
    finally:
        srv.stop()


def test_a_second_start_scans_the_range_again(mod, narrow_range, held):  # noqa: F811
    srv = mod.MCPSocketServer("127.0.0.1", 0)
    assert srv.start()
    assert srv.port == narrow_range and srv.requested_port == 0
    srv.stop()
    held.append(hold(narrow_range))
    assert srv.start()
    try:
        assert srv.port == narrow_range + 1
    finally:
        srv.stop()


def test_a_taken_instance_file_failure_is_reported_not_fatal(mod, narrow_range, monkeypatch):  # noqa: F811
    def broken(port, info):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(sys.modules[f"{ROOT}.wire"], "write_instance", broken)
    srv = mod.MCPSocketServer("127.0.0.1", 0)
    assert srv.start()  # the server still serves
    try:
        warning = srv.discovery_warning
        assert warning.startswith("Discovery is off: could not write the instance file at ")
        assert str(wire.instances_dir() / f"{srv.port}.json") in warning
        assert "Permission denied" in warning
        assert f"Clients need --port {srv.port}." in warning
    finally:
        srv.stop()
    assert srv.discovery_warning == ""


@WINDOWS_ONLY
def test_windows_second_bind_on_the_same_port_fails(mod, narrow_range):  # noqa: F811
    first = mod.MCPSocketServer("127.0.0.1", narrow_range)
    assert first.start()
    try:
        with pytest.raises(mod.BindError):
            mod.MCPSocketServer("127.0.0.1", narrow_range).start()
    finally:
        first.stop()


# --- the instance file -----------------------------------------------------------


def test_instance_file_written_and_removed(mod, narrow_range):  # noqa: F811
    srv = mod.MCPSocketServer("127.0.0.1", 0)
    assert srv.start()
    path = wire.instances_dir() / f"{srv.port}.json"
    try:
        data = json.loads(path.read_text())
        assert set(data) == {
            "port",
            "host",
            "pid",
            "protocol",
            "addon",
            "blender",
            "blend",
            "started",
        }
        assert data["host"] == "127.0.0.1"
        assert data["port"] == srv.port and data["pid"] == os.getpid()
        assert data["protocol"] == wire.PROTOCOL
        assert abs(data["started"] - time.time()) < 60
        assert wire.read_token() not in path.read_text()
    finally:
        srv.stop()
    assert not path.exists()


def test_failed_bind_leaves_no_instance_file(mod, narrow_range, held):  # noqa: F811
    held.append(hold(narrow_range))
    with pytest.raises(mod.BindError):
        mod.MCPSocketServer("127.0.0.1", narrow_range).start()
    assert not list(wire.instances_dir().glob("*.json")) if wire.instances_dir().exists() else True


@POSIX_ONLY
def test_write_instance_modes_under_a_loose_umask(tmp_path, monkeypatch):
    monkeypatch.setenv("MESHWIRE_CONFIG_DIR", str(tmp_path / "fresh"))
    old = os.umask(0o002)
    try:
        path = wire.write_instance(9876, info())
    finally:
        os.umask(old)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.parent.parent.stat().st_mode) == 0o700
    wire.read_token()  # the token checks accept the folder


def test_write_instance_is_atomic_and_leaves_no_temp(tmp_path, monkeypatch):
    monkeypatch.setenv("MESHWIRE_CONFIG_DIR", str(tmp_path / "cfg"))
    path = wire.write_instance(9877, info())
    assert path == wire.instances_dir() / "9877.json"
    wire.write_instance(9877, info(blend="/other.blend"))
    assert json.loads(path.read_text())["blend"] == "/other.blend"
    assert [p.name for p in wire.instances_dir().iterdir()] == ["9877.json"]


def test_remove_instance(tmp_path, monkeypatch):
    monkeypatch.setenv("MESHWIRE_CONFIG_DIR", str(tmp_path / "cfg"))
    path = wire.write_instance(9877, info())
    wire.remove_instance(9877)
    wire.remove_instance(9877)  # already gone is fine
    assert not path.exists()


# --- discovery -------------------------------------------------------------------


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.delenv("MESHWIRE_TOKEN", raising=False)
    monkeypatch.delenv("MESHWIRE_PORT", raising=False)
    monkeypatch.setenv("MESHWIRE_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path / "cfg"


def live(held, started, **over):
    sock = listener()
    held.append(sock)
    port = sock.getsockname()[1]
    wire.write_instance(port, info(started=started, **over))
    return port


def test_most_recent_live_instance_wins(cfg, held):
    older = live(held, 1000.0, blend="/old.blend")
    newer = live(held, 2000.0, blend="/new.blend")
    found = wire.live_instances()
    assert [i["port"] for i in found] == [newer, older]
    assert found[0]["blend"] == "/new.blend"


@POSIX_ONLY
def test_stale_instance_file_is_removed(cfg, held):
    good = live(held, 1000.0)
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        dead = probe.getsockname()[1]
    stale = wire.write_instance(dead, info(started=5000.0))
    assert [i["port"] for i in wire.live_instances()] == [good]
    assert not stale.exists()


# --- the probe's three answers ---------------------------------------------------


def fake_probe(monkeypatch, answers, seen=None):
    def probe(host, port, timeout):
        if seen is not None:
            seen.append((host, port, timeout))
        return answers[port]

    monkeypatch.setattr(wire, "_probe", probe)


def test_probe_answers_decide_choose_delete_or_keep(cfg, monkeypatch, caplog):
    paths = {p: wire.write_instance(p, info(started=float(p))) for p in (9001, 9002, 9003)}
    fake_probe(monkeypatch, {9001: "live", 9002: "refused", 9003: "unknown"})
    with caplog.at_level(logging.INFO, logger="meshwire.wire"):
        found = wire.live_instances()
    assert [(i["port"], i["probe"]) for i in found] == [(9003, "unknown"), (9001, "live")]
    assert paths[9001].exists()
    assert not paths[9002].exists()  # refused: nothing listens, so the file is stale
    assert paths[9003].exists()  # unknown (a timeout): kept, and still tried, in order
    assert "9003" in caplog.text


def test_probe_timeout_does_not_delete_a_live_blenders_file(cfg, monkeypatch):
    path = wire.write_instance(9004, info())
    monkeypatch.setattr(wire, "_probe", lambda host, port, timeout: "unknown")
    assert [(i["port"], i["probe"]) for i in wire.live_instances()] == [(9004, "unknown")]
    assert path.exists()
    monkeypatch.setattr(wire, "_probe", lambda host, port, timeout: "live")
    assert [(i["port"], i["probe"]) for i in wire.live_instances()] == [(9004, "live")]


def test_real_probe_sees_a_live_listener(held):
    sock = listener()
    held.append(sock)
    assert wire._probe("127.0.0.1", sock.getsockname()[1], 1.0) == "live"


@POSIX_ONLY
def test_real_probe_sees_a_refusal():
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        dead = probe.getsockname()[1]
    assert wire._probe("127.0.0.1", dead, 1.0) == "refused"


def test_probe_timeout_is_unknown_not_refused(monkeypatch):
    def slow(*args, **kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setattr(wire.socket, "create_connection", slow)
    assert wire._probe("127.0.0.1", 9999, 0.2) == "unknown"


def test_probe_uses_the_recorded_host_and_maps_wildcards(cfg, monkeypatch):
    wire.write_instance(9010, info(host="127.0.0.1"))
    wire.write_instance(9011, info(host="0.0.0.0"))
    wire.write_instance(9012, info(host="::"))
    wire.write_instance(9013, info(host="::1"))
    seen = []
    fake_probe(monkeypatch, {p: "live" for p in (9010, 9011, 9012, 9013)}, seen)
    wire.live_instances()
    assert {(h, p) for h, p, _ in seen} == {
        ("127.0.0.1", 9010),
        ("127.0.0.1", 9011),
        ("::1", 9012),
        ("::1", 9013),
    }
    assert all(t == wire.PROBE_SECONDS for _, _, t in seen)


def test_instances_bound_elsewhere_are_left_alone(cfg, monkeypatch):
    path = wire.write_instance(9020, info(host="192.168.1.50"))
    seen = []
    fake_probe(monkeypatch, {}, seen)
    assert wire.live_instances() == []
    assert seen == [] and path.exists()


def test_a_file_replaced_during_the_probe_is_not_deleted(cfg, monkeypatch):
    path = wire.write_instance(9030, info(started=1.0))

    def probe(host, port, timeout):
        wire.write_instance(9030, info(started=2.0))  # a new Blender took the port
        return "refused"

    monkeypatch.setattr(wire, "_probe", probe)
    assert wire.live_instances() == []
    assert path.exists() and json.loads(path.read_text())["started"] == 2.0


def test_a_failed_write_leaves_no_temp_file(cfg, monkeypatch):
    def boom(fd):
        raise OSError(5, "I/O error")

    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError):
        wire.write_instance(9040, info())
    assert list(wire.instances_dir().iterdir()) == []


def test_old_temp_files_are_cleaned_and_other_files_are_not(cfg):
    wire.write_instance(9041, info())
    d = wire.instances_dir()
    old = d / ".9041.123.deadbeef.tmp"
    fresh = d / ".9041.124.cafef00d.tmp"
    other = d / ".9041.notes.tmp"
    for f in (old, fresh, other):
        f.write_text("x")
    os.utime(old, (time.time() - 7200,) * 2)
    os.utime(other, (time.time() - 7200,) * 2)
    wire.clean_stale_temps()
    assert not old.exists() and fresh.exists() and other.exists()
    assert (d / "9041.json").exists()


def test_malformed_files_are_ignored_and_kept(cfg, held):
    good = live(held, 1000.0)
    d = wire.instances_dir()
    (d / "1.json").write_text("{not json")
    (d / "notes.json").write_text("{}")
    (d / "9990.json").write_text(json.dumps({"port": 9990}))
    (d / "80.json").write_text(json.dumps(dict(info(), port=80, pid=1, protocol=1, started=1.0)))
    (d / "70000.json").write_text(
        json.dumps(dict(info(), port=70000, pid=1, protocol=1, started=1.0))
    )
    assert [i["port"] for i in wire.live_instances()] == [good]
    assert (d / "1.json").exists() and (d / "9990.json").exists()


@POSIX_ONLY
def test_symlinked_instance_is_not_followed_or_deleted(cfg, held, tmp_path):
    good = live(held, 1000.0)
    target = tmp_path / "elsewhere.json"
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        dead = probe.getsockname()[1]
    target.write_text(json.dumps(dict(info(), port=dead, pid=1, protocol=1, started=9.0)))
    link = wire.instances_dir() / f"{dead}.json"
    link.symlink_to(target)
    assert [i["port"] for i in wire.live_instances()] == [good]
    assert link.is_symlink() and target.exists()


@POSIX_ONLY
def test_group_writable_folder_yields_no_instances(cfg, held, caplog):
    live(held, 1000.0)
    os.chmod(wire.instances_dir(), 0o775)
    with caplog.at_level(logging.WARNING):
        assert wire.live_instances() == []
    assert "instances" in caplog.text


@POSIX_ONLY
def test_group_writable_meshwire_folder_yields_no_instances(cfg, held):
    live(held, 1000.0)
    os.chmod(cfg, 0o775)
    assert wire.live_instances() == []


def test_no_instances_folder_is_just_empty(cfg):
    assert wire.live_instances() == []


# --- the client's choice --------------------------------------------------------


def fake_instance(port, started, blend="", blender="4.5.15", probe="live"):
    return {
        "probe": probe,
        "port": port,
        "host": "127.0.0.1",
        "pid": 1,
        "protocol": 1,
        "addon": "0.5.0",
        "blender": blender,
        "blend": blend,
        "started": started,
    }


def refusing(monkeypatch) -> list[int]:
    """Make every dial fail as refused, and return the ports dialled, in order."""
    seen: list[int] = []

    async def refuse(host, port):
        seen.append(port)
        raise ConnectionRefusedError

    monkeypatch.setattr(asyncio, "open_connection", refuse)
    return seen


def dial(host, port) -> None:
    """Connect once; every failure is fine, the tests look at the ports dialled."""
    try:
        asyncio.run(BlenderClient(host, port).connect(timeout=1))
    except BlenderConnectionError:
        pass


def test_explicit_port_beats_discovery(cfg, monkeypatch):
    wire.ensure_token()

    def boom():
        raise AssertionError("discovery must not run")

    monkeypatch.setattr(wire, "live_instances", boom)
    seen = refusing(monkeypatch)
    dial("127.0.0.1", 9999)
    assert seen == [9999]


def test_discovery_picks_newest_and_logs_it(cfg, monkeypatch, caplog):
    wire.ensure_token()
    found = [
        fake_instance(9880, 2000.0, blend="/work/new.blend", blender="5.2.3"),
        fake_instance(9877, 1000.0),
    ]
    monkeypatch.setattr(wire, "live_instances", lambda: found)
    seen = refusing(monkeypatch)
    with caplog.at_level(logging.INFO, logger="meshwire.client"):
        dial("127.0.0.1", None)
    assert seen == [9880, 9877]
    text = caplog.text
    assert "9880" in text and "5.2.3" in text and "/work/new.blend" in text
    assert "the most recently started of 2" in text


def test_log_shows_file_values_escaped(cfg, monkeypatch, caplog):
    wire.ensure_token()
    found = [fake_instance(9877, 1.0, blend="/a\nFAKE LOG LINE.blend")]
    monkeypatch.setattr(wire, "live_instances", lambda: found)
    refusing(monkeypatch)
    with caplog.at_level(logging.INFO, logger="meshwire.client"):
        dial("127.0.0.1", None)
    assert "\nFAKE LOG LINE" not in caplog.text


def test_discovery_log_for_a_single_instance_has_no_count(cfg, monkeypatch, caplog):
    wire.ensure_token()
    monkeypatch.setattr(wire, "live_instances", lambda: [fake_instance(9877, 1.0)])
    seen = refusing(monkeypatch)
    with caplog.at_level(logging.INFO, logger="meshwire.client"):
        dial("127.0.0.1", None)
    assert seen == [9877]
    assert "9877" in caplog.text and "most recently started" not in caplog.text


def test_discovery_falls_back_to_9876(cfg, monkeypatch):
    wire.ensure_token()
    monkeypatch.setattr(wire, "live_instances", lambda: [])
    seen = refusing(monkeypatch)
    dial("127.0.0.1", None)
    assert seen == [9876]


def test_discovery_runs_off_the_event_loop(cfg, monkeypatch):
    import threading

    wire.ensure_token()
    seen = {}

    def spy():
        seen["thread"] = threading.current_thread()
        return []

    monkeypatch.setattr(wire, "live_instances", spy)
    refusing(monkeypatch)
    dial("127.0.0.1", None)
    assert seen["thread"] is not threading.main_thread()


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_hosts_discover(cfg, monkeypatch, host):
    wire.ensure_token()
    monkeypatch.setattr(wire, "live_instances", lambda: [fake_instance(9881, 1.0)])
    seen = refusing(monkeypatch)
    dial(host, None)
    assert seen == [9881]


def test_remote_host_never_discovers(cfg, monkeypatch):
    wire.ensure_token()

    def boom():
        raise AssertionError("a remote host must not read local instance files")

    monkeypatch.setattr(wire, "live_instances", boom)
    seen = refusing(monkeypatch)
    dial("10.0.0.5", None)
    assert seen == [9876]


def test_discovery_happens_again_on_every_open(cfg, monkeypatch):
    wire.ensure_token()
    answers = iter([[fake_instance(9877, 1.0)], [fake_instance(9879, 2.0)]])
    monkeypatch.setattr(wire, "live_instances", lambda: next(answers))
    seen = refusing(monkeypatch)

    async def twice():
        client = BlenderClient("127.0.0.1", None)
        for _ in range(2):
            with pytest.raises(BlenderConnectionError):
                await client.connect(timeout=1)

    asyncio.run(twice())
    assert seen == [9877, 9879]


def test_open_uses_the_discovered_port(cfg, monkeypatch):
    wire.ensure_token()
    monkeypatch.setattr(wire, "live_instances", lambda: [fake_instance(9881, 1.0)])
    seen = refusing(monkeypatch)
    client = BlenderClient("127.0.0.1", None)
    with pytest.raises(BlenderConnectionError, match="9881"):
        asyncio.run(client.connect(timeout=1))
    assert seen == [9881]


# --- falling through to the next instance ---------------------------------------


def test_a_foreign_listener_on_the_newest_port_does_not_shadow_a_healthy_blender(
    cfg, held, monkeypatch
):
    wire.ensure_token()
    older = live(held, 1000.0, blend="/old.blend")
    newer = live(held, 2000.0, blend="/new.blend")
    tried = []

    async def hello(self, reader, writer, token, timeout, voided):
        port = writer.get_extra_info("peername")[1]
        tried.append(port)
        if port == newer:
            raise _NotMeshwire("did not prove it holds the Meshwire token")

    monkeypatch.setattr(BlenderClient, "_hello", hello)

    async def go():
        client = BlenderClient("127.0.0.1", None)
        await client.connect(timeout=2)
        try:
            return client.port
        finally:
            await client.disconnect()

    assert asyncio.run(go()) == older
    assert tried == [newer, older]


# --- which failures fall through, and which stop -----------------------------------


async def healthy() -> MockBlenderServer:
    return await MockBlenderServer().start()


async def silent_server() -> tuple[asyncio.AbstractServer, int]:
    """Accepts the connection and never writes a byte: a Blender whose main thread is busy."""

    async def hold_open(reader, writer):
        await reader.read()

    server = await asyncio.start_server(hold_open, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def raw_server(reply: bytes | None) -> tuple[asyncio.AbstractServer, int]:
    """Answers the first line with ``reply`` and closes; ``None`` closes with no reply."""

    async def answer(reader, writer):
        await reader.readline()
        if reply is not None:
            writer.write(reply)
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(answer, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


def run_discovery(monkeypatch, newest_port, older_port, **kw):
    """Connect with the newest and an older instance on offer. Returns (port or error)."""
    found = [
        fake_instance(newest_port, 2000.0, **kw),
        fake_instance(older_port, 1000.0),
    ]
    monkeypatch.setattr(wire, "live_instances", lambda: found)

    async def go():
        client = BlenderClient("127.0.0.1", None)
        try:
            await client.connect(timeout=0.5)
            return client.port
        except BlenderConnectionError as e:
            return e
        finally:
            await client.disconnect()

    return go


def test_a_busy_newest_blender_is_an_error_not_a_silent_switch(cfg, monkeypatch):
    wire.ensure_token()

    async def scenario():
        older = await healthy()
        busy, busy_port = await silent_server()
        try:
            result = await run_discovery(monkeypatch, busy_port, older.port)()
            return result, busy_port, older
        finally:
            busy.close()
            await older.stop()

    result, busy_port, older = asyncio.run(scenario())
    assert isinstance(result, BlenderConnectionError)
    text = str(result)
    assert f"port {busy_port}" in text and f"{busy_port}.json" in text
    assert "did not answer within 0.5 s" in text and "may be busy" in text
    assert "--port" in text and "MESHWIRE_PORT" in text
    assert older.hellos == [] and str(older.port) not in text


def test_too_many_clients_from_the_newest_stops_there(cfg, monkeypatch):
    wire.ensure_token()

    async def scenario():
        older, newest = await healthy(), await healthy()
        newest.proof_error = {"code": wire.E_TOO_MANY, "message": "Too many clients: at most 8"}
        try:
            result = await run_discovery(monkeypatch, newest.port, older.port)()
            return result, newest.port, older
        finally:
            await older.stop()
            await newest.stop()

    result, newest_port, older = asyncio.run(scenario())
    assert isinstance(result, BlenderConnectionError)
    assert "Too many clients" in str(result)
    assert f"port {newest_port}" in str(result) and f"{newest_port}.json" in str(result)
    assert older.hellos == []


def test_an_old_addon_on_the_newest_port_stops_there(cfg, monkeypatch):
    wire.ensure_token()

    async def scenario():
        older, newest = await healthy(), await healthy()
        newest.hello_error = V040_UNKNOWN_METHOD
        try:
            result = await run_discovery(monkeypatch, newest.port, older.port)()
            return result, newest.port, older
        finally:
            await older.stop()
            await newest.stop()

    result, newest_port, older = asyncio.run(scenario())
    assert isinstance(result, BlenderConnectionError)
    assert "older than this server" in str(result) and f"port {newest_port}" in str(result)
    assert older.hellos == []


def test_a_relay_mismatch_on_the_newest_stops_there(cfg, monkeypatch):
    wire.ensure_token()
    monkeypatch.setenv("MESHWIRE_ADDON_ADDRESS", "127.0.0.1:1")

    async def scenario():
        older, newest = await healthy(), await healthy()
        try:
            result = await run_discovery(monkeypatch, newest.port, older.port)()
            return result, newest.port, older
        finally:
            await older.stop()
            await newest.stop()

    result, newest_port, older = asyncio.run(scenario())
    assert isinstance(result, BlenderConnectionError)
    assert "MESHWIRE_ADDON_ADDRESS" in str(result) and f"port {newest_port}" in str(result)
    assert older.hellos == []


def test_a_wrong_proof_from_the_newest_falls_through(cfg, monkeypatch):
    wire.ensure_token()

    async def scenario():
        older, newest = await healthy(), await healthy()
        newest.bad_proof = True
        try:
            return await run_discovery(monkeypatch, newest.port, older.port)(), older.port
        finally:
            await older.stop()
            await newest.stop()

    result, older_port = asyncio.run(scenario())
    assert result == older_port


@pytest.mark.parametrize(
    "reply",
    [None, b"HTTP/1.0 400 Bad Request\r\n\r\n", b"[1, 2]\n", b'{"result": {"protocol": 1}}\n'],
    ids=["closed", "not-json", "not-an-object", "no-proof"],
)
def test_a_peer_that_is_not_meshwire_falls_through(cfg, monkeypatch, reply):
    wire.ensure_token()

    async def scenario():
        older = await healthy()
        foreign, foreign_port = await raw_server(reply)
        try:
            return await run_discovery(monkeypatch, foreign_port, older.port)(), older.port
        finally:
            foreign.close()
            await older.stop()

    result, older_port = asyncio.run(scenario())
    assert result == older_port


def test_a_refused_newest_falls_through(cfg, monkeypatch):
    wire.ensure_token()
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        dead = probe.getsockname()[1]

    async def scenario():
        older = await healthy()
        try:
            return await run_discovery(monkeypatch, dead, older.port)(), older.port
        finally:
            await older.stop()

    result, older_port = asyncio.run(scenario())
    assert result == older_port


def test_an_unknown_newest_is_tried_first(cfg, monkeypatch):
    wire.ensure_token()

    async def scenario():
        older, newest = await healthy(), await healthy()
        try:
            result = await run_discovery(monkeypatch, newest.port, older.port, probe="unknown")()
            return result, newest.port, older
        finally:
            await older.stop()
            await newest.stop()

    result, newest_port, older = asyncio.run(scenario())
    assert result == newest_port
    assert older.hellos == []


def test_every_instance_failing_names_them_all(cfg, held, monkeypatch):
    wire.ensure_token()
    first = live(held, 1000.0)
    second = live(held, 2000.0)

    async def hello(self, reader, writer, token, timeout, voided):
        raise _NotMeshwire(f"refused handshake on {writer.get_extra_info('peername')[1]}")

    monkeypatch.setattr(BlenderClient, "_hello", hello)
    client = BlenderClient("127.0.0.1", None)
    with pytest.raises(BlenderConnectionError) as raised:
        asyncio.run(client.connect(timeout=2))
    text = str(raised.value)
    for port in (first, second):
        assert str(port) in text and f"{port}.json" in text
        assert f"refused handshake on {port}" in text
    assert "--port" in text and "MESHWIRE_PORT" in text


def test_an_explicit_port_never_falls_through(cfg, held, monkeypatch):
    wire.ensure_token()
    other = live(held, 2000.0)
    fixed = live(held, 1000.0)
    tried = []

    async def hello(self, reader, writer, token, timeout, voided):
        tried.append(writer.get_extra_info("peername")[1])
        raise BlenderConnectionError("explicit port failed")

    monkeypatch.setattr(BlenderClient, "_hello", hello)
    monkeypatch.setattr(wire, "live_instances", lambda: pytest.fail("no discovery"))
    client = BlenderClient("127.0.0.1", fixed)
    with pytest.raises(BlenderConnectionError, match="explicit port failed"):
        asyncio.run(client.connect(timeout=2))
    assert tried == [fixed] and other not in tried


# --- the server's port setting --------------------------------------------------


def test_port_precedence_flag_then_env_then_discovery(monkeypatch):
    monkeypatch.delenv("MESHWIRE_PORT", raising=False)
    assert server_module.configured_port(None) is None
    monkeypatch.setenv("MESHWIRE_PORT", "9880")
    assert server_module.configured_port(None) == 9880
    assert server_module.configured_port(9877) == 9877


def test_empty_env_port_means_unset(monkeypatch):
    monkeypatch.setenv("MESHWIRE_PORT", "  ")
    assert server_module.configured_port(None) is None


@pytest.mark.parametrize("bad", ["abc", "0", "80", "70000", "-1"])
def test_bad_env_port_is_an_error_naming_the_variable(monkeypatch, bad):
    monkeypatch.setenv("MESHWIRE_PORT", bad)
    with pytest.raises(ValueError, match="MESHWIRE_PORT"):
        server_module.configured_port(None)
