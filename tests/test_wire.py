"""The wire constants live in two files that must never drift apart."""

import ast
import hashlib
import hmac
import os
import stat
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ADDON_WIRE = ROOT / "addon" / "blender_mcp_addon" / "wire.py"
SERVER_WIRE = ROOT / "src" / "mcp_blender" / "wire.py"

# wire.py is loaded by the add-on inside Blender and by the server outside it.
ALLOWED_IMPORTS = {"os", "sys", "stat", "secrets", "pathlib", "hmac", "hashlib"}


def load_wire() -> dict:
    namespace: dict = {"__name__": "wire_under_test"}
    exec(compile(ADDON_WIRE.read_text(), str(ADDON_WIRE), "exec"), namespace)
    return namespace


@pytest.fixture
def wire(monkeypatch, tmp_path):
    monkeypatch.delenv("MESHWIRE_TOKEN", raising=False)
    monkeypatch.setenv("MESHWIRE_CONFIG_DIR", str(tmp_path / "cfg"))
    return type("Wire", (), load_wire())


def test_wire_copies_are_identical():
    assert ADDON_WIRE.read_bytes() == SERVER_WIRE.read_bytes()


def test_wire_imports_only_the_allowlist():
    tree = ast.parse(ADDON_WIRE.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            found.add((node.module or "").split(".")[0])
    assert found <= ALLOWED_IMPORTS, found - ALLOWED_IMPORTS


def test_error_codes():
    namespace = load_wire()
    assert namespace["E_PARSE"] == -32700
    assert namespace["E_TOO_MANY"] == -32003
    assert namespace["E_TOO_LARGE"] == -32004
    assert namespace["E_REPLY_TOO_LARGE"] == -32005
    assert namespace["E_UNAUTHORIZED"] == -32001
    assert namespace["E_PROTOCOL"] == -32002


def test_handshake_constants():
    namespace = load_wire()
    assert namespace["PROTOCOL"] == 1
    assert namespace["HELLO_MAX"] == 4096
    assert namespace["HELLO_SECONDS"] == 2.0


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_token_file_created_0600(wire):
    token = wire.ensure_token()
    path = wire.token_path()
    assert path.read_text().strip() == token
    assert len(token) >= 40
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert wire.ensure_token() == token  # a second call reads, never rewrites


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_loose_token_file_is_tightened_with_a_warning(wire, capsys):
    token = wire.ensure_token()
    os.chmod(wire.token_path(), 0o644)
    assert wire.ensure_token() == token
    assert stat.S_IMODE(os.stat(wire.token_path()).st_mode) == 0o600
    err = capsys.readouterr().err
    assert "0600" in err and token not in err


def test_env_token_overrides_file(wire, monkeypatch):
    from_file = wire.ensure_token()
    monkeypatch.setenv("MESHWIRE_TOKEN", "from-env")
    assert wire.read_token() == "from-env"
    assert wire.read_token() != from_file
    monkeypatch.delenv("MESHWIRE_TOKEN")
    assert wire.read_token() == from_file


def test_read_token_is_none_without_file_or_env(wire):
    assert wire.read_token() is None


def test_config_dir_per_platform(wire, monkeypatch, tmp_path):
    monkeypatch.delenv("MESHWIRE_CONFIG_DIR")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    ns = load_wire()
    cases = {
        "linux": tmp_path / "xdg" / "meshwire",
        "darwin": tmp_path / "home" / "Library" / "Application Support" / "meshwire",
        "win32": tmp_path / "appdata" / "meshwire",
    }
    for platform, expected in cases.items():
        monkeypatch.setattr(sys, "platform", platform)
        assert ns["config_dir"]() == expected, platform
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert ns["config_dir"]() == tmp_path / "home" / ".config" / "meshwire"
    monkeypatch.setenv("MESHWIRE_CONFIG_DIR", str(tmp_path / "override"))
    assert ns["config_dir"]() == tmp_path / "override"
    assert ns["token_path"]() == tmp_path / "override" / "token"
    assert ns["instances_dir"]() == tmp_path / "override" / "instances"


def test_hello_request_shape(wire):
    request = wire.hello_request("N" * 20, 7, client="meshwire 1.2.3")
    assert request == {
        "jsonrpc": "2.0",
        "method": "hello",
        "params": {"protocol": 1, "client": "meshwire 1.2.3", "nonce": "N" * 20},
        "id": 7,
    }
    assert "token" not in request["params"]


def test_hello_proof_request_shape(wire):
    assert wire.hello_proof_request("ab", 9) == {
        "jsonrpc": "2.0",
        "method": "hello_proof",
        "params": {"proof": "ab"},
        "id": 9,
    }


def test_proof_matches_the_stated_hmac(wire):
    assert wire.ADDON_LABEL == "meshwire-addon" and wire.CLIENT_LABEL == "meshwire-client"
    expected = hmac.new(b"tok", b"meshwire-addon\nA\nB", hashlib.sha256).hexdigest()
    assert wire.proof("tok", wire.ADDON_LABEL, "A", "B") == expected
    assert len(expected) == 64
    # The two directions differ, so a proof cannot be replayed back at its sender.
    assert wire.proof("tok", wire.CLIENT_LABEL, "B", "A") != expected


def test_new_nonce_is_urlsafe_and_fresh(wire):
    a, b = wire.new_nonce(), wire.new_nonce()
    assert a != b and 16 <= len(a) <= 128


# --- ensure_token hardening ----------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_empty_loose_token_file_ends_0600_with_a_good_token(wire):
    path = wire.token_path()
    path.parent.mkdir(parents=True)
    path.write_text("")
    os.chmod(path, 0o644)
    token = wire.ensure_token()
    assert len(token) >= 32
    assert path.read_text().strip() == token
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_short_token_file_is_replaced(wire):
    path = wire.token_path()
    path.parent.mkdir(parents=True)
    path.write_text("short\n")
    token = wire.ensure_token()
    assert len(token) >= 32 and path.read_text().strip() == token
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_symlink_at_the_token_path_is_refused(wire, tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("")
    path = wire.token_path()
    path.parent.mkdir(parents=True)
    path.symlink_to(target)
    with pytest.raises(OSError) as info:
        wire.ensure_token()
    assert str(path) in str(info.value)
    assert target.read_text() == ""  # nothing was written through the link


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_dangling_symlink_is_refused(wire, tmp_path):
    path = wire.token_path()
    path.parent.mkdir(parents=True)
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(OSError, match="symlink"):
        wire.ensure_token()
    assert not (tmp_path / "missing").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_config_dir_is_created_0700(wire):
    wire.ensure_token()
    assert stat.S_IMODE(os.stat(wire.config_dir()).st_mode) == 0o700


def test_concurrent_first_starts_agree_with_the_file(wire):
    for _ in range(20):
        path = wire.token_path()
        if path.exists():
            path.unlink()
        barrier = threading.Barrier(8)
        got: list = []

        def start():
            barrier.wait()
            got.append(wire.ensure_token())

        threads = [threading.Thread(target=start) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(set(got)) == 1, "two first starts returned different tokens"
        assert path.read_text().strip() == got[0]
        assert not list(path.parent.glob(".token.*")), "temp files left behind"
