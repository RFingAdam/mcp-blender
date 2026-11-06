"""Wire constants and token helpers shared by the Meshwire add-on and the MCP server.

This file exists twice, byte for byte: once in the add-on and once in the server
package, because the two ship separately. tests/test_wire.py compares the copies and
allows it to import only a short list of standard-library modules. It must import
nothing from Blender or from either package.
"""

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import socket
import stat
import sys
import time
from pathlib import Path

logger = logging.getLogger("meshwire.wire")

PROTOCOL = 1
PORT_FIRST = 9876  # the add-on scans PORT_FIRST to PORT_LAST for a free port
PORT_LAST = 9885
PORT_MIN = 1024  # lowest port either side accepts when one is named
PORT_MAX = 65535
PROBE_SECONDS = 0.2  # how long live_instances() waits for a TCP connect
INSTANCE_MAX = 65536  # most bytes read from one instance file
INSTANCE_FIELDS = ("port", "host", "pid", "protocol", "addon", "blender", "blend", "started")
HELLO_MAX = 4096  # most bytes the first line may hold
HELLO_SECONDS = 2.0  # each handshake step: hello from accept, hello_proof from the hello reply
MIN_TOKEN = 32  # shortest token ensure_token() will keep
SETTLE_SECONDS = 2.0  # how long a loser of a first-start race waits for the winner's token
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
    """The token to use: MESHWIRE_TOKEN if set, else the token file, else None.

    The file is held to the same rules the writer enforces (no symlink, ours, in a
    folder nobody else can write to), so a token another user could have swapped in is
    refused with an OSError rather than trusted. MESHWIRE_TOKEN has no file to check.
    """
    env = os.environ.get("MESHWIRE_TOKEN", "").strip()
    if env:
        return env
    path = token_path()
    try:
        _check_dir(path.parent)
    except FileNotFoundError:
        return None
    _refuse_symlink(path)
    text = _read_file_token(path)
    if text is None:
        return None
    _check_file_owner(path)
    return text or None


def _refuse_symlink(path: Path) -> None:
    if path.is_symlink():
        raise OSError(f"{path} is a symlink; Meshwire will not follow it. Remove it and retry")


def _read_file_token(path: Path) -> str | None:
    """The token in the file, never following a symlink. None when absent."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as e:
        if path.is_symlink():
            raise OSError(f"{path} must be a plain file, not a symlink: {e.strerror}") from e
        raise OSError(f"Cannot read the Meshwire token at {path}: {e.strerror}") from e
    with os.fdopen(fd, "rb") as handle:
        return handle.read(4096).decode("utf-8", "replace").strip()


def _check_dir(directory: Path) -> None:
    """POSIX: the Meshwire folder must be ours and closed to writes by anyone else.

    Only this folder is checked, not its parents. A writable folder would let another
    user rename a token file of their own over ours.
    """
    if sys.platform == "win32" or not hasattr(os, "getuid"):
        return
    info = os.stat(directory)
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise OSError(
            f"The Meshwire folder {directory} is not owned by you or can be written by other "
            f"users, so its token could be replaced. Fix it with: chmod 700 {directory}"
        )


def _check_file_owner(path: Path) -> None:
    if sys.platform == "win32" or not hasattr(os, "getuid"):
        return
    if os.stat(path).st_uid != os.getuid():
        raise OSError(f"The Meshwire token file {path} is not owned by you. Delete it and retry")


def _secure_file(path: Path) -> None:
    """POSIX: the token file must be ours and 0600. Tighten a looser one, or refuse it."""
    if sys.platform == "win32" or not hasattr(os, "getuid"):
        return
    _check_file_owner(path)
    info = os.stat(path)
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        try:
            os.chmod(path, 0o600)
        except OSError as e:
            raise OSError(
                f"The Meshwire token file {path} (mode {mode:04o}) can be read by other users "
                f"and could not be tightened: {e.strerror}. Run: chmod 600 {path}"
            ) from e
        print(f"Meshwire: token file {path} was mode {mode:04o}; set to 0600", file=sys.stderr)


def _settled(path: Path) -> str:
    """The token in the file, waiting up to SETTLE_SECONDS for a writer that is mid-create."""
    end = time.monotonic() + SETTLE_SECONDS
    while True:
        text = _read_file_token(path)
        if text is not None and len(text) >= MIN_TOKEN:
            _secure_file(path)
            return text
        if time.monotonic() >= end:
            raise OSError(
                f"The Meshwire token file {path} is empty or too short. "
                "Delete it and start the server again"
            )
        time.sleep(0.02)


def _write_fsync(fd: int, token: str) -> None:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def ensure_token() -> str:
    """Return the token, creating the token file (0600, in a 0700 folder) on first use.

    The token is never written to a file with looser permissions, and a symlink at the
    path is refused. A file is created whole: written and synced to a private temp
    file, then linked into place, so no reader sees it empty. Whoever loses a race
    reads the winner's file, so the returned token is always the file's contents.
    """
    env = os.environ.get("MESHWIRE_TOKEN", "").strip()
    if env:
        return env
    path = token_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _check_dir(path.parent)
    _refuse_symlink(path)
    existing = _read_file_token(path)
    if existing is not None and len(existing) >= MIN_TOKEN:
        _secure_file(path)
        return existing

    token = secrets.token_urlsafe(32)
    tmp = path.with_name(f".token.{os.getpid()}.{secrets.token_hex(4)}")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        _write_fsync(os.open(tmp, flags, 0o600), token)
        if existing is not None:
            # An empty or short file is stale (Meshwire does not leave one). Replace it,
            # which also replaces rather than follows anything at the path.
            os.replace(tmp, path)
            return _settled(path)
        try:
            os.link(tmp, path)
        except FileExistsError:
            return _settled(path)
        except OSError:
            # No hard links here (FAT, exFAT, some network volumes): create the file
            # exclusively and write it. A loser of that race reads the winner's file.
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                return _settled(path)
            _write_fsync(fd, token)
        return token
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def endpoint(host: str, port: int) -> str:
    """``host:port`` as both sides compare it: no IPv4-mapped prefix or zone, IPv6 in brackets."""
    host = host.split("%", 1)[0]
    if host.lower().startswith("::ffff:") and "." in host:
        host = host[7:]
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def new_nonce() -> str:
    return secrets.token_urlsafe(32)


def proof(token: str, label: str, *parts: str) -> str:
    """HMAC-SHA256 of the label and parts joined by newlines, keyed by the token, as 64 hex."""
    message = "\n".join((label, *parts))
    return hmac.new(token.encode(), message.encode(), hashlib.sha256).hexdigest()


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


_INSTANCE_NAME = re.compile(r"[0-9]{1,5}\.json")
_TEMP_NAME = re.compile(r"\.[0-9]+\.[0-9]+\.[0-9a-f]{8}\.tmp")
TEMP_MAX_AGE = 3600.0  # seconds before clean_stale_temps() treats a leftover temp file as dead
WILDCARD = {"0.0.0.0", "::", ""}


def _make_private_dir(directory: Path) -> None:
    """Create ``directory`` at 0700 if it is missing. The mode is not left to the umask."""
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        return
    if sys.platform != "win32":
        os.chmod(directory, 0o700)  # mkdir's mode is masked by the umask; 0700 only loses bits


def write_instance(port: int, info: dict) -> Path:
    """Publish ``instances/<port>.json`` for this Blender and return its path.

    ``info`` supplies addon, blender, blend and host (the address the add-on bound).
    pid, protocol and started are filled in unless given. There is no token in the file.
    It is written whole to a private temp file in the same folder and renamed into
    place, so a reader never sees half of it.
    The Meshwire folder and the instances folder are created at 0700 when missing and
    held to the same checks as the token's folder.
    """
    base, directory = config_dir(), instances_dir()
    base.parent.mkdir(parents=True, exist_ok=True)
    _make_private_dir(base)
    _make_private_dir(directory)
    _check_dir(base)
    _check_dir(directory)
    record = {
        "port": port,
        "host": "127.0.0.1",
        "pid": os.getpid(),
        "protocol": PROTOCOL,
        "addon": "unknown",
        "blender": "unknown",
        "blend": "",
        "started": time.time(),
    }
    record.update({k: v for k, v in info.items() if k in INSTANCE_FIELDS and k != "port"})
    path = directory / f"{port}.json"
    tmp = directory / f".{port}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(tmp, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return path


def remove_instance(port: int) -> None:
    """Delete this port's instance file if it is there and is a plain file."""
    path = instances_dir() / f"{port}.json"
    try:
        if stat.S_ISREG(os.lstat(path).st_mode):
            os.unlink(path)
    except OSError:
        pass


def clean_stale_temps() -> None:
    """Delete temp files an interrupted write_instance left: plain files, over an hour old."""
    try:
        entries = list(os.scandir(instances_dir()))
    except OSError:
        return
    cutoff = time.time() - TEMP_MAX_AGE
    for entry in entries:
        try:
            if not _TEMP_NAME.fullmatch(entry.name):
                continue
            info = os.lstat(entry.path)
            if stat.S_ISREG(info.st_mode) and info.st_mtime < cutoff:
                os.unlink(entry.path)
        except OSError:
            pass


def _read_instance(path: Path) -> tuple[dict, tuple[int, int]] | None:
    """The record in ``path`` and its (inode, mtime_ns), or None when it is not well formed."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(INSTANCE_MAX + 1)
    finally:
        os.close(fd)
    if len(raw) > INSTANCE_MAX:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or any(k not in data for k in INSTANCE_FIELDS):
        return None
    port, started = data["port"], data["started"]
    if type(port) is not int or not PORT_MIN <= port <= PORT_MAX:
        return None
    if type(started) not in (int, float) or type(data["host"]) is not str:
        return None
    return {k: data[k] for k in INSTANCE_FIELDS}, (opened.st_ino, opened.st_mtime_ns)


def _probe(host: str, port: int, timeout: float) -> str:
    """Try a TCP connect: "live", "refused" (nothing listens) or "unknown" (anything else).

    A timeout is "unknown", not "refused": a busy Blender with a full backlog times out,
    and Windows takes longer than the timeout to refuse a loopback connect.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "live"
    except ConnectionRefusedError:
        return "refused"
    except OSError:
        return "unknown"


def _probe_host(host: str) -> str | None:
    """Where to probe an instance bound to ``host``, or None if this machine cannot reach it."""
    if host == "::" or host == "::1":
        return "::1"
    if host in WILDCARD or host.lower() == "localhost":
        return "127.0.0.1"
    if host.startswith("127."):
        return host
    return None


def _delete_if_unchanged(path: str, ident: tuple[int, int]) -> None:
    """Unlink a stale instance file unless it was replaced since it was read."""
    try:
        now = os.lstat(path)
        if stat.S_ISREG(now.st_mode) and (now.st_ino, now.st_mtime_ns) == ident:
            os.unlink(path)
    except OSError:
        pass


def live_instances() -> list[dict]:
    """The Blenders that may be running, newest first by ``started``.

    Each record carries ``probe``: "live" or "unknown".

    A file counts only if it is a plain file called ``<number>.json`` with every field,
    a port in range that matches its name, and an address this machine can reach
    (loopback or a wildcard; others are left alone, neither used nor deleted). The port
    is probed at the recorded address. "live" chooses the instance. "refused" means nothing
    listens: the file is stale and is deleted, if it is still the file that was read.
    "unknown" (a timeout, say) keeps the file and still lists the instance, in its place: only
    the handshake can say whether a busy Blender is there, and skipping it would pick an older one.
    Symlinks are never followed. On POSIX the Meshwire folder and the instances folder
    must be ours and closed to writes by others, as the token's folder must be; otherwise
    nothing is trusted and the result is empty.
    """
    directory = instances_dir()
    try:
        _check_dir(config_dir())
        _check_dir(directory)
        entries = list(os.scandir(directory))
    except FileNotFoundError:
        return []
    except OSError as e:
        logger.warning("Ignoring the Meshwire instances in %s: %s", directory, e)
        return []
    found = []
    for entry in entries:
        if not _INSTANCE_NAME.fullmatch(entry.name):
            continue
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
        except OSError:
            continue
        read = _read_instance(Path(entry.path))
        if read is None or entry.name != f"{read[0]['port']}.json":
            continue
        record, ident = read
        target = _probe_host(record["host"])
        if target is None:
            continue
        answer = _probe(target, record["port"], PROBE_SECONDS)
        if answer == "refused":
            _delete_if_unchanged(entry.path, ident)
            continue
        if answer != "live":
            logger.info(
                "Port %s did not answer within %.1f s; keeping %s and leaving it to the handshake",
                record["port"],
                PROBE_SECONDS,
                entry.name,
            )
        found.append({**record, "probe": answer})
    found.sort(key=lambda r: (-r["started"], r["port"]))
    return found
