"""Wire constants and token helpers shared by the Meshwire add-on and the MCP server.

This file exists twice, byte for byte: once in the add-on and once in the server
package, because the two ship separately. tests/test_wire.py compares the copies and
allows it to import only a short list of standard-library modules. It must import
nothing from Blender or from either package.
"""

import os
import secrets
import stat
import sys
from pathlib import Path

PROTOCOL = 1
HELLO_MAX = 4096  # most bytes the first line may hold
HELLO_SECONDS = 2.0  # time from accept to a good hello

# JSON-RPC error codes the add-on sends on its own, outside any tool call.
E_UNAUTHORIZED = -32001  # the hello token was missing or wrong
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


def ensure_token() -> str:
    """Return the token, creating the 0600 file on first use."""
    existing = read_token()
    if existing:
        _tighten(token_path())
        return existing
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        # Another process won the race, or the file is empty: overwrite only if empty.
        if path.read_text(encoding="utf-8").strip():
            return path.read_text(encoding="utf-8").strip()
        fd = os.open(path, os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    return token


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


def hello_request(token: str, msg_id, client: str = "meshwire") -> dict:
    """The first line a client sends."""
    return {
        "jsonrpc": "2.0",
        "method": "hello",
        "params": {"token": token, "protocol": PROTOCOL, "client": client},
        "id": msg_id,
    }
