"""Several Blenders at once: port binding, instance files and how the server finds one.

The add-on half runs Blender-free on real loopback sockets, through the fixtures of
tests/test_socket_server.py. The server half uses the server's own wire.py.
"""

import asyncio
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
from mcp_blender.blender_client import BlenderClient, BlenderConnectionError
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
        assert set(data) == {"port", "pid", "protocol", "addon", "blender", "blend", "started"}
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


def test_stale_instance_file_is_removed(cfg, held):
    good = live(held, 1000.0)
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        dead = probe.getsockname()[1]
    stale = wire.write_instance(dead, info(started=5000.0))
    assert [i["port"] for i in wire.live_instances()] == [good]
    assert not stale.exists()


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


def fake_instance(port, started, blend="", blender="4.5.15"):
    return {
        "port": port,
        "pid": 1,
        "protocol": 1,
        "addon": "0.5.0",
        "blender": blender,
        "blend": blend,
        "started": started,
    }


def test_explicit_port_beats_discovery(monkeypatch):
    def boom():
        raise AssertionError("discovery must not run")

    monkeypatch.setattr(wire, "live_instances", boom)
    client = BlenderClient("127.0.0.1", 9999)
    assert asyncio.run(client._resolve_port()) == 9999
    assert client.port == 9999


def test_discovery_picks_newest_and_logs_it(monkeypatch, caplog):
    found = [
        fake_instance(9880, 2000.0, blend="/work/new.blend", blender="5.2.3"),
        fake_instance(9877, 1000.0),
    ]
    monkeypatch.setattr(wire, "live_instances", lambda: found)
    client = BlenderClient("127.0.0.1", None)
    with caplog.at_level(logging.INFO, logger="meshwire.client"):
        assert asyncio.run(client._resolve_port()) == 9880
    assert client.port == 9880
    text = caplog.text
    assert "9880" in text and "5.2.3" in text and "/work/new.blend" in text
    assert "the most recently started of 2" in text


def test_discovery_log_for_a_single_instance_has_no_count(monkeypatch, caplog):
    monkeypatch.setattr(wire, "live_instances", lambda: [fake_instance(9877, 1.0)])
    client = BlenderClient("127.0.0.1", None)
    with caplog.at_level(logging.INFO, logger="meshwire.client"):
        assert asyncio.run(client._resolve_port()) == 9877
    assert "9877" in caplog.text and "most recently started" not in caplog.text


def test_discovery_falls_back_to_9876(monkeypatch):
    monkeypatch.setattr(wire, "live_instances", lambda: [])
    client = BlenderClient("127.0.0.1", None)
    assert asyncio.run(client._resolve_port()) == 9876


def test_discovery_runs_off_the_event_loop(monkeypatch):
    import threading

    seen = {}

    def spy():
        seen["thread"] = threading.current_thread()
        return []

    monkeypatch.setattr(wire, "live_instances", spy)
    asyncio.run(BlenderClient("127.0.0.1", None)._resolve_port())
    assert seen["thread"] is not threading.main_thread()


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_hosts_discover(monkeypatch, host):
    monkeypatch.setattr(wire, "live_instances", lambda: [fake_instance(9881, 1.0)])
    assert asyncio.run(BlenderClient(host, None)._resolve_port()) == 9881


def test_remote_host_never_discovers(monkeypatch):
    def boom():
        raise AssertionError("a remote host must not read local instance files")

    monkeypatch.setattr(wire, "live_instances", boom)
    assert asyncio.run(BlenderClient("10.0.0.5", None)._resolve_port()) == 9876


def test_discovery_happens_again_on_every_open(monkeypatch):
    answers = iter([[fake_instance(9877, 1.0)], [fake_instance(9879, 2.0)]])
    monkeypatch.setattr(wire, "live_instances", lambda: next(answers))
    client = BlenderClient("127.0.0.1", None)
    assert asyncio.run(client._resolve_port()) == 9877
    assert asyncio.run(client._resolve_port()) == 9879


def test_open_uses_the_discovered_port(cfg, monkeypatch):
    wire.ensure_token()
    monkeypatch.setattr(wire, "live_instances", lambda: [fake_instance(9881, 1.0)])
    seen = []

    async def refuse(host, port):
        seen.append(port)
        raise ConnectionRefusedError

    monkeypatch.setattr(asyncio, "open_connection", refuse)
    client = BlenderClient("127.0.0.1", None)
    with pytest.raises(BlenderConnectionError, match="9881"):
        asyncio.run(client.connect(timeout=1))
    assert seen == [9881]


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
