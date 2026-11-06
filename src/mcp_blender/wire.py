"""Wire constants and token helpers shared by the Meshwire add-on and the MCP server.

This file exists twice, byte for byte: once in the add-on and once in the server
package, because the two ship separately. tests/test_wire.py compares the copies and
allows it to import only a short list of standard-library modules. It must import
nothing from Blender or from either package.
"""

import hashlib
import hmac
import os
import secrets
import stat
import sys
from pathlib import Path

PROTOCOL = 1
HELLO_MAX = 4096  # most bytes the first line may hold
HELLO_SECONDS = 2.0  # time from accept to a finished handshake (hello, then hello_proof)
MIN_TOKEN = 32  # shortest token ensure_token() will keep
ADDON_LABEL = "meshwire-addon"  # what the add-on proves with
CLIENT_LABEL = "meshwire-client"  # what the client proves with

# JSON-RPC error codes the add-on sends on its own, outside any tool call.
E_UNAUTHORIZED = -32001  # the client's proof was wrong, or the second line was not hello_proof
E_PROTOCOL = -32002  # the first line was not a hello, or the protocol versions differ
E_TOO_MANY = -32003  # all client slots are taken
E_TOO_LARGE = -32004  # a request line passed the inbound cap
E_REPLY_TOO_LARGE = -32005  # a reply would not fit in the write buffer
E_PARSE = -32700  # the line was not UTF-8, not JSON, or not a JSON object


def config_dir() -> Path:
    """Where Meshwire keeps its token and instance files."""
    override = os.environ.get("MESHWIRE_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / "meshwire"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "meshwire"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / "meshwire"


def token_path() -> Path:
    return config_dir() / "token"


def instances_dir() -> Path:
    return config_dir() / "instances"


def read_token() -> str | None:
    """The token to use: MESHWIRE_TOKEN if set, else the token file, else None."""
    env = os.environ.get("MESHWIRE_TOKEN", "").strip()
    if env:
        return env
    try:
        text = token_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _read_file_token(path: Path) -> str | None:
    """The token in the file, never following a symlink. None when absent."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise OSError(f"{path} must be a plain file, not a symlink: {e.strerror}") from e
    with os.fdopen(fd, "rb") as handle:
        return handle.read(4096).decode("utf-8", "replace").strip()


def ensure_token() -> str:
    """Return the token, creating the token file (0600, in a 0700 folder) on first use.

    The token is never written to a file with looser permissions, and a symlink at the
    path is refused. A file is created whole: written to a private temp file, then
    linked into place, so no reader sees it empty and two first starts agree.
    """
    env = os.environ.get("MESHWIRE_TOKEN", "").strip()
    if env:
        return env
    path = token_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise OSError(f"{path} is a symlink; Meshwire will not follow it. Remove it and retry")
    existing = _read_file_token(path)
    if existing is not None and len(existing) >= MIN_TOKEN:
        _tighten(path)
        return existing

    token = secrets.token_urlsafe(32)
    tmp = path.with_name(f".token.{os.getpid()}.{secrets.token_hex(4)}")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token + "\n")
        if existing is not None:
            # An empty or short file is stale (Meshwire never leaves one). Replace it,
            # which also replaces rather than follows anything at the path.
            os.replace(tmp, path)
            return _read_file_token(path) or token
        try:
            os.link(tmp, path)
        except FileExistsError:
            winner = _read_file_token(path)
            if winner and len(winner) >= MIN_TOKEN:
                _tighten(path)
                return winner
            os.replace(tmp, path)
            return _read_file_token(path) or token
        except OSError:
            # No hard links here (some Windows and network volumes): exclusive create.
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(token + "\n")
        return token
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _tighten(path: Path) -> None:
    """Make a looser token file 0600 on POSIX, and say so on stderr."""
    if sys.platform == "win32":
        return
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & 0o077:
            os.chmod(path, 0o600)
            print(f"Meshwire: token file {path} was mode {mode:04o}; set to 0600", file=sys.stderr)
    except OSError:
        pass


def new_nonce() -> str:
    return secrets.token_urlsafe(32)


def proof(token: str, label: str, a: str, b: str) -> str:
    """HMAC-SHA256 of ``label``, ``a`` and ``b`` keyed by the token, as 64 hex characters."""
    return hmac.new(token.encode(), f"{label}\n{a}\n{b}".encode(), hashlib.sha256).hexdigest()


def hello_request(nonce: str, msg_id, client: str = "meshwire") -> dict:
    """The first line a client sends. It carries a nonce, never the token."""
    return {
        "jsonrpc": "2.0",
        "method": "hello",
        "params": {"protocol": PROTOCOL, "client": client, "nonce": nonce},
        "id": msg_id,
    }


def hello_proof_request(proof_hex: str, msg_id) -> dict:
    """The second line a client sends, after it has checked the add-on's proof."""
    return {
        "jsonrpc": "2.0",
        "method": "hello_proof",
        "params": {"proof": proof_hex},
        "id": msg_id,
    }
